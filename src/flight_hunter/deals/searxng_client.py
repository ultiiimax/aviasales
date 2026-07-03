from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx2

from flight_hunter.deals.models import SearxngSearchResponse, SearxngSearchResult
from flight_hunter.deals.url_policy import DealUrlPolicy, DealUrlPolicyError


class SearxngClientError(RuntimeError):
    """Raised when SearXNG discovery does not return a safe JSON result set."""


class SearxngClient:
    def __init__(
        self,
        *,
        base_url: str,
        http_client: httpx2.Client | None = None,
        timeout_seconds: int = 15,
        clock: Callable[[], datetime] | None = None,
        url_policy: DealUrlPolicy | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be http(s)")
        self._client = http_client or httpx2.Client(base_url=base_url, timeout=timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._url_policy = url_policy or DealUrlPolicy()

    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        try:
            response = self._client.get(
                "/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": language,
                    "categories": categories,
                },
            )
        except httpx2.TimeoutException as exc:
            raise SearxngClientError("searxng_timeout") from exc
        except httpx2.HTTPError as exc:
            raise SearxngClientError("searxng_unavailable") from exc
        if response.status_code == 429:
            raise SearxngClientError("searxng_rate_limited")
        if response.status_code >= 400:
            raise SearxngClientError(f"searxng_http_{response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SearxngClientError("searxng_invalid_json") from exc
        if not isinstance(payload, dict):
            raise SearxngClientError("searxng_invalid_payload")
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise SearxngClientError("searxng_invalid_results")
        return SearxngSearchResponse(
            query=query,
            received_at=self._clock(),
            results=tuple(_parse_result(item, url_policy=self._url_policy) for item in raw_results),
        )


def _parse_result(raw: Any, *, url_policy: DealUrlPolicy) -> SearxngSearchResult:
    if not isinstance(raw, dict):
        raise SearxngClientError("searxng_invalid_result")
    title = _required_text(raw.get("title"), "title")
    url = _required_text(raw.get("url"), "url")
    content = _optional_text(raw.get("content")) or ""
    try:
        safe_url = url_policy.validate_public_http_url(url)
    except DealUrlPolicyError as exc:
        raise SearxngClientError("searxng_invalid_url") from exc
    return SearxngSearchResult(
        title=title,
        url=safe_url,
        content=content,
        engine=_optional_text(raw.get("engine")),
        published_date=_optional_text(raw.get("publishedDate")),
    )


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SearxngClientError(f"searxng_missing_{field_name}")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
