from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.application.provider_registry import ProviderRegistry
from flight_hunter.application.search_service import (
    DemoSearchService,
    SearchRequest,
    with_browser_observed_offers_and_deal_candidates,
)
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness
from flight_hunter.domain.policy import DataKind, ExecutionContext, ProviderPolicy
from flight_hunter.domain.search_results import Confidence, DealCandidate

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_demo_search_returns_cached_offer_with_caveats() -> None:
    service = DemoSearchService(
        registry=ProviderRegistry.default(clock=lambda: NOW), clock=lambda: NOW
    )

    result = service.search(
        SearchRequest(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            passengers=2,
            currency="PLN",
            provider_ids=None,
        )
    )

    assert result.search_id
    assert [offer.provider_id for offer in result.mergeable_offers] == ["fake"]
    assert result.mergeable_offers[0].freshness == Freshness.CACHED
    assert result.mergeable_offers[0].requires_live_confirmation
    assert result.provider_isolated_offers == ()
    assert result.priced_offers == result.mergeable_offers
    assert {link.source_id for link in result.external_links} >= {
        "aviasales_clickout",
        "tutu",
        "yandex_travel",
    }
    assert result.browser_observed_offers == ()
    assert result.deal_candidates == ()
    assert result.freshness_summary.needs_external_confirmation is True
    assert "external_links_are_not_prices" in result.warnings
    assert "aviasales_search" in result.denied_providers


def test_demo_search_does_not_merge_provider_isolated_results() -> None:
    service = DemoSearchService(
        registry=ProviderRegistry.default(clock=lambda: NOW), clock=lambda: NOW
    )

    result = service.search(
        SearchRequest(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="PLN",
            provider_ids=("aviasales_search",),
        )
    )

    assert result.mergeable_offers == ()
    assert result.provider_isolated_offers == ()
    assert result.denied_providers["aviasales_search"].code == "provider_disabled"


def test_search_enrichment_keeps_deal_candidates_out_of_priced_offers() -> None:
    service = DemoSearchService(
        registry=ProviderRegistry.default(clock=lambda: NOW), clock=lambda: NOW
    )
    result = service.search(
        SearchRequest(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            provider_ids=None,
        )
    )
    candidate = DealCandidate(
        source_id="deal_discovery",
        url="https://example.com/deal",
        title="Manual deal hint",
        summary_ru="Manual verification required.",
        extracted_price=Money(1_842_000, "RUB"),
        extracted_origin="MOW",
        extracted_destination="IST",
        extracted_date_window="2026-09-10",
        confidence=Confidence.MEDIUM,
        discovered_at=NOW,
        requires_manual_verification=True,
    )

    enriched = with_browser_observed_offers_and_deal_candidates(
        result,
        browser_observed_offers=(),
        deal_candidates=(candidate,),
    )

    assert enriched.priced_offers == result.priced_offers
    assert enriched.mergeable_offers == result.mergeable_offers
    assert enriched.deal_candidates == (candidate,)
    assert "deal_candidates_require_manual_verification" in enriched.warnings


def test_search_service_calls_enabled_aviasales_data_provider_through_plan() -> None:
    registry = ProviderRegistry.default(
        clock=lambda: NOW,
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_data_enabled=True,
            travelpayouts_api_token="secret-value",
            aviasales_data_default_market="pl",
            aviasales_data_internal_rpm=30,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
    )
    aviasales_provider = StubOfferProvider()
    service = DemoSearchService(
        registry=registry,
        clock=lambda: NOW,
        providers={"aviasales_data": aviasales_provider},
    )

    result = service.search(
        SearchRequest(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="PLN",
            provider_ids=("aviasales_data",),
        )
    )

    assert aviasales_provider.calls == 1
    assert [offer.provider_id for offer in result.mergeable_offers] == ["aviasales_data"]
    assert result.ranking_reasons["aviasales_data:offer-1"] == (
        "cached_price",
        "requires_live_confirmation",
        "baggage_unknown",
    )


def test_search_service_passes_passenger_mix_to_provider_intent() -> None:
    registry = ProviderRegistry((_policy("provider_a"),))
    provider = RecordingOfferProvider()
    service = DemoSearchService(
        registry=registry,
        clock=lambda: NOW,
        providers={"provider_a": provider},
    )

    service.search(
        SearchRequest(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            passengers=3,
            currency="PLN",
            provider_ids=("provider_a",),
            adults=2,
            children=1,
            infants=0,
            trip_type="round_trip",
        )
    )

    assert provider.last_passenger_mix == (2, 1, 0)


