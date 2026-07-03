from __future__ import annotations

from datetime import UTC, datetime

import httpx2
from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app
from flight_hunter.providers.aviasales_data.adapter import AviasalesDataAdapter
from flight_hunter.providers.aviasales_data.client import AviasalesDataClient

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


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


def test_date_matrix_with_route_gracefully_reports_missing_cached_provider() -> None:
    client = TestClient(create_app())

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
    assert body["pricing_denials"] == ["aviasales_data_credentials_missing"]
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

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["passenger_mix_not_supported"]
    assert all(cell["amount_minor"] is None for cell in body["cells"])


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


def test_date_matrix_can_overlay_aviasales_data_week_matrix_cached_prices() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/week-matrix"
        assert request.headers["X-Access-Token"] == "test-token"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18420,
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "actual": True,
                    },
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-11",
                        "return_date": "2026-09-21",
                        "value": 9999,
                        "actual": False,
                    },
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )
    client = TestClient(create_app(provider_instances={"aviasales_data": adapter}))

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
            "provider_ids": ["aviasales_data"],
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
    assert priced_cells[0]["provider_id"] == "aviasales_data"
    assert priced_cells[0]["freshness"] == "cached"
    assert priced_cells[0]["observed_at"] == "2026-06-29T08:15:00+00:00"
    assert priced_cells[0]["requires_live_confirmation"] is True
