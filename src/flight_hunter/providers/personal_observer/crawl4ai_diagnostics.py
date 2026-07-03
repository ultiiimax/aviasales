from __future__ import annotations

from collections.abc import Callable

from flight_hunter.browser.html_extractor import DomSnapshot
from flight_hunter.config import AppSettings
from flight_hunter.deals.crawl4ai_client import Crawl4AiMarkdownClient


class Crawl4AiBrowserMarkdownProvider:
    def __init__(self, client: Crawl4AiMarkdownClient) -> None:
        self._client = client

    def __call__(self, snapshot: DomSnapshot) -> str | None:
        if snapshot.title is not None and snapshot.title.startswith("fixture:"):
            return None
        page = self._client.fetch_markdown_sync(
            snapshot.final_url,
            title=snapshot.title or "",
        )
        return page.markdown


def crawl4ai_browser_markdown_provider_from_settings(
    settings: AppSettings,
) -> Callable[[DomSnapshot], str | None] | None:
    if not settings.crawl4ai_enabled:
        return None
    return Crawl4AiBrowserMarkdownProvider(
        Crawl4AiMarkdownClient(
            enabled=settings.crawl4ai_enabled,
            mode=settings.crawl4ai_mode,
            base_url=settings.crawl4ai_base_url,
            api_token=settings.crawl4ai_api_token,
            timeout_seconds=settings.crawl4ai_timeout_seconds,
        )
    )
