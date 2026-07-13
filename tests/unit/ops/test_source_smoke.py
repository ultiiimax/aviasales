from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from flight_hunter.config import AppSettings
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResponse, SearxngSearchResult
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.ops.source_smoke import format_source_smoke_result, run_source_smoke

NOW = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_source_smoke_reports_disabled_searxng_without_calling_client() -> None:
    result = await run_source_smoke(
        settings=_settings(searxng_enabled=False),
        source="searxng",
        searxng_client_factory=lambda settings: FailingSearchClient(),
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "searxng_disabled"
    assert result.item_count == 0
    assert result.checked_at == NOW


@pytest.mark.anyio
async def test_source_smoke_checks_searxng_with_safe_summary() -> None:
    client = RecordingSearchClient()
    result = await run_source_smoke(
        settings=_settings(searxng_enabled=True),
        source="searxng",
        query="авиабилеты MOW IST акция",
        searxng_client_factory=lambda settings: client,
        clock=lambda: NOW,
    )

    rendered = format_source_smoke_result(result)

    assert result.ok is True
    assert result.code == "ok"
    assert result.item_count == 1
    assert result.received_at == NOW
    assert client.queries == ["авиабилеты MOW IST акция"]
    assert "token" not in rendered.lower()
    assert "raw" not in rendered.lower()


@pytest.mark.anyio
async def test_source_smoke_requires_crawl4ai_url_when_enabled() -> None:
    result = await run_source_smoke(
        settings=_settings(crawl4ai_enabled=True),
        source="crawl4ai",
        crawl4ai_client_factory=lambda settings: FailingMarkdownClient(),
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "crawl4ai_url_required"


@pytest.mark.anyio
async def test_source_smoke_checks_crawl4ai_markdown_without_exposing_content() -> None:
    result = await run_source_smoke(
        settings=_settings(crawl4ai_enabled=True),
        source="crawl4ai",
        url="https://example.com/deal",
        crawl4ai_client_factory=lambda settings: RecordingMarkdownClient(),
        clock=lambda: NOW,
    )
    rendered = format_source_smoke_result(result)

    assert result.ok is True
    assert result.code == "ok"
    assert result.item_count == 1
    assert result.received_at == NOW
    assert "secret fare text" not in rendered


@pytest.mark.anyio
async def test_source_smoke_reports_aviasales_search_missing_credentials() -> None:
    result = await run_source_smoke(
        settings=_settings(
            aviasales_search_enabled=True,
            aviasales_search_signature=None,
            aviasales_search_marker=None,
        ),
        source="aviasales_search",
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "aviasales_search_credentials_missing"
    assert result.source == "aviasales_search"


@pytest.mark.anyio
async def test_source_smoke_checks_aviasales_search_with_safe_summary() -> None:
    client = RecordingAviasalesClient()
    result = await run_source_smoke(
        settings=_settings(
            aviasales_search_enabled=True,
            aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
            aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        source="aviasales_search",
        aviasales_client_factory=lambda settings: client,
        clock=lambda: NOW,
    )
    rendered = format_source_smoke_result(result)

    assert result.ok is True
    assert result.code == "ok"
    assert result.item_count == 2
    assert result.source == "aviasales_search"
    assert client.terms == ["LED"]
    assert "123e4567-e89b-12d3-a456-426614174000" not in rendered
    assert "mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in rendered


@pytest.mark.anyio
async def test_source_smoke_runs_sanitized_exact_search() -> None:
    adapter = RecordingAviasalesAdapter()
    result = await run_source_smoke(
        settings=_settings(
            aviasales_search_enabled=True,
            aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
            aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        source="aviasales_search",
        exact_search=True,
        origin="MOW",
        destination="LED",
        departure_offset_days=30,
        aviasales_adapter_factory=lambda settings: adapter,
        clock=lambda: NOW,
    )
    rendered = format_source_smoke_result(result)

    assert result.ok is True
    assert result.item_count == 1
    assert result.source_ids == ("aviasales_search",)
    assert result.freshness_values == ("live",)
    assert adapter.intents[0].departure_date == "2026-07-29"
    assert adapter.intents[0].passengers == 1
    assert adapter.intents[0].currency == "RUB"
    assert "123400" not in rendered
    assert "provider_offer_id" not in rendered
    assert "booking" not in rendered.lower()


@pytest.mark.anyio
async def test_source_smoke_rejects_incomplete_exact_search_arguments() -> None:
    result = await run_source_smoke(
        settings=_settings(
            aviasales_search_enabled=True,
            aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
            aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        source="aviasales_search",
        exact_search=True,
        origin="MOW",
        destination=None,
        departure_offset_days=30,
        aviasales_adapter_factory=lambda settings: FailingAviasalesAdapter(),
        clock=lambda: NOW,
    )

    assert result.ok is False
    assert result.code == "smoke_arguments_invalid"


class RecordingSearchClient:
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
                    title="Sale",
                    url="https://example.com/deal",
                    content="cached hint",
                ),
            ),
        )


class RecordingMarkdownClient:
    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        return DealPageMarkdown(
            url=url,
            title=title,
            markdown="secret fare text",
            fetched_at=NOW,
        )


class FailingSearchClient:
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse:
        raise AssertionError("search client should not be called")


class FailingMarkdownClient:
    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown:
        raise AssertionError("markdown client should not be called")


class RecordingAviasalesClient:
    def __init__(self) -> None:
        self.terms: list[str] = []

    def suggest_places(self, term: str, *, max_results: int = 5) -> tuple[object, ...]:
        self.terms.append(term)
        return (object(), object())


class RecordingAviasalesAdapter:
    def __init__(self) -> None:
        self.intents: list[SearchIntent] = []

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WEB_USER_ACTION,
    ) -> tuple[FlightOffer, ...]:
        self.intents.append(intent)
        return (
            FlightOffer(
                provider_id="aviasales_search",
                provider_offer_id="secret-provider-offer-id",
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=None,
                total_price=Money(123_400, "RUB"),
                passengers=1,
                observed_at=NOW,
                freshness=Freshness.LIVE,
                requires_live_confirmation=False,
                baggage_summary=None,
                booking_action_ref="secret-booking-ref",
            ),
        )


class FailingAviasalesAdapter:
    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WEB_USER_ACTION,
    ) -> tuple[FlightOffer, ...]:
        raise AssertionError("exact-search adapter should not be called")


def _settings(**overrides) -> AppSettings:
    base = AppSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        aviasales_search_enabled=False,
        aviasales_search_signature=None,
        aviasales_search_marker=None,
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
    )
    return replace(base, **overrides)
