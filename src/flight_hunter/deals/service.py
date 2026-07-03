from __future__ import annotations

from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError
from flight_hunter.deals.extractor import DealMarkdownExtractor
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResponse
from flight_hunter.deals.query_builder import DealQueryBuilder
from flight_hunter.deals.url_policy import DealUrlPolicy
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.domain.search_results import DealCandidate


class DealSearchPort(Protocol):
    def search(
        self, query: str, *, language: str = "ru", categories: str = "general"
    ) -> SearxngSearchResponse: ...


class DealMarkdownPort(Protocol):
    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown: ...


class DealDiscoveryService:
    def __init__(
        self,
        *,
        search_client: DealSearchPort,
        markdown_client: DealMarkdownPort,
        query_builder: DealQueryBuilder | None = None,
        extractor: DealMarkdownExtractor | None = None,
        url_policy: DealUrlPolicy | None = None,
    ) -> None:
        self._search_client = search_client
        self._markdown_client = markdown_client
        self._query_builder = query_builder or DealQueryBuilder()
        self._extractor = extractor or DealMarkdownExtractor()
        self._url_policy = url_policy or DealUrlPolicy()

    async def discover(self, intent: SearchIntent, *, limit: int = 5) -> tuple[DealCandidate, ...]:
        queries = self._query_builder.build_queries(intent)
        candidates: list[DealCandidate] = []
        seen_urls: set[str] = set()
        first_markdown_error: Crawl4AiClientError | None = None
        for query in queries:
            search_response = self._search_client.search(query)
            for result in search_response.results:
                safe_url = self._url_policy.validate_public_http_url(result.url)
                url_key = _canonical_url_key(safe_url)
                if url_key in seen_urls:
                    continue
                seen_urls.add(url_key)
                try:
                    page = await self._markdown_client.fetch_markdown(safe_url)
                except Crawl4AiClientError as exc:
                    if first_markdown_error is None:
                        first_markdown_error = exc
                    continue
                candidates.append(
                    self._extractor.extract(
                        search_result=result,
                        page=page,
                        intent=intent,
                    )
                )
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break
        if not candidates and first_markdown_error is not None:
            raise first_markdown_error
        return tuple(candidates)


def _canonical_url_key(url: str) -> str:
    parsed = urlsplit(url)
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _is_tracking_query_param(key)
        )
    )
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, query, ""))


def _is_tracking_query_param(key: str) -> bool:
    normalized = key.lower()
    return normalized.startswith("utm_") or normalized in {"gclid", "fbclid", "yclid"}
