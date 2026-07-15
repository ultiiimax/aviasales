from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, FlightSegmentSummary, Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    CalendarPrice,
    GraphqlFeedBlock,
    HotOffer,
    SuggestPlace,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _settings() -> AppSettings:
    return AppSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        aviasales_search_enabled=True,
        aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
        aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
        app_secret_key="test-secret",
    )


class FakeMobileProvider:
    def __init__(self) -> None:
        self.resolved: list[tuple[str, str, str]] = []

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        assert context == ExecutionContext.WEB_USER_ACTION
        return (
            FlightOffer(
                provider_id="aviasales_search",
                provider_offer_id="offer-1",
                origin=intent.origin,
                destination=intent.destination,
                departure_date=intent.departure_date,
                return_date=intent.return_date,
                total_price=Money(123_400, intent.currency),
                passengers=intent.passengers,
                observed_at=NOW,
                freshness=Freshness.LIVE,
                requires_live_confirmation=False,
                baggage_summary="baggage:1",
                seller_name="Gate",
                segments=(
                    FlightSegmentSummary(
                        airline_code="SU",
                        airline_name="Aeroflot",
                        flight_number="SU100",
                        origin=intent.origin,
                        destination=intent.destination,
                        depart_at="2026-09-15T10:00",
                        arrive_at="2026-09-15T12:00",
                    ),
                ),
                booking_action_ref=(
                    '{"provider_id":"aviasales_search","proposal_id":"p1",'
                    '"results_url":"host","search_id":"s1"}'
                ),
            ),
        )

    def resolve_purchase_url(
        self,
        *,
        search_id: str,
        proposal_id: str,
        results_url: str,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> str | None:
        self.resolved.append((search_id, proposal_id, results_url))
        return "https://gate.example/buy"

    def suggest_places(
        self,
        term: str,
        *,
        locale: str = "ru",
        place_types: tuple[str, ...] = ("city", "airport"),
        max_results: int = 5,
    ) -> tuple[SuggestPlace, ...]:
        return (
            SuggestPlace(code="LED", name="Saint Petersburg", place_type="city", country_code="RU"),
        )

    def hot_offers(
        self,
        *,
        origin: str,
        origin_type: str = "city",
        market: str = "RU",
        currency: str = "rub",
        one_way: bool = True,
    ) -> tuple[HotOffer, ...]:
        return (
            HotOffer(
                origin=origin.upper(),
                destination="LED",
                departure_date="2026-09-15",
                return_date=None,
                price_minor_units=123_400,
                currency=currency.upper(),
            ),
        )

    def calendar_prices(
        self,
        *,
        origin: str,
        destination: str,
        depart_from: str,
        depart_to: str,
        one_way: bool,
        currency: str = "rub",
    ) -> tuple[CalendarPrice, ...]:
        return (
            CalendarPrice(
                origin=origin.upper(),
                destination=destination.upper(),
                departure_date=depart_from,
                return_date=None,
                price_minor_units=123_400,
                currency=currency.upper(),
            ),
        )

    def main_page_blocks(
        self,
        *,
        origin: str,
        origin_type: str = "CITY",
        market: str = "RU",
        currency: str = "rub",
        language: str = "ru",
        one_way: bool = True,
    ) -> tuple[GraphqlFeedBlock, ...]:
        return (GraphqlFeedBlock(typename="HotTicketsBlock"),)


class FailingMobileProvider(FakeMobileProvider):
    def __init__(self, error: AviasalesSearchError) -> None:
        super().__init__()
        self.error = error

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        raise self.error

    def suggest_places(
        self,
        term: str,
        *,
        locale: str = "ru",
        place_types: tuple[str, ...] = ("city", "airport"),
        max_results: int = 5,
    ) -> tuple[SuggestPlace, ...]:
        raise self.error

    def calendar_prices(
        self,
        *,
        origin: str,
        destination: str,
        depart_from: str,
        depart_to: str,
        one_way: bool,
        currency: str = "rub",
    ) -> tuple[CalendarPrice, ...]:
        raise self.error


class CalendarRowsProvider(FakeMobileProvider):
    def __init__(self, rows: tuple[CalendarPrice, ...]) -> None:
        super().__init__()
        self.rows = rows

    def calendar_prices(
        self,
        *,
        origin: str,
        destination: str,
        depart_from: str,
        depart_to: str,
        one_way: bool,
        currency: str = "rub",
    ) -> tuple[CalendarPrice, ...]:
        return self.rows


def test_search_returns_booking_token_and_resolve_returns_purchase_url() -> None:
    provider = FakeMobileProvider()
    client = TestClient(_app(provider))

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "MOW",
            "destination": "LED",
            "departure_date": "2026-09-15",
            "return_date": None,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_search"],
        },
    )

    assert response.status_code == 201
    offer = response.json()["priced_offers"][0]
    assert offer["seller_name"] == "Gate"
    assert offer["segments"][0]["flight_number"] == "SU100"
    assert offer["booking_action_available"] is True
    assert offer["booking_action_token"]

    resolve = client.post(
        "/api/v1/booking-actions/resolve",
        json={"token": offer["booking_action_token"]},
    )

    assert resolve.status_code == 200
    assert resolve.json() == {"status": "resolved", "url": "https://gate.example/buy"}
    assert provider.resolved == [("s1", "p1", "host")]


