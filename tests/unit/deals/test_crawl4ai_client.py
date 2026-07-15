from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest

from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError, Crawl4AiMarkdownClient

NOW = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_crawl4ai_client_validates_url_before_disabled_check() -> None:
    client = Crawl4AiMarkdownClient(enabled=False, clock=lambda: NOW)

    with pytest.raises(Crawl4AiClientError, match="deal_url_blocked_ip"):
        await client.fetch_markdown("http://127.0.0.1/admin", title="internal")


@pytest.mark.anyio
async def test_crawl4ai_library_mode_loads_optional_dependency_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported_modules: list[str] = []

    class FakeCrawler:
        async def __aenter__(self) -> FakeCrawler:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def arun(self, *, url: str) -> SimpleNamespace:
            assert url == "https://example.com/deal"
            return SimpleNamespace(markdown="# Runtime-loaded markdown")

    def import_module(name: str) -> SimpleNamespace:
        imported_modules.append(name)
        return SimpleNamespace(AsyncWebCrawler=FakeCrawler)

    monkeypatch.setattr(importlib, "import_module", import_module)
    client = Crawl4AiMarkdownClient(enabled=True, mode="library", clock=lambda: NOW)

    page = await client.fetch_markdown("https://example.com/deal", title="deal")

    assert imported_modules == ["crawl4ai"]
    assert page.markdown == "# Runtime-loaded markdown"
    assert page.fetched_at == NOW


@pytest.mark.anyio
async def test_crawl4ai_library_mode_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def import_missing_module(name: str) -> None:
        assert name == "crawl4ai"
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", import_missing_module)
    client = Crawl4AiMarkdownClient(enabled=True, mode="library", clock=lambda: NOW)

    with pytest.raises(Crawl4AiClientError, match=r"^crawl4ai_unavailable$"):
        await client.fetch_markdown("https://example.com/deal", title="deal")


def test_crawl4ai_fixture_reader_enforces_markdown_size_cap(tmp_path: Path) -> None:
    fixture = tmp_path / "large.md"
    fixture.write_text("x" * 20, encoding="utf-8")
    client = Crawl4AiMarkdownClient(
        enabled=False,
        clock=lambda: NOW,
        max_markdown_chars=10,
    )

    with pytest.raises(Crawl4AiClientError, match="crawl4ai_markdown_too_large"):
        client.read_fixture(fixture, url="https://example.com/deal", title="large")


def test_crawl4ai_fixture_reader_rejects_unsafe_fixture_url(tmp_path: Path) -> None:
    fixture = tmp_path / "deal.md"
    fixture.write_text("# deal", encoding="utf-8")
    client = Crawl4AiMarkdownClient(enabled=False, clock=lambda: NOW)

    with pytest.raises(Crawl4AiClientError, match="deal_url_blocked_host"):
        client.read_fixture(fixture, url="http://localhost/deal", title="internal")


@pytest.mark.anyio
async def test_crawl4ai_server_mode_posts_safe_md_request_with_token() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"markdown": "# Deal\n\nSecret fare redacted"})

    client = Crawl4AiMarkdownClient(
        enabled=True,
        mode="server",
        base_url="http://crawl4ai:11235",
        api_token="server-secret",
        http_client=httpx2.Client(
            base_url="http://crawl4ai:11235",
            transport=httpx2.MockTransport(handler),
        ),
        clock=lambda: NOW,
    )

    page = await client.fetch_markdown("https://example.com/deal", title="deal")

    assert page.url == "https://example.com/deal"
    assert page.title == "deal"
    assert page.markdown == "# Deal\n\nSecret fare redacted"
    assert page.fetched_at == NOW
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert captured_request.url.path == "/md"
    assert captured_request.headers["authorization"] == "Bearer server-secret"
    assert json.loads(captured_request.read()) == {
        "url": "https://example.com/deal",
        "f": "raw",
    }


def test_crawl4ai_server_mode_sync_fetch_posts_safe_md_request() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"markdown": "# Browser diagnostic"})

    client = Crawl4AiMarkdownClient(
        enabled=True,
        mode="server",
        base_url="http://crawl4ai:11235",
        http_client=httpx2.Client(
            base_url="http://crawl4ai:11235",
            transport=httpx2.MockTransport(handler),
        ),
        clock=lambda: NOW,
    )

    page = client.fetch_markdown_sync("https://example.com/result", title="browser result")

    assert page.url == "https://example.com/result"
    assert page.title == "browser result"
    assert page.markdown == "# Browser diagnostic"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert captured_request.url.path == "/md"
    assert json.loads(captured_request.read()) == {
        "url": "https://example.com/result",
        "f": "raw",
    }


@pytest.mark.anyio
async def test_crawl4ai_server_mode_rejects_http_auth_errors() -> None:
    client = Crawl4AiMarkdownClient(
        enabled=True,
        mode="server",
        base_url="http://crawl4ai:11235",
        http_client=httpx2.Client(
            base_url="http://crawl4ai:11235",
            transport=httpx2.MockTransport(lambda request: httpx2.Response(401)),
        ),
        clock=lambda: NOW,
    )

    with pytest.raises(Crawl4AiClientError, match="crawl4ai_auth_failed"):
        await client.fetch_markdown("https://example.com/deal", title="deal")


@pytest.mark.anyio
async def test_crawl4ai_server_mode_accepts_plain_text_markdown_response() -> None:
    client = Crawl4AiMarkdownClient(
        enabled=True,
        mode="server",
        base_url="http://crawl4ai:11235",
        http_client=httpx2.Client(
            base_url="http://crawl4ai:11235",
            transport=httpx2.MockTransport(lambda request: httpx2.Response(200, text="# Markdown")),
        ),
        clock=lambda: NOW,
    )

    page = await client.fetch_markdown("https://example.com/deal", title="deal")

    assert page.markdown == "# Markdown"
