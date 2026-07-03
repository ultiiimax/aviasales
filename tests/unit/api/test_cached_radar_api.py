from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import httpx2
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import DealCandidateRepository
from flight_hunter.providers.aviasales_data.adapter import AviasalesDataAdapter
from flight_hunter.providers.aviasales_data.client import AviasalesDataClient

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_cached_radar_reports_missing_aviasales_data_credentials_without_call() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "month_matrix",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["aviasales_data_credentials_missing"]
    assert body["offers"] == []


def test_cached_radar_rejects_unsupported_passenger_mix_before_provider_lookup() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "month_matrix",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 2,
            "adults": 1,
            "children": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["passenger_mix_not_supported"]
    assert body["offers"] == []


def test_cached_radar_rejects_multi_adult_inferred_totals_before_provider_lookup() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "month_matrix",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 2,
            "adults": 2,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 0
    assert body["priced"] is False
    assert body["pricing_denials"] == ["passenger_mix_not_supported"]
    assert body["offers"] == []


def test_cached_radar_returns_month_matrix_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/month-matrix"
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

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "month_matrix",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
            "provider_ids": ["aviasales_data"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["priced"] is True
    assert body["pricing_denials"] == []
    assert body["warnings"] == ["cached_prices_require_external_confirmation"]
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["provider_id"] == "aviasales_data"
    assert offer["origin"] == "MOW"
    assert offer["destination"] == "IST"
    assert offer["price_basis"] == "provider_single_adult_ticket"
    assert offer["total_price"]["minor_units"] == 1_842_000
    assert offer["freshness"] == "cached"
    assert offer["observed_at"] == "2026-06-29T08:15:00+00:00"
    assert offer["requires_live_confirmation"] is True
    assert "cached_month_matrix" in offer["ranking_reasons"]
    assert offer["risk"]["level"] == "medium"
    assert offer["risk"]["flags"] == [
        "cached_price",
        "requires_live_confirmation",
        "baggage_unknown",
        "provider_single_adult_ticket",
    ]


def test_cached_radar_returns_nearest_places_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/nearest-places-matrix"
        assert request.url.params["distance"] == "250"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "DME",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18100,
                        "found_at": "2026-06-29T09:15:00+00:00",
                        "distance": 42,
                        "actual": True,
                    }
                ],
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "nearest_places_matrix",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
            "nearby_distance_km": 250,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["origin"] == "DME"
    assert offer["total_price"]["minor_units"] == 1_810_000
    assert offer["freshness"] == "cached"
    assert "cached_nearest_places_matrix" in offer["ranking_reasons"]


def test_cached_radar_returns_price_range_cached_offers_from_minor_unit_bounds() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/search_by_price_range"
        assert request.url.params["value_min"] == "10000"
        assert request.url.params["value_max"] == "20000"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin_code": "MOW",
                        "destination_code": "IST",
                        "origin_airport": "DME",
                        "destination_airport": "IST",
                        "departure_at": "2026-09-10",
                        "price": 18420,
                        "link": "/MOW1009IST1?t=signature",
                    }
                ],
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "price_range",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": None,
            "passengers": 1,
            "currency": "RUB",
            "min_price_minor": 1_000_000,
            "max_price_minor": 2_000_000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["origin"] == "MOW"
    assert offer["total_price"]["minor_units"] == 1_842_000
    assert offer["freshness"] == "cached"
    assert offer["observed_at"] == NOW.isoformat()
    assert "cached_price_range" in offer["ranking_reasons"]


def test_cached_radar_returns_grouped_prices_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/grouped_prices"
        assert request.url.params["group_by"] == "departure_at"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": {
                    "2026-09-10": {
                        "origin": "MOW",
                        "destination": "IST",
                        "price": 18420,
                        "departure_at": "2026-09-10T09:20:00+03:00",
                        "return_at": "2026-09-20T18:40:00+03:00",
                        "link": "/search/MOW1009IST2009",
                    }
                },
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "grouped_prices",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert body["warnings"] == ["cached_prices_require_external_confirmation"]
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["total_price"]["minor_units"] == 1_842_000
    assert offer["freshness"] == "cached"
    assert offer["requires_live_confirmation"] is True
    assert "cached_grouped_prices" in offer["ranking_reasons"]


def test_cached_radar_returns_latest_prices_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_latest_prices"
        assert request.url.params["period_type"] == "month"
        assert request.url.params["group_by"] == "dates"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "value": 17600,
                        "depart_date": "2026-09-12",
                        "return_date": "2026-09-20",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "actual": True,
                    }
                ],
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "latest_prices",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-01",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["total_price"]["minor_units"] == 1_760_000
    assert offer["observed_at"] == "2026-06-29T08:15:00+00:00"
    assert offer["freshness"] == "cached"
    assert offer["requires_live_confirmation"] is True
    assert "cached_latest_prices" in offer["ranking_reasons"]


