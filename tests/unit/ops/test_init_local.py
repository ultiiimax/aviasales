import json
from pathlib import Path

from flight_hunter.ops.init_local import initialize_local_env, main


def test_initializer_generates_safe_local_secrets(tmp_path: Path) -> None:
    output_path = tmp_path / ".env"

    result = initialize_local_env(
        template_path=Path(".env.example"),
        output_path=output_path,
    )

    values = _parse_env(output_path)
    assert result.ok
    assert result.code == "ok"
    assert result.path == output_path
    assert len(values["APP_SECRET_KEY"]) >= 43
    assert len(values["AUTH_BOOTSTRAP_TOKEN"]) >= 43
    assert values["AUTH_ALLOW_LEGACY_HEADERS"] == "false"
    assert values["DATABASE_URL"] == "sqlite+aiosqlite:///./flight_hunter_dev.db"
    assert values["AVIASALES_SEARCH_SIGNATURE"] == ""
    assert values["AVIASALES_SEARCH_MARKER"] == ""
    assert values["TELEGRAM_BOT_TOKEN"] == ""


def test_initializer_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    output_path = tmp_path / ".env"
    output_path.write_text("existing=true\n", encoding="utf-8")

    result = initialize_local_env(
        template_path=Path(".env.example"),
        output_path=output_path,
    )

    assert not result.ok
    assert result.code == "env_exists"
    assert output_path.read_text(encoding="utf-8") == "existing=true\n"


def test_initializer_force_replaces_existing_file(tmp_path: Path) -> None:
    output_path = tmp_path / ".env"
    output_path.write_text("existing=true\n", encoding="utf-8")

    result = initialize_local_env(
        template_path=Path(".env.example"),
        output_path=output_path,
        force=True,
    )

    assert result.ok
    assert "existing=true" not in output_path.read_text(encoding="utf-8")


def test_init_cli_prints_metadata_without_secret_values(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / ".env"
    monkeypatch.setattr(
        "sys.argv",
        ["flight-hunter-init-local", "--output", str(output_path)],
    )

    exit_code = main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {"ok": True, "code": "ok", "path": str(output_path)}
    assert "APP_SECRET_KEY" not in payload
    assert "AUTH_BOOTSTRAP_TOKEN" not in payload


def _parse_env(path: Path) -> dict[str, str]:
    return {
        key: value
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
        for key, value in (line.split("=", 1),)
    }