def test_search_service_ranks_mergeable_offers_with_freshness_caveats() -> None:
    registry = ProviderRegistry(
        (
            _policy("provider_a"),
            _policy("provider_b"),
        )
    )
    service = DemoSearchService(
        registry=registry,
        clock=lambda: NOW,
        providers={
            "provider_a": StaticOfferProvider(
                provider_id="provider_a",
                provider_offer_id="stale-cheaper",
                amount_minor=49_000,
                freshness=Freshness.STALE,
                baggage_summary="hand baggage included",
            ),
            "provider_b": StaticOfferProvider(
                provider_id="provider_b",
                provider_offer_id="cached-clear",
                amount_minor=50_000,
                freshness=Freshness.CACHED,
                baggage_summary="hand baggage included",
            ),
        },
    )

    result = service.search(
        SearchRequest(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="PLN",
            provider_ids=None,
        )
    )

    assert [offer.provider_offer_id for offer in result.mergeable_offers] == [
        "cached-clear",
        "stale-cheaper",
    ]


class StubOfferProvider:
    def __init__(self) -> None:
        self.calls = 0

    def search(
        self,
        intent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        self.calls += 1
        return (
            FlightOffer(
                provider_id="aviasales_data",
                provider_offer_id="offer-1",
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=intent.return_date,
                total_price=Money(51200, intent.currency),
                passengers=intent.passengers,
                observed_at=NOW,
                freshness=Freshness.CACHED,
                requires_live_confirmation=True,
                baggage_summary=None,
            ),
        )


class StaticOfferProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        provider_offer_id: str,
        amount_minor: int,
        freshness: Freshness,
        baggage_summary: str | None,
    ) -> None:
        self._provider_id = provider_id
        self._provider_offer_id = provider_offer_id
        self._amount_minor = amount_minor
        self._freshness = freshness
        self._baggage_summary = baggage_summary

    def search(
        self,
        intent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        return (
            FlightOffer(
                provider_id=self._provider_id,
                provider_offer_id=self._provider_offer_id,
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=intent.return_date,
                total_price=Money(self._amount_minor, intent.currency),
                passengers=intent.passengers,
                observed_at=NOW,
                freshness=self._freshness,
                requires_live_confirmation=True,
                baggage_summary=self._baggage_summary,
            ),
        )


class RecordingOfferProvider:
    def __init__(self) -> None:
        self.last_passenger_mix: tuple[int, int, int] | None = None

    def search(
        self,
        intent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        mix = intent.passenger_mix
        self.last_passenger_mix = (mix.adults, mix.children, mix.infants)
        return (
            FlightOffer(
                provider_id="provider_a",
                provider_offer_id="offer-1",
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=intent.return_date,
                total_price=Money(51200, intent.currency),
                passengers=intent.passengers,
                observed_at=NOW,
                freshness=Freshness.CACHED,
                requires_live_confirmation=True,
                baggage_summary=None,
            ),
        )


def _policy(provider_id: str) -> ProviderPolicy:
    return ProviderPolicy(
        provider_id=provider_id,
        policy_version="2026-06-23",
        terms_url="https://example.test/provider",
        terms_verified_at=NOW,
        enabled=True,
        credentials_present=True,
        access_approved=True,
        data_kind=DataKind.CACHED,
        background_requests_allowed=True,
        user_action_required=False,
        merge_with_other_sources_allowed=True,
        persist_raw_results_allowed=False,
        persist_normalized_results_allowed=True,
        booking_link_requires_click=True,
        preload_booking_links_allowed=False,
        server_side_only=True,
        real_user_ip_required=False,
        max_requests_per_minute=None,
        max_requests_per_hour_per_user_ip=None,
        cache_ttl_seconds=300,
        result_ttl_seconds=86_400,
        max_concurrent_requests=1,
        supports_flexible_dates=True,
        supports_nearby_airports=False,
        supports_multi_city=False,
        supports_one_way=True,
        supports_round_trip=True,
        supports_baggage=False,
        supports_fare_rules=False,
        notes="test",
    )
