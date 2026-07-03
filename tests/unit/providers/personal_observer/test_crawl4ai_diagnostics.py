from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx2

from flight_hunter.browser.html_extractor import DomSnapshot
from flight_hunter.deals.crawl4ai_client import Crawl4AiMarkdownClient
from flight_hunter.providers.personal_observer.crawl4ai_diagnostics import (
    Crawl4AiBrowserMarkdownProvider,
)

NOW = datetime(2026, 6, 29, 22, 30, tzinfo=UTC)


def test_crawl4ai_browser_markdown_provider_fetches_snapshot_final_url() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"markdown": "MOW IST diagnostic 24 500 RUB"})

    provider = Crawl4AiBrowserMarkdownProvider(
        Crawl4AiMarkdownClient(
            enabled=True,
            mode="server",
            base_url="http://crawl4ai:11235",
            http_client=httpx2.Client(
                base_url="http://crawl4ai:11235",
                transport=httpx2.MockTransport(handler),
            ),
            clock=lambda: NOW,
        )
    )
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/result?redacted=true",
        title="Visible browser result",
        html="<html><body>No structured cards yet.</body></html>",
        captured_at=NOW,
    )

    markdown = provider(snapshot)

    assert markdown == "MOW IST diagnostic 24 500 RUB"
    assert captured_request is not None
    assert captured_request.url.path == "/md"
    assert json.loads(captured_request.read()) == {
        "url": "https://www.tutu.ru/avia/search/result?redacted=true",
        "f": "raw",
    }


def test_crawl4ai_browser_markdown_provider_does_not_fetch_fixture_snapshots() -> None:
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={"markdown": "should not be fetched"})

    provider = Crawl4AiBrowserMarkdownProvider(
        Crawl4AiMarkdownClient(
            enabled=True,
            mode="server",
            base_url="http://crawl4ai:11235",
            http_client=httpx2.Client(
                base_url="http://crawl4ai:11235",
                transport=httpx2.MockTransport(handler),
            ),
            clock=lambda: NOW,
        )
    )
    snapshot = DomSnapshot.from_html(
        source_id="tutu",
        final_url="https://www.tutu.ru/avia/search/result",
        title="fixture:result.html",
        html="<html><body>Local fixture only.</body></html>",
        captured_at=NOW,
    )

    assert provider(snapshot) is None
    assert calls == 0
