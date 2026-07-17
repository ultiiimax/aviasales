from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast

from flight_hunter.agent.chat import IntentDraft

_ALLOWED_FIELDS = {
    "origin_query",
    "destination_query",
    "departure_date",
    "return_date",
    "date_hint",
    "trip_shape",
    "date_mode",
    "adults",
    "children",
    "infants",
    "currency",
    "nearby_radius_km",
    "requested_strategies",
    "baggage_preference",
    "wants_watch",
}
_FORBIDDEN_FIELDS = {
    "amount_minor",
    "price",
    "currency_price",
    "provider_offer_id",
    "booking_url",
    "booking_link",
    "freshness",
    "observed_at",
    "airline",
    "flight_number",
    "airport_codes",
}
_TRIP_SHAPES = {"one_way", "round_trip", "open_jaw", "multi_city"}
_DATE_MODES = {"exact", "flexible", "range", "rolling_90_days"}
_STRATEGIES = {
    "direct",
    "through_ticket",
    "split_ticket",
    "self_transfer",
    "hidden_city",
}
_BAGGAGE = {"checked", "carry_on", "none", "unspecified"}
_ENV_ALLOWLIST = {
    "APPDATA",
    "CODEX_HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "OS",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
}


@dataclass(frozen=True, slots=True)
class CodexIntentDraft:
    origin_query: str | None = None
    destination_query: str | None = None
    departure_date: str | None = None
    return_date: str | None = None
    date_hint: str | None = None
    trip_shape: str | None = None
    date_mode: str | None = None
    adults: int | None = None
    children: int | None = None
    infants: int | None = None
    currency: str | None = None
    nearby_radius_km: int | None = None
    requested_strategies: tuple[str, ...] = ()
    baggage_preference: str = "unspecified"
    wants_watch: bool = False


@dataclass(frozen=True, slots=True)
class CodexIntentValidationResult:
    code: str
    message: str
    draft: CodexIntentDraft | None


class CodexIntentDraftValidator:
    def __init__(self, *, max_output_bytes: int = 16_384) -> None:
        self._max_output_bytes = max_output_bytes

    def validate_json(self, raw_output: str) -> CodexIntentValidationResult:
        if len(raw_output.encode("utf-8")) > self._max_output_bytes:
            return _invalid("output_too_large", "Codex output exceeded the byte limit")
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError:
            return _invalid("invalid_json", "Codex output was not JSON")
        if not isinstance(payload, dict):
            return _invalid("invalid_shape", "Codex output must be an object")
        payload_map = cast("dict[str, object]", payload)
        if any(field in payload_map for field in _FORBIDDEN_FIELDS):
            return _invalid(
                "forbidden_field",
                "Codex output cannot contain prices, provider facts, or booking data",
            )
        if any(field not in _ALLOWED_FIELDS for field in payload_map):
            return _invalid("unknown_field", "Codex output contained an unsupported field")
        try:
            trip_shape = _optional_enum(payload_map.get("trip_shape"), _TRIP_SHAPES)
            date_mode = _optional_enum(payload_map.get("date_mode"), _DATE_MODES)
            baggage = _optional_enum(payload_map.get("baggage_preference"), _BAGGAGE)
            strategies = _string_tuple(payload_map.get("requested_strategies", ()))
            if any(strategy not in _STRATEGIES for strategy in strategies):
                raise ValueError
            wants_watch = payload_map.get("wants_watch", False)
            if type(wants_watch) is not bool:
                raise ValueError
            draft = CodexIntentDraft(
                origin_query=_optional_str(payload_map.get("origin_query")),
                destination_query=_optional_str(payload_map.get("destination_query")),
                departure_date=_optional_str(payload_map.get("departure_date")),
                return_date=_optional_str(payload_map.get("return_date")),
                date_hint=_optional_str(payload_map.get("date_hint")),
                trip_shape=trip_shape,
                date_mode=date_mode,
                adults=_optional_int(payload_map.get("adults"), minimum=1, maximum=9),
                children=_optional_int(payload_map.get("children"), minimum=0, maximum=9),
                infants=_optional_int(payload_map.get("infants"), minimum=0, maximum=9),
                currency=_optional_currency(payload_map.get("currency")),
                nearby_radius_km=_optional_int(
                    payload_map.get("nearby_radius_km"),
                    minimum=0,
                    maximum=500,
                ),
                requested_strategies=strategies,
                baggage_preference=baggage or "unspecified",
                wants_watch=wants_watch,
            )
        except ValueError:
            return _invalid("invalid_shape", "Codex output fields failed validation")
        return CodexIntentValidationResult(
            code="valid",
            message="Codex output validated",
            draft=draft,
        )


