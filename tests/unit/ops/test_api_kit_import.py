from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from flight_hunter.ops.api_kit_import import import_aviasales_api_kit, main

_SIGNATURE = "12345678-1234-4234-9234-123456789abc"
_OTHER_SIGNATURE = "aaaaaaaa-aaaa-4aaa-9aaa-aaaaaaaaaaaa"
_ANDROID_ID = "local-test-device"


def _write_kit(
    root: Path,
    *,
    json_signature: str = _SIGNATURE,
    client_signature: str = _SIGNATURE,
    marker: str | None = "mobile_app.0123456789abcdef0123456789abcdef",
) -> None:
    aviasales = root / "aviasales"
    aviasales.mkdir(parents=True)
    payload: dict[str, str] = {"x_signature": json_signature}
    if marker is not None:
        payload["marker"] = marker
    (aviasales / "keys.json").write_text(json.dumps(payload), encoding="utf-8")
    marker_line = f'MARKER = "{marker}"\n' if marker is not None else ""
    (aviasales / "client.py").write_text(
        f'X_SIGNATURE = "{client_signature}"\n'
        f'ANDROID_ID = "{_ANDROID_ID}"\n'
        f"{marker_line}",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("client_signature", "expected_ok"),
    [
        (_SIGNATURE, True),
        (_OTHER_SIGNATURE, False),
    ],
)
def test_import_is_atomic_and_rejects_conflicting_source(
    tmp_path: Path,
    client_signature: str,
    expected_ok: bool,
) -> None:
    root = tmp_path / "kit"
    _write_kit(root, client_signature=client_signature)
    env_path = tmp_path / ".env"
    original = "APP_NAME=Flight Hunter\r\nAVIASALES_SEARCH_ENABLED=false\r\nKEEP=1\r\n"
    env_path.write_text(original, encoding="utf-8", newline="")

    result = import_aviasales_api_kit(api_kit_root=root, env_path=env_path)

    assert result.configured is expected_ok
    rendered = env_path.read_bytes().decode("utf-8")
    if expected_ok:
        assert "APP_NAME=Flight Hunter\r\n" in rendered
        assert "KEEP=1\r\n" in rendered
        assert "AVIASALES_SEARCH_ENABLED=true\r\n" in rendered
        assert f"AVIASALES_SEARCH_SIGNATURE={_SIGNATURE}\r\n" in rendered
        assert (
            "AVIASALES_SEARCH_MARKER=mobile_app.0123456789abcdef0123456789abcdef\r\n"
            in rendered
        )
    else:
        assert result.code == "api_kit_invalid"
        assert rendered == original


def test_import_derives_marker_from_utf8_android_id(tmp_path: Path) -> None:
    root = tmp_path / "kit"
    aviasales = root / "aviasales"
    aviasales.mkdir(parents=True)
    (aviasales / "keys.json").write_text(
        json.dumps({"x_signature": _SIGNATURE}), encoding="utf-8"
    )
    (aviasales / "client.py").write_text(
        f'X_SIGNATURE = "{_SIGNATURE}"\nANDROID_ID = "тест-device"\n',
        encoding="utf-8",
    )
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\n", encoding="utf-8")

    result = import_aviasales_api_kit(api_kit_root=root, env_path=env_path)

    assert result.configured
    rendered = env_path.read_text(encoding="utf-8")
    assert "AVIASALES_SEARCH_MARKER=mobile_app.78a1ba39020cc052b3e2ffca15c6e442\n" in rendered


def test_cli_redacts_values_and_write_failure_leaves_env_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root = tmp_path / "kit-secret-name"
    _write_kit(root)
    env_path = tmp_path / ".env"
    original = "KEEP=unchanged\n"
    env_path.write_text(original, encoding="utf-8")

    def fail_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        del source, target
        raise OSError("private filesystem detail")

    monkeypatch.setattr("flight_hunter.ops.api_kit_import.os.replace", fail_replace)

    exit_code = main(["--path", str(root), "--env", str(env_path)])
    captured = capsys.readouterr()

    assert exit_code == 3
    assert captured.out == ""
    assert captured.err == "api_kit_env_write_failed\n"
    assert _SIGNATURE not in captured.err
    assert str(root) not in captured.err
    assert env_path.read_text(encoding="utf-8") == original


def test_import_rejects_resolved_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "kit"
    outside = tmp_path / "outside"
    _write_kit(outside)
    root.mkdir()
    try:
        (root / "aviasales").symlink_to(outside / "aviasales", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this Windows host")
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\n", encoding="utf-8")

    result = import_aviasales_api_kit(api_kit_root=root, env_path=env_path)

    assert result.code == "api_kit_invalid"
    assert env_path.read_text(encoding="utf-8") == "KEEP=1\n"
