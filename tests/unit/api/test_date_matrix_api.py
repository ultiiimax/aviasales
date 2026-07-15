from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.providers.aviasales_search.client import CalendarPrice


@dataclass(frozen=True, slots=True)
class FakeCalendarProvider:
    prices: tuple[CalendarPrice, ...]
    calls: list[dict[str, object]] = field(default_factory=list)

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
        self.calls.append(
            {
                "origin": origin,
                "destination": destination,
                "depart_from": depart_from,
                "depart_to": depart_to,
                "one_way": one_way,
                "currency": currency,
            }
        )
        assert origin == "MOW"
        assert destination == "IST"
        assert depart_from == "2026-09-09"
        assert depart_to == "2026-09-11"
        assert one_way is False
        assert currency == "RUB"
        return self.prices


def test_date_matrix_endpoint_returns_unpriced_planning_cells() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "departure_date": "2026-10-12",
            "return_date": "2026-10-19",
            "flexibility_days": 3,
            "min_stay_days": 6,
            "max_stay_days": 8,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["route_required_for_pricing"]
    assert body["cells"]
    assert all(6 <= cell["stay_days"] <= 8 for cell in body["cells"])
    assert all(cell["evidence_kind"] is None for cell in body["cells"])
    assert all(cell["confirmation_state"] is None for cell in body["cells"])


def test_date_matrix_with_route_gracefully_reports_missing_mobile_provider() -> None:
    client = TestClient(
        create_app(
            settings=AppSettings(
                database_url="sqlite+aiosqlite:///:memory:",
                aviasales_search_enabled=True,
                aviasales_search_signature=None,
                aviasales_search_marker=None,
                aviasales_search_internal_rpm=20,
                telegram_enabled=False,
                telegram_webhook_secret=None,
            )
        )
    )

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["aviasales_search_credentials_missing"]
    assert all(cell["amount_minor"] is None for cell in body["cells"])


def test_date_matrix_rejects_unsupported_passenger_mix_before_provider_lookup() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "children": 1,
        },
    )

    assert response.status_code == 422


def test_date_matrix_rejects_contradictory_passenger_fields_before_provider_io() -> None:
    provider = FakeCalendarProvider(prices=())
    client = TestClient(create_app(provider_instances={"aviasales_search": provider}))

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "passengers": 1,
            "adults": 2,
            "children": 0,
            "infants": 0,
        },
    )

    assert response.status_code == 422
    assert provider.calls == []


def test_date_matrix_rejects_multi_adult_inferred_totals_before_provider_lookup() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "passengers": 2,
            "adults": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["passenger_mix_not_supported"]
    assert all(cell["amount_minor"] is None for cell in body["cells"])


def test_date_matrix_can_overlay_aviasales_mobile_calendar_prices() -> None:
    provider = FakeCalendarProvider(
        prices=(
            CalendarPrice(
                origin="MOW",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                price_minor_units=1_842_000,
                currency="RUB",
            ),
        )
    )
    client = TestClient(create_app(provider_instances={"aviasales_search": provider}))

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_search"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    priced_cells = [cell for cell in body["cells"] if cell["amount_minor"] is not None]
    assert body["provider_calls_required"] == 1
    assert body["priced"] is True
    assert body["pricing_denials"] == []
    assert len(priced_cells) == 1
    assert priced_cells[0]["departure_date"] == "2026-09-10"
    assert priced_cells[0]["return_date"] == "2026-09-20"
    assert priced_cells[0]["amount_minor"] == 1_842_000
    assert priced_cells[0]["currency"] == "RUB"
    assert priced_cells[0]["provider_id"] == "aviasales_search"
    assert priced_cells[0]["freshness"] == "live"
    assert priced_cells[0]["evidence_kind"] == "discovery_signal"
    assert priced_cells[0]["confirmation_state"] == "indicative"
    assert priced_cells[0]["requires_live_confirmation"] is True
    assert priced_cells[0]["passengers"] == 1
    assert priced_cells[0]["price_basis"] == "provider_single_adult_ticket"


def test_date_matrix_never_attaches_a_wrong_route_calendar_row_by_date_alone() -> None:
    provider = FakeCalendarProvider(
        prices=(
            CalendarPrice(
                origin="LED",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                price_minor_units=100,
                currency="RUB",
            ),
        )
    )
    client = TestClient(create_app(provider_instances={"aviasales_search": provider}))

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_search"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["priced"] is False
    assert body["pricing_denials"] == ["aviasales_search_empty"]
    assert all(cell["amount_minor"] is None for cell in body["cells"])


def test_date_matrix_mixed_currency_rows_return_stable_pricing_denial() -> None:
    provider = FakeCalendarProvider(
        prices=(
            CalendarPrice(
                origin="MOW",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                price_minor_units=1_842_000,
                currency="RUB",
            ),
            CalendarPrice(
                origin="MOW",
                destination="IST",
                departure_date="2026-09-11",
                return_date="2026-09-21",
                price_minor_units=100,
                currency="USD",
            ),
        )
    )
    client = TestClient(create_app(provider_instances={"aviasales_search": provider}))

    response = client.post(
        "/api/v1/searches/date-matrix",
        json={
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "flexibility_days": 1,
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_search"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["priced"] is False
    assert body["pricing_denials"] == ["aviasales_search_schema_error"]
    assert all(cell["amount_minor"] is None for cell in body["cells"])
