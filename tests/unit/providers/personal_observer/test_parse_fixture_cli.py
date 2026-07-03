from __future__ import annotations

import json
import sys
from pathlib import Path

from flight_hunter.providers.personal_observer.parse_fixture_cli import main

SOURCE_SPECIFIC_FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
MARKDOWN_HINT_FIXTURE = Path("tests/fixtures/crawl4ai/browser_observer_markdown_hint.md")


def test_parse_fixture_cli_outputs_sanitized_offer_summary(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("SCRAPLING_ENABLED", "false")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "flight-hunter-parse-fixture",
            str(SOURCE_SPECIFIC_FIXTURE),
            "--source",
            "tutu",
            "--origin",
            "MOW",
            "--destination",
            "IST",
            "--depart",
            "2026-09-10",
            "--return-date",
            "2026-09-20",
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["source_id"] == "tutu"
    assert payload["confidence"] == "medium"
    assert payload["offers"][0]["provider_offer_id"] == "tutu-realistic-1"
    assert payload["offers"][0]["amount_minor"] == 1_842_000
    assert "tutu-flight-card" not in output
    assert "<html" not in output.lower()


def test_parse_fixture_cli_accepts_crawl4ai_markdown_fixture_without_printing_it(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("SCRAPLING_ENABLED", "false")
    monkeypatch.setenv("CRAWL4AI_ENABLED", "true")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "flight-hunter-parse-fixture",
            str(SOURCE_SPECIFIC_FIXTURE),
            "--source",
            "tutu",
            "--origin",
            "MOW",
            "--destination",
            "IST",
            "--depart",
            "2026-09-10",
            "--return-date",
            "2026-09-20",
            "--crawl4ai-markdown-fixture",
            str(MARKDOWN_HINT_FIXTURE),
        ],
    )

    main()

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["offers"][0]["amount_minor"] == 1_842_000
    assert "24 500" not in output
    assert "Manual diagnostic markdown" not in output
