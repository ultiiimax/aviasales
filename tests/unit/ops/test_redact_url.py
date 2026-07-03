from __future__ import annotations

import json
import sys

from flight_hunter.ops.redact_url import main, redact_url


def test_redact_url_removes_credentials_sensitive_query_values_and_fragment() -> None:
    result = redact_url(
        "https://user:pass@example.com/deal?session=secret&from=MOW&Access_Token=abc#token=abc"
    )

    assert result.ok is True
    assert (
        result.redacted_url
        == "https://example.com/deal?session=%3Credacted%3E&from=MOW&Access_Token=%3Credacted%3E"
    )
    assert result.redacted_keys == ("session", "Access_Token")
    assert result.credentials_redacted is True
    assert result.fragment_redacted is True


def test_redact_url_cli_prints_only_redacted_url(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "flight-hunter-redact-url",
            "--url",
            "https://example.com/path?api_key=secret&ok=1",
        ],
    )

    exit_code = main()

    stdout = capsys.readouterr().out
    summary = json.loads(stdout)
    assert exit_code == 0
    assert summary["ok"] is True
    assert summary["redacted_url"] == "https://example.com/path?api_key=%3Credacted%3E&ok=1"
    assert "secret" not in stdout