def test_cached_radar_returns_popular_directions_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_popular_directions"
        assert request.url.params["destination"] == "IST"
        assert request.url.params["locale"] == "ru"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": {
                    "destination": {"iata": "IST", "name": "Istanbul"},
                    "origin": [
                        {
                            "city_iata": "MOW",
                            "price": 18420,
                            "departure_at": "2026-09-10",
                            "return_at": "2026-09-20",
                        }
                    ],
                },
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "popular_directions",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["origin"] == "MOW"
    assert offer["destination"] == "IST"
    assert offer["total_price"]["minor_units"] == 1_842_000
    assert offer["freshness"] == "cached"
    assert offer["requires_live_confirmation"] is True
    assert "cached_popular_directions" in offer["ranking_reasons"]


def test_cached_radar_returns_special_offers_cached_offers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_special_offers"
        assert request.url.params["origin"] == "MOW"
        assert request.url.params["destination"] == "IST"
        assert request.url.params["locale"] == "ru"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "price": 18420,
                        "departure_at": "2026-09-10",
                        "return_at": "2026-09-20",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "link": "/search/MOW1009IST2009",
                        "signature": "signed-link",
                        "search_id": "provider-search-id",
                    }
                ],
                "error": None,
            },
        )

    client = TestClient(create_app(provider_instances={"aviasales_data": _adapter(handler)}))

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "special_offers",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "return_date": "2026-09-20",
            "passengers": 1,
            "currency": "RUB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider_calls_required"] == 1
    assert body["pricing_denials"] == []
    assert body["warnings"] == ["cached_prices_require_external_confirmation"]
    assert len(body["offers"]) == 1
    offer = body["offers"][0]
    assert offer["origin"] == "MOW"
    assert offer["destination"] == "IST"
    assert offer["total_price"]["minor_units"] == 1_842_000
    assert offer["observed_at"] == "2026-06-29T08:15:00+00:00"
    assert offer["freshness"] == "cached"
    assert offer["requires_live_confirmation"] is True
    assert "cached_special_offers" in offer["ranking_reasons"]


def test_cached_radar_can_persist_aviasales_data_deal_seeds_for_authenticated_search() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_special_offers"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "price": 18420,
                        "departure_at": "2026-09-10",
                        "return_at": "2026-09-20",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "link": "/search/MOW1009IST2009?signature=signed",
                        "signature": "signed-link",
                        "search_id": "provider-search-id",
                    }
                ],
                "error": None,
            },
        )

    session_factory = asyncio.run(_session_factory())
    client = TestClient(
        create_app(
            provider_instances={"aviasales_data": _adapter(handler)},
            watch_session_factory=session_factory,
        )
    )
    headers = {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
    search_request = {
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "currency": "RUB",
    }
    search_id = client.post("/api/v1/searches", headers=headers, json=search_request).json()[
        "search_id"
    ]

    response = client.post(
        "/api/v1/searches/cached-radar",
        headers=headers,
        json={
            **search_request,
            "radar_kind": "special_offers",
            "search_id": search_id,
            "save_deal_candidates": True,
        },
    )
    search_response = client.post("/api/v1/searches", headers=headers, json=search_request)
    other_user_response = client.post(
        "/api/v1/searches",
        headers={**headers, "X-Flight-Hunter-User-Id": str(UUID(int=2))},
        json=search_request,
    )
    stored = asyncio.run(_stored_deal_candidates(session_factory, search_id=search_id))

    assert response.status_code == 200
    body = response.json()
    assert body["deal_candidates_saved"] == 1
    assert len(body["deal_candidates"]) == 1
    candidate = body["deal_candidates"][0]
    assert candidate["source_id"] == "aviasales_data"
    assert candidate["requires_manual_verification"] is True
    assert candidate["extracted_price"]["minor_units"] == 1_842_000
    assert candidate["url"] == "https://www.aviasales.ru/"
    assert "signed-link" not in str(candidate)
    assert len(stored) == 1
    assert search_response.json()["deal_candidates"][0]["source_id"] == "aviasales_data"
    assert "deal_candidates_require_manual_verification" in search_response.json()["warnings"]
    assert other_user_response.json()["deal_candidates"] == []


def test_cached_radar_rejects_price_range_minor_units_that_would_round() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/searches/cached-radar",
        json={
            "radar_kind": "price_range",
            "origin": "MOW",
            "destination": "IST",
            "departure_date": "2026-09-10",
            "passengers": 1,
            "currency": "RUB",
            "min_price_minor": 1_000_050,
            "max_price_minor": 2_000_000,
        },
    )

    assert response.status_code == 422


def _adapter(handler: Callable[[httpx2.Request], httpx2.Response]) -> AviasalesDataAdapter:
    return AviasalesDataAdapter(
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


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _stored_deal_candidates(session_factory, *, search_id: str):
    async with session_factory() as session:
        return await DealCandidateRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id=search_id,
            now=NOW,
        )