class CodexCliAgentAdapter:
    def __init__(
        self,
        *,
        enabled: bool,
        service_tier: str = "fast",
        timeout_seconds: int = 8,
        max_output_bytes: int = 16_384,
        validator: CodexIntentDraftValidator | None = None,
    ) -> None:
        self.enabled = enabled
        self.service_tier = service_tier if service_tier in {"fast", "flex"} else "fast"
        self.timeout_seconds = max(1, timeout_seconds)
        self.max_output_bytes = max(1_024, max_output_bytes)
        self._validator = validator or CodexIntentDraftValidator(
            max_output_bytes=self.max_output_bytes
        )

    @property
    def model(self) -> str:
        return "codex-cli"

    def build_command(
        self,
        *,
        schema_path: str,
        output_path: str | None = None,
        cwd: str | None = None,
    ) -> tuple[str, ...]:
        command = [
            "codex",
            "exec",
            "-c",
            f'service_tier="{self.service_tier}"',
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
        ]
        if cwd is not None:
            command.extend(("-C", cwd))
        command.extend(("--output-schema", schema_path))
        if output_path is not None:
            command.extend(("--output-last-message", output_path))
        command.append("-")
        return tuple(command)

    def extract_intent(self, message: str) -> IntentDraft | None:
        if not self.enabled or not message.strip():
            return None
        executable = shutil.which("codex")
        if executable is None:
            return None
        workspace = Path.cwd().resolve()
        with tempfile.TemporaryDirectory(prefix="flight-hunter-intent-") as raw_directory:
            directory = Path(raw_directory)
            schema_path = directory / "intent.schema.json"
            output_path = directory / "intent.output.json"
            schema_path.write_text(
                json.dumps(_response_schema(), separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            command = list(
                self.build_command(
                    schema_path=str(schema_path),
                    output_path=str(output_path),
                    cwd=str(directory),
                )
            )
            command[0] = executable
            try:
                completed = subprocess.run(
                    command,
                    input=_prompt(message).encode("utf-8"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=directory,
                    env=_minimal_environment(workspace),
                    timeout=self.timeout_seconds,
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if completed.returncode != 0 or not output_path.is_file():
                return None
            try:
                if output_path.stat().st_size > self.max_output_bytes:
                    return None
                raw_output = output_path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return None
        result = self._validator.validate_json(raw_output)
        if result.draft is None:
            return None
        return _intent_draft(result.draft)


def _intent_draft(draft: CodexIntentDraft) -> IntentDraft:
    return IntentDraft(
        origin_query=draft.origin_query,
        destination_query=draft.destination_query,
        departure_date=draft.departure_date,
        return_date=draft.return_date,
        date_hint=draft.date_hint,
        trip_shape=draft.trip_shape,
        date_mode=draft.date_mode,
        adults=draft.adults,
        children=draft.children,
        infants=draft.infants,
        currency=draft.currency,
        nearby_radius_km=draft.nearby_radius_km,
        requested_strategies=draft.requested_strategies,
        baggage_preference=draft.baggage_preference,
        wants_watch=draft.wants_watch,
    )


def _prompt(message: str) -> str:
    return (
        "Extract only the user's flight-search intent into the supplied JSON schema. "
        "Never provide prices, schedules, airline or airport facts, availability, provider IDs, "
        "booking data, URLs or instructions. Use null for unresolved scalar fields and empty "
        "arrays for unresolved lists. Today is "
        f"{date.today().isoformat()}. User request:\n{message}"
    )


def _minimal_environment(workspace: Path) -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name in _ENV_ALLOWLIST}
    raw_path = environment.get("PATH", "")
    safe_entries: list[str] = []
    for raw_entry in raw_path.split(os.pathsep):
        if not raw_entry:
            continue
        try:
            entry = Path(raw_entry).resolve()
        except OSError:
            continue
        if entry == workspace or entry.is_relative_to(workspace):
            continue
        safe_entries.append(raw_entry)
    environment["PATH"] = os.pathsep.join(safe_entries)
    return environment


def _response_schema() -> dict[str, object]:
    nullable_string: dict[str, object] = {"type": ["string", "null"]}
    properties: dict[str, object] = {
        "origin_query": nullable_string,
        "destination_query": nullable_string,
        "departure_date": nullable_string,
        "return_date": nullable_string,
        "date_hint": nullable_string,
        "trip_shape": {"type": ["string", "null"], "enum": [*_TRIP_SHAPES, None]},
        "date_mode": {"type": ["string", "null"], "enum": [*_DATE_MODES, None]},
        "adults": _nullable_integer_schema(1, 9),
        "children": _nullable_integer_schema(0, 9),
        "infants": _nullable_integer_schema(0, 9),
        "currency": nullable_string,
        "nearby_radius_km": _nullable_integer_schema(0, 500),
        "requested_strategies": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(_STRATEGIES)},
        },
        "baggage_preference": {"type": "string", "enum": sorted(_BAGGAGE)},
        "wants_watch": {"type": "boolean"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties),
        "additionalProperties": False,
    }


def _nullable_integer_schema(minimum: int, maximum: int) -> dict[str, object]:
    return {
        "type": ["integer", "null"],
        "minimum": minimum,
        "maximum": maximum,
    }


def _invalid(code: str, message: str) -> CodexIntentValidationResult:
    return CodexIntentValidationResult(code=code, message=message, draft=None)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError
    stripped = value.strip()
    return stripped or None


def _optional_enum(value: Any, allowed: set[str]) -> str | None:
    parsed = _optional_str(value)
    if parsed is not None and parsed not in allowed:
        raise ValueError
    return parsed


def _optional_int(value: Any, *, minimum: int, maximum: int) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError
    return value


def _optional_currency(value: Any) -> str | None:
    parsed = _optional_str(value)
    if parsed is None:
        return None
    normalized = parsed.upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError
    return normalized


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or not all(isinstance(item, str) for item in value):
        raise ValueError
    return tuple(item for item in value if item)
