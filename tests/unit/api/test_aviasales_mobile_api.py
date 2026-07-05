from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, FlightSegmentSummary, Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.providers.aviasales_search.client import (
    CalendarPrice,
    GraphqlFeedBlock,
    HotOffer,
    SuggestPlace,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


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
    assert calendar.json()["prices"][0]["departure_date"] == "2026-09-01"
    assert blocks.status_code == 200
    assert blocks.json()["blocks"] == [{"typename": "HotTicketsBlock"}]


def _app(provider: FakeMobileProvider):
    return create_app(
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_search_enabled=True,
            aviasales_search_signature="secret-signature",
            aviasales_search_marker="secret-marker",
            aviasales_search_internal_rpm=20,
            telegram_enabled=False,
            telegram_webhook_secret=None,
            app_secret_key="test-secret",
        ),
        provider_instances={"aviasales_search": provider},
    )
