from __future__ import annotations

import argparse
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

_GENERATED_VALUES = ("APP_SECRET_KEY", "AUTH_BOOTSTRAP_TOKEN")
_LOCAL_VALUES = {
    "AUTH_ALLOW_LEGACY_HEADERS": "false",
    "DATABASE_URL": "sqlite+aiosqlite:///./flight_hunter_dev.db",
    "AVIASALES_SEARCH_ENABLED": "false",
    "AVIASALES_SEARCH_SIGNATURE": "",
    "AVIASALES_SEARCH_MARKER": "",
    "TELEGRAM_ENABLED": "false",
    "TELEGRAM_BOT_TOKEN": "",
}


@dataclass(frozen=True, slots=True)
class InitLocalResult:
    ok: bool
    code: str
    path: Path

    def to_json(self) -> str:
        return json.dumps(
            {"ok": self.ok, "code": self.code, "path": str(self.path)},
            ensure_ascii=False,
        )


def initialize_local_env(
    *,
    template_path: Path,
    output_path: Path,
    force: bool = False,
) -> InitLocalResult:
    if not template_path.is_file():
        return InitLocalResult(False, "template_missing", output_path)
    if output_path.exists() and not force:
        return InitLocalResult(False, "env_exists", output_path)

    replacements = dict(_LOCAL_VALUES)
    replacements.update({name: secrets.token_urlsafe(48) for name in _GENERATED_VALUES})
    try:
        rendered = _replace_env_values(
            template_path.read_text(encoding="utf-8"),
            replacements,
        )
    except ValueError:
        return InitLocalResult(False, "template_invalid", output_path)

    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    output_path.chmod(0o600)
    return InitLocalResult(True, "ok", output_path)


def _replace_env_values(template: str, replacements: dict[str, str]) -> str:
    remaining = set(replacements)
    rendered: list[str] = []
    for line in template.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in replacements:
                line = f"{key}={replacements[key]}"
                remaining.discard(key)
        rendered.append(line)
    if remaining:
        raise ValueError("local env template is missing required keys")
    return "\n".join(rendered) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(prog="flight-hunter-init-local")
    parser.add_argument("--template", type=Path, default=Path(".env.example"))
    parser.add_argument("--output", type=Path, default=Path(".env"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = initialize_local_env(
        template_path=args.template,
        output_path=args.output,
        force=args.force,
    )
    print(result.to_json())
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