def test_typed_aviasales_mobile_endpoints_use_provider() -> None:
    client = TestClient(_app(FakeMobileProvider()))

    suggest = client.get("/api/v1/aviasales/suggest?q=led")
    hot = client.get("/api/v1/aviasales/hot-offers?origin=mow")
    calendar = client.get(
        "/api/v1/aviasales/calendar"
        "?origin=mow&destination=led&depart_from=2026-09-01&depart_to=2026-09-30"
    )
    blocks = client.get("/api/v1/aviasales/graphql/main-page-blocks?origin=mow")

    assert suggest.status_code == 200
    assert suggest.json()["places"][0]["code"] == "LED"
    assert hot.status_code == 200
    assert hot.json()["offers"][0]["amount_minor"] == 123_400
    assert calendar.status_code == 200
    calendar_price = calendar.json()["prices"][0]
    assert calendar_price["departure_date"] == "2026-09-01"
    assert calendar_price["evidence_kind"] == "discovery_signal"
    assert calendar_price["confirmation_state"] == "indicative"
    assert calendar_price["requires_live_confirmation"] is True
    assert calendar_price["passengers"] == 1
    assert calendar_price["provider_id"] == "aviasales_search"
    assert calendar_price["source_kind"] == "calendar"
    assert calendar_price["price_basis"] == "provider_single_adult_ticket"
    assert datetime.fromisoformat(calendar_price["observed_at"]).utcoffset() is not None
    assert blocks.status_code == 200
    assert blocks.json()["blocks"] == [{"typename": "HotTicketsBlock"}]


@pytest.mark.parametrize(
    "row",
    [
        CalendarPrice(
            origin="CDG",
            destination="LED",
            departure_date="2026-09-15",
            return_date=None,
            price_minor_units=100,
            currency="RUB",
        ),
        CalendarPrice(
            origin="MOW",
            destination="LED",
            departure_date="private-invalid-date",
            return_date=None,
            price_minor_units=100,
            currency="RUB",
        ),
        CalendarPrice(
            origin="MOW",
            destination="LED",
            departure_date="2026-09-15",
            return_date=None,
            price_minor_units=-100,
            currency="RUB",
        ),
        CalendarPrice(
            origin="MOW",
            destination="LED",
            departure_date="2026-09-15",
            return_date=None,
            price_minor_units=100,
            currency="USD",
        ),
        CalendarPrice(
            origin="MOW",
            destination="LED",
            departure_date="2026-09-15",
            return_date="2026-09-22",
            price_minor_units=100,
            currency="RUB",
        ),
    ],
)
def test_standalone_calendar_never_publishes_invalid_provider_row(
    row: CalendarPrice,
) -> None:
    response = TestClient(_app(CalendarRowsProvider((row,)))).get(
        "/api/v1/aviasales/calendar"
        "?origin=MOW&destination=LED&depart_from=2026-09-01&depart_to=2026-09-30"
        "&one_way=true&currency=RUB"
    )

    if response.status_code == 200:
        assert response.json()["prices"] == []
    else:
        assert response.status_code == 502
        assert response.json()["code"] == "aviasales_search_schema_error"


@pytest.mark.parametrize(
    ("error", "status_code", "code", "retry_after"),
    [
        (
            AviasalesSearchAuthFailed("aviasales_search_auth_failed"),
            502,
            "aviasales_search_auth_failed",
            None,
        ),
        (AviasalesSearchBlocked("aviasales_search_blocked"), 502, "aviasales_search_blocked", None),
        (
            AviasalesSearchSchemaError("aviasales_search_schema_error"),
            502,
            "aviasales_search_schema_error",
            None,
        ),
        (AviasalesSearchError("transport failed"), 502, "aviasales_search_unavailable", None),
        (
            AviasalesSearchRateLimited(retry_after_seconds=17),
            429,
            "aviasales_search_rate_limited",
            "17",
        ),
    ],
)
def test_direct_aviasales_endpoint_returns_stable_coded_error(
    error: AviasalesSearchError,
    status_code: int,
    code: str,
    retry_after: str | None,
) -> None:
    response = TestClient(_app(FailingMobileProvider(error))).get("/api/v1/aviasales/suggest?q=LED")

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert "detail" not in response.json()
    assert response.headers.get("Retry-After") == retry_after


@pytest.mark.parametrize(
    ("settings", "code"),
    [
        (replace(_settings(), aviasales_search_enabled=False), "aviasales_search_disabled"),
        (
            replace(
                _settings(),
                aviasales_search_signature=None,
                aviasales_search_marker=None,
            ),
            "aviasales_search_credentials_missing",
        ),
        (
            replace(
                _settings(),
                aviasales_search_signature="not-a-uuid",
                aviasales_search_marker="not-a-marker",
            ),
            "aviasales_search_credentials_invalid",
        ),
    ],
)
def test_direct_aviasales_endpoint_distinguishes_local_configuration(
    settings: AppSettings,
    code: str,
) -> None:
    response = TestClient(create_app(settings=settings, provider_instances={})).get(
        "/api/v1/aviasales/suggest?q=LED"
    )

    assert response.status_code == 503
    assert response.json()["code"] == code


def test_aggregate_search_keeps_fake_results_when_aviasales_is_blocked() -> None:
    client = TestClient(
        _app(FailingMobileProvider(AviasalesSearchBlocked("aviasales_search_blocked")))
    )

    response = client.post(
        "/api/v1/searches",
        json={
            "origin": "MOW",
            "destination": "LED",
            "departure_date": "2026-09-15",
            "return_date": None,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["fake", "aviasales_search"],
        },
    )

    assert response.status_code == 201
    assert response.json()["offers"][0]["provider_id"] == "fake"
    assert response.json()["denied_providers"]["aviasales_search"]["code"] == (
        "aviasales_search_blocked"
    )


def test_date_matrix_keeps_http_success_and_stable_provider_error() -> None:
    client = TestClient(
        _app(FailingMobileProvider(AviasalesSearchSchemaError("aviasales_search_schema_error")))
    )

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "LED",
            "departure_date": "2026-09-15",
            "return_date": None,
            "flexibility_days": 2,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_search"],
        },
    )

    assert response.status_code == 200
    assert response.json()["priced"] is False
    assert response.json()["pricing_denials"] == ["aviasales_search_schema_error"]


def _app(provider: FakeMobileProvider):
    return create_app(
        settings=_settings(),
        provider_instances={"aviasales_search": provider},
    )
