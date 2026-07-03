from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResponse, SearxngSearchResult
from flight_hunter.deals.service import DealDiscoveryService
from flight_hunter.deals.url_policy import DealUrlPolicy
from flight_hunter.domain.offers import SearchIntent

NOW = datetime(2026, 6, 29, 20, 30, tzinfo=UTC)


class FakeSearchClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        self.queries.append(query)
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="SearXNG title MOW IST from 999 RUB",
                    url="https://example.com/deal",
                    content="Untrusted snippet says MOW IST 2026-09-10 from 999 RUB.",
                ),
            ),
        )


class FakeMarkdownClient:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.titles: list[str] = []

    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        self.urls.append(url)
        self.titles.append(title)
        return DealPageMarkdown(
            url=url,
            title=title,
            markdown="# Page markdown title\n\nMOW - IST on 2026-09-10 from 18 420 RUB.",
            fetched_at=NOW,
        )


class DuplicateSearchClient:
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="same deal canonical",
                    url="https://example.com/deal/?utm_source=feed#top",
                    content="Untrusted duplicate snippet.",
                ),
                SearxngSearchResult(
                    title="same deal duplicate",
                    url="https://example.com/deal",
                    content="Untrusted duplicate snippet.",
                ),
                SearxngSearchResult(
                    title="other deal",
                    url="https://example.com/other-deal?sort=cheap",
                    content="Untrusted other snippet.",
                ),
            ),
        )


class EmptyThenResultSearchClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        self.queries.append(query)
        if len(self.queries) == 1:
            return SearxngSearchResponse(query=query, received_at=NOW, results=())
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="second query deal",
                    url="https://example.com/second-query-deal",
                    content="Untrusted second snippet.",
                ),
            ),
        )


class TwoResultSearchClient:
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="first deal",
                    url="https://example.com/first-deal",
                    content="Untrusted first snippet.",
                ),
                SearxngSearchResult(
                    title="second deal",
                    url="https://example.com/second-deal",
                    content="Untrusted second snippet.",
                ),
            ),
        )


class PartiallyFailingMarkdownClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        self.urls.append(url)
        if url.endswith("/first-deal"):
            raise Crawl4AiClientError("crawl4ai_fetch_failed")
        return DealPageMarkdown(
            url=url,
            title=title,
            markdown="# Surviving deal\n\nMOW - IST on 2026-09-10 from 18 420 RUB.",
            fetched_at=NOW,
        )


class AlwaysFailingMarkdownClient:
    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        raise Crawl4AiClientError("crawl4ai_fetch_failed")


@pytest.mark.anyio
async def test_deal_discovery_service_builds_manual_candidates_without_live_prices() -> None:
    search_client = FakeSearchClient()
    markdown_client = FakeMarkdownClient()
    service = DealDiscoveryService(
        search_client=search_client,
        markdown_client=markdown_client,
    )

    candidates = await service.discover(_intent())

    assert search_client.queries
    assert markdown_client.titles == [""]
    assert len(candidates) == 1
    assert candidates[0].source_id == "deal_discovery"
    assert candidates[0].requires_manual_verification is True
    assert candidates[0].extracted_price is not None
    assert candidates[0].extracted_price.minor_units == 1_842_000
    assert "999" not in candidates[0].title
    assert "999" not in candidates[0].summary_ru


@pytest.mark.anyio
async def test_deal_discovery_service_uses_bounded_query_strategy_until_candidate_found() -> None:
    search_client = EmptyThenResultSearchClient()
    markdown_client = FakeMarkdownClient()
    service = DealDiscoveryService(
        search_client=search_client,
        markdown_client=markdown_client,
    )

    candidates = await service.discover(_intent(), limit=1)

    assert len(search_client.queries) == 2
    assert "MOW" in search_client.queries[0]
    assert "IST" in search_client.queries[0]
    assert "2026-09" in search_client.queries[0]
    assert search_client.queries[0] != search_client.queries[1]
    assert len(markdown_client.urls) == 1
    assert len(candidates) == 1


@pytest.mark.anyio
async def test_deal_discovery_service_deduplicates_tracking_urls_before_fetch() -> None:
    markdown_client = FakeMarkdownClient()
    service = DealDiscoveryService(
        search_client=DuplicateSearchClient(),
        markdown_client=markdown_client,
    )

    candidates = await service.discover(_intent(), limit=2)

    assert len(candidates) == 2
    assert markdown_client.urls == [
        "https://example.com/deal/?utm_source=feed#top",
        "https://example.com/other-deal?sort=cheap",
    ]


@pytest.mark.anyio
async def test_deal_discovery_service_keeps_partial_success_when_page_fetch_fails() -> None:
    markdown_client = PartiallyFailingMarkdownClient()
    service = DealDiscoveryService(
        search_client=TwoResultSearchClient(),
        markdown_client=markdown_client,
    )

    candidates = await service.discover(_intent(), limit=2)

    assert markdown_client.urls == [
        "https://example.com/first-deal",
        "https://example.com/second-deal",
    ]
    assert len(candidates) == 1
    assert candidates[0].url == "https://example.com/second-deal"


@pytest.mark.anyio
async def test_deal_discovery_service_reraises_when_all_page_fetches_fail() -> None:
    service = DealDiscoveryService(
        search_client=TwoResultSearchClient(),
        markdown_client=AlwaysFailingMarkdownClient(),
    )

    with pytest.raises(Crawl4AiClientError, match="crawl4ai_fetch_failed"):
        await service.discover(_intent(), limit=2)


class UnsafeSearchClient:
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="internal metadata",
                    url="http://127.0.0.1/admin",
                    content="not public",
                ),
            ),
        )


class OffAllowlistSearchClient:
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        return SearxngSearchResponse(
            query=query,
            received_at=NOW,
            results=(
                SearxngSearchResult(
                    title="off allowlist deal",
                    url="https://unexpected.example/deal",
                    content="not allowed",
                ),
            ),
        )


@pytest.mark.anyio
async def test_deal_discovery_service_rejects_unsafe_url_before_markdown_fetch() -> None:
    markdown_client = FakeMarkdownClient()
    service = DealDiscoveryService(
        search_client=UnsafeSearchClient(),
        markdown_client=markdown_client,
    )

    with pytest.raises(ValueError, match="deal_url_blocked_ip"):
        await service.discover(_intent())

    assert markdown_client.urls == []


@pytest.mark.anyio
async def test_deal_discovery_service_enforces_host_allowlist_before_markdown_fetch() -> None:
    markdown_client = FakeMarkdownClient()
    service = DealDiscoveryService(
        search_client=OffAllowlistSearchClient(),
        markdown_client=markdown_client,
        url_policy=DealUrlPolicy(allowed_hosts=("approved.example",)),
    )

    with pytest.raises(ValueError, match="deal_url_host_not_allowed"):
        await service.discover(_intent())

    assert markdown_client.urls == []


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )
