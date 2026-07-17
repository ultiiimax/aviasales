from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

ApiKitImportCode = Literal["ok", "api_kit_invalid", "api_kit_env_write_failed"]

_CLIENT_NAMES = frozenset({"X_SIGNATURE", "MARKER", "ANDROID_ID"})
_MARKER_PATTERN = re.compile(r"mobile_app\.[0-9a-f]{32}\Z")
_ENV_REPLACEMENTS = (
    "AVIASALES_SEARCH_ENABLED",
    "AVIASALES_SEARCH_SIGNATURE",
    "AVIASALES_SEARCH_MARKER",
)


@dataclass(frozen=True, slots=True)
class ApiKitImportResult:
    configured: bool
    code: ApiKitImportCode


class _ApiKitInvalid(ValueError):
    pass


class _EnvWriteFailed(OSError):
    pass


def import_aviasales_api_kit(
    *,
    api_kit_root: Path,
    env_path: Path,
) -> ApiKitImportResult:
    try:
        keys_path, client_path = _resolved_source_paths(api_kit_root)
        signature, marker = _read_credentials(keys_path, client_path)
    except (OSError, UnicodeError, json.JSONDecodeError, SyntaxError, _ApiKitInvalid):
        return ApiKitImportResult(False, "api_kit_invalid")

    try:
        _atomic_update_env(
            env_path,
            {
                "AVIASALES_SEARCH_ENABLED": "true",
                "AVIASALES_SEARCH_SIGNATURE": signature,
                "AVIASALES_SEARCH_MARKER": marker,
            },
        )
    except (OSError, UnicodeError, _EnvWriteFailed):
        return ApiKitImportResult(False, "api_kit_env_write_failed")
    return ApiKitImportResult(True, "ok")


def _resolved_source_paths(api_kit_root: Path) -> tuple[Path, Path]:
    root = api_kit_root.resolve(strict=True)
    if not root.is_dir():
        raise _ApiKitInvalid
    resolved: list[Path] = []
    for relative in (Path("aviasales/keys.json"), Path("aviasales/client.py")):
        candidate = (root / relative).resolve(strict=True)
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise _ApiKitInvalid
        resolved.append(candidate)
    return resolved[0], resolved[1]


def _read_credentials(keys_path: Path, client_path: Path) -> tuple[str, str]:
    raw_json = json.loads(keys_path.read_text(encoding="utf-8"))
    if not isinstance(raw_json, dict):
        raise _ApiKitInvalid
    signature = _required_string(raw_json.get("x_signature"))
    json_marker = _optional_string(raw_json.get("marker"))
    constants = _literal_client_constants(client_path.read_text(encoding="utf-8"))

    client_signature = constants.get("X_SIGNATURE")
    if client_signature is not None and client_signature != signature:
        raise _ApiKitInvalid
    marker = json_marker or constants.get("MARKER")
    if marker is None:
        android_id = constants.get("ANDROID_ID")
        if android_id is None:
            raise _ApiKitInvalid
        digest = hashlib.md5(android_id.encode("utf-8"), usedforsecurity=False).hexdigest()
        marker = f"mobile_app.{digest}"

    try:
        UUID(signature)
    except ValueError as exc:
        raise _ApiKitInvalid from exc
    if _MARKER_PATTERN.fullmatch(marker) is None:
        raise _ApiKitInvalid
    return signature, marker


def _literal_client_constants(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    result: dict[str, str] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                name = target.id
                value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name not in _CLIENT_NAMES:
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            if name == "MARKER":
                # Real kits commonly derive MARKER from the literal ANDROID_ID.
                # Do not execute or interpret that expression; the importer derives
                # the same bounded value itself below.
                continue
            raise _ApiKitInvalid
        parsed = value.value.strip()
        if not parsed:
            raise _ApiKitInvalid
        existing = result.get(name)
        if existing is not None and existing != parsed:
            raise _ApiKitInvalid
        result[name] = parsed
    return result


def _required_string(value: object) -> str:
    parsed = _optional_string(value)
    if parsed is None:
        raise _ApiKitInvalid
    return parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _ApiKitInvalid
    parsed = value.strip()
    if not parsed:
        raise _ApiKitInvalid
    return parsed


def _atomic_update_env(env_path: Path, replacements: dict[str, str]) -> None:
    if set(replacements) != set(_ENV_REPLACEMENTS):
        raise _EnvWriteFailed
    try:
        original_bytes = env_path.read_bytes() if env_path.exists() else b""
        original = original_bytes.decode("utf-8")
        newline = "\r\n" if b"\r\n" in original_bytes else "\n"
        keep_final_newline = not original_bytes or original.endswith(("\n", "\r"))
        rendered = _replace_env_values(
            original,
            replacements,
            newline=newline,
            final_newline=keep_final_newline,
        )
        parent = env_path.parent.resolve(strict=True)
        if not parent.is_dir():
            raise _EnvWriteFailed
        existing_mode = env_path.stat().st_mode if env_path.exists() else None
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                prefix=f".{env_path.name}.",
                suffix=".tmp",
                dir=parent,
                delete=False,
            ) as temporary:
                temporary.write(rendered)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            if existing_mode is not None:
                temporary_path.chmod(existing_mode)
            os.replace(temporary_path, env_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    except (OSError, UnicodeError) as exc:
        raise _EnvWriteFailed from exc


def _replace_env_values(
    original: str,
    replacements: dict[str, str],
    *,
    newline: str,
    final_newline: bool,
) -> str:
    remaining = set(replacements)
    rendered_lines: list[str] = []
    for line in original.splitlines():
        candidate = line.lstrip()
        if candidate and not candidate.startswith("#") and "=" in candidate:
            key = candidate.split("=", 1)[0].strip()
            if key in replacements:
                line = f"{key}={replacements[key]}"
                remaining.discard(key)
        rendered_lines.append(line)
    for key in _ENV_REPLACEMENTS:
        if key in remaining:
            rendered_lines.append(f"{key}={replacements[key]}")
    rendered = newline.join(rendered_lines)
    if final_newline:
        rendered += newline
    return rendered


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flight-hunter-import-api-kit")
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--env", default=Path(".env"), type=Path)
    args = parser.parse_args(argv)
    result = import_aviasales_api_kit(api_kit_root=args.path, env_path=args.env)
    if result.configured:
        print('{"configured":true,"provider":"aviasales_search"}')
        return 0
    print(result.code, file=sys.stderr)
    return 3 if result.code == "api_kit_env_write_failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
