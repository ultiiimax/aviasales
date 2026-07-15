from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2

from flight_hunter.deals.models import DealPageMarkdown
from flight_hunter.deals.url_policy import DealUrlPolicy, DealUrlPolicyError


class Crawl4AiClientError(RuntimeError):
    """Raised when Crawl4AI markdown extraction cannot produce a safe page snapshot."""


class Crawl4AiMarkdownClient:
    def __init__(
        self,
        *,
        enabled: bool,
        mode: str = "library",
        base_url: str = "http://crawl4ai:11235",
        api_token: str | None = None,
        http_client: httpx2.Client | None = None,
        timeout_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
        url_policy: DealUrlPolicy | None = None,
        max_markdown_chars: int = 200_000,
    ) -> None:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"library", "server"}:
            raise ValueError("crawl4ai mode must be library or server")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("crawl4ai base_url must be http(s)")
        self._enabled = enabled
        self._mode = normalized_mode
        self._api_token = api_token
        self._client = http_client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._url_policy = url_policy or DealUrlPolicy()
        self._max_markdown_chars = max_markdown_chars

    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        safe_url = self._validate_url(url)
        if not self._enabled:
            raise Crawl4AiClientError("crawl4ai_disabled")
        if self._mode == "server":
            return self._fetch_markdown_via_server(safe_url, title=title)
        return await self._fetch_markdown_via_library(safe_url, title=title)

    def fetch_markdown_sync(self, url: str, *, title: str = "") -> DealPageMarkdown:
        safe_url = self._validate_url(url)
        if not self._enabled:
            raise Crawl4AiClientError("crawl4ai_disabled")
        if self._mode == "server":
            return self._fetch_markdown_via_server(safe_url, title=title)
        return _run_async_from_sync(lambda: self._fetch_markdown_via_library(safe_url, title=title))

    async def _fetch_markdown_via_library(
        self,
        url: str,
        *,
        title: str = "",
    ) -> DealPageMarkdown:
        try:
            crawler_module = importlib.import_module("crawl4ai")
            async_web_crawler = crawler_module.AsyncWebCrawler
        except (AttributeError, ImportError) as exc:
            raise Crawl4AiClientError("crawl4ai_unavailable") from exc

        try:
            async with async_web_crawler() as crawler:
                result = await crawler.arun(url=url)
        except Exception as exc:  # pragma: no cover - external browser/runtime boundary
            raise Crawl4AiClientError("crawl4ai_fetch_failed") from exc

        markdown = _markdown_from_result(result)
        if not markdown:
            raise Crawl4AiClientError("crawl4ai_empty_markdown")
        if len(markdown) > self._max_markdown_chars:
            raise Crawl4AiClientError("crawl4ai_markdown_too_large")
        return DealPageMarkdown(
            url=url,
            title=title,
            markdown=markdown,
            fetched_at=self._clock(),
        )

    def _fetch_markdown_via_server(self, url: str, *, title: str = "") -> DealPageMarkdown:
        headers = (
            {"Authorization": f"Bearer {self._api_token}"}
            if self._api_token is not None and self._api_token.strip()
            else None
        )
        try:
            response = self._client.post(
                "/md",
                json={"url": url, "f": "raw"},
                headers=headers,
            )
        except httpx2.HTTPError as exc:
            raise Crawl4AiClientError("crawl4ai_server_unavailable") from exc
        if response.status_code in {401, 403}:
            raise Crawl4AiClientError("crawl4ai_auth_failed")
        if response.status_code == 429:
            raise Crawl4AiClientError("crawl4ai_rate_limited")
        if response.status_code >= 400:
            raise Crawl4AiClientError(f"crawl4ai_http_{response.status_code}")

        markdown = _markdown_from_response(response)
        if not markdown:
            raise Crawl4AiClientError("crawl4ai_empty_markdown")
        if len(markdown) > self._max_markdown_chars:
            raise Crawl4AiClientError("crawl4ai_markdown_too_large")
        return DealPageMarkdown(
            url=url,
            title=title,
            markdown=markdown,
            fetched_at=self._clock(),
        )

    def read_fixture(self, path: Path, *, url: str, title: str = "") -> DealPageMarkdown:
        safe_url = self._validate_url(url)
        markdown = path.read_text(encoding="utf-8")
        if len(markdown) > self._max_markdown_chars:
            raise Crawl4AiClientError("crawl4ai_markdown_too_large")
        return DealPageMarkdown(
            url=safe_url,
            title=title,
            markdown=markdown,
            fetched_at=self._clock(),
        )

    def _validate_url(self, url: str) -> str:
        try:
            return self._url_policy.validate_public_http_url(url)
        except DealUrlPolicyError as exc:
            raise Crawl4AiClientError(str(exc)) from exc


def _markdown_from_result(result: Any) -> str:
    markdown = getattr(result, "markdown", None)
    if isinstance(markdown, str):
        return markdown
    raw_markdown = getattr(markdown, "raw_markdown", None)
    if isinstance(raw_markdown, str):
        return raw_markdown
    fit_markdown = getattr(markdown, "fit_markdown", None)
    if isinstance(fit_markdown, str):
        return fit_markdown
    return ""


def _run_async_from_sync(
    factory: Callable[[], Coroutine[Any, Any, DealPageMarkdown]],
) -> DealPageMarkdown:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    raise Crawl4AiClientError("crawl4ai_sync_event_loop_running")


def _markdown_from_response(response: httpx2.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text.strip()
    return _markdown_from_payload(payload)


def _markdown_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, list):
        return _markdown_from_payload(payload[0]) if payload else ""
    if not isinstance(payload, dict):
        return ""
    for key in ("markdown", "raw_markdown", "fit_markdown", "content"):
        markdown = payload.get(key)
        if isinstance(markdown, str) and markdown.strip():
            return markdown.strip()
        if isinstance(markdown, dict):
            nested = _markdown_from_payload(markdown)
            if nested:
                return nested
    result = payload.get("result") or payload.get("data")
    if result is not None:
        return _markdown_from_payload(result)
    results = payload.get("results")
    if isinstance(results, list) and results:
        return _markdown_from_payload(results[0])
    return ""
