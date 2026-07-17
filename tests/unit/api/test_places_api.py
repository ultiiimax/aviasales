from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType
from flight_hunter.geo.demo_repository import DemoAirportRepository
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import AirportReferenceRepository


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    database_path = tmp_path / "places.db"
    sync_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    mapper_registry.metadata.create_all(sync_engine)
    sync_engine.dispose()
    settings = replace(
        AppSettings.from_env(),
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    with TestClient(create_app(settings=settings)) as test_client:
        yield test_client


def _search_json(
    *,
    origin: str = "MOW",
    destination: str = "PAR",
    origin_kind: str | None = None,
    destination_kind: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "origin": origin,
        "destination": destination,
        "departure_date": "2026-10-12",
        "return_date": None,
        "passengers": 1,
        "currency": "RUB",
    }
    if origin_kind is not None:
        payload["origin_kind"] = origin_kind
    if destination_kind is not None:
        payload["destination_kind"] = destination_kind
    return payload


def test_places_suggest_returns_human_moscow_and_airports(client: TestClient) -> None:
    response = client.get(
        "/api/v1/places/suggest",
        params={"q": "москва", "locale": "ru"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["catalog_status"] == "ready"
    assert body["enrichment_status"] == "disabled"
    assert len(body["directory_version"]) == 64
    assert body["items"][0]["ref"] == {"kind": "city", "code": "MOW"}
    assert body["items"][0]["display_name"]["text"] == "Москва"
    assert {item["ref"]["code"] for item in body["items"]} >= {
        "MOW",
        "DME",
        "SVO",
        "VKO",
        "ZIA",
    }


def test_places_suggest_short_query_returns_empty_stable_envelope(client: TestClient) -> None:
    response = client.get(
        "/api/v1/places/suggest",
        params={"q": "м", "locale": "ru"},
    )

    assert response.status_code == 200
    assert response.json()["catalog_status"] == "ready"
    assert response.json()["items"] == []


def test_places_lookup_preserves_typed_order_and_reports_unknown(client: TestClient) -> None:
    response = client.post(
        "/api/v1/places/lookup",
        json={
            "locale": "ru",
            "places": [
                {"kind": "airport", "code": "DME"},
                {"kind": "city", "code": "MOW"},
                {"kind": "airport", "code": "XXX"},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["ref"] for item in body["items"]] == [
        {"kind": "airport", "code": "DME"},
        {"kind": "city", "code": "MOW"},
        {"kind": "airport", "code": "XXX"},
    ]
    assert body["items"][0]["resolved"] is True
    assert body["items"][0]["airport_codes"] == ["DME"]
    assert body["items"][1]["airport_codes"] == ["DME", "SVO", "VKO", "ZIA"]
    assert body["items"][2]["resolved"] is False
    assert body["items"][2]["error"]["code"] == "place_unknown"


def test_place_catalog_database_failure_is_not_reported_as_ready(tmp_path: Path) -> None:
    settings = replace(
        AppSettings.from_env(),
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'broken.db').as_posix()}",
    )
    with TestClient(create_app(settings=settings), raise_server_exceptions=False) as broken_client:
        suggested = broken_client.get("/api/v1/places/suggest", params={"q": "Москва"})
        looked_up = broken_client.post(
            "/api/v1/places/lookup",
            json={"places": [{"kind": "city", "code": "MOW"}]},
        )
        searched = broken_client.post("/api/v1/searches", json=_search_json())

    for response in (suggested, looked_up):
        assert response.status_code == 200
        assert response.json() == {
            "catalog_status": "unavailable",
            "enrichment_status": "disabled",
            "directory_version": None,
            "items": [],
        }
    assert searched.status_code == 503
    assert searched.json()["error"]["code"] == "place_unavailable"


@pytest.mark.parametrize(
    "places",
    [
        [
            {"kind": "airport", "code": "DME"},
            {"kind": "airport", "code": "dme"},
        ],
        [{"kind": "airport", "code": "DME"}] * 65,
    ],
)
def test_places_lookup_rejects_duplicate_or_oversized_batches(
    client: TestClient,
    places: list[dict[str, str]],
) -> None:
    response = client.post(
        "/api/v1/places/lookup",
        json={"locale": "ru", "places": places},
    )

    assert response.status_code == 422


def test_search_resolves_legacy_airport_and_city(client: TestClient) -> None:
    response = client.post(
        "/api/v1/searches",
        json=_search_json(origin="DME", destination="PAR"),
    )

    assert response.status_code == 201
    route = response.json()["requested_route"]
    assert route["origin"]["ref"] == {"kind": "airport", "code": "DME"}
    assert route["origin"]["display_name"]["text"] == "Домодедово"
    assert route["origin"]["airport_codes"] == ["DME"]
    assert route["destination"]["ref"] == {"kind": "city", "code": "PAR"}
    assert route["destination"]["airport_codes"] == ["BVA", "CDG", "ORY"]


def test_search_rejects_unknown_legacy_place_with_coded_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/searches",
        json=_search_json(origin="XXX", destination="CDG"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "place_unknown"


def test_search_honors_explicit_kind_instead_of_guessing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/searches",
        json=_search_json(
            origin="DME",
            destination="CDG",
            origin_kind="city",
            destination_kind="airport",
        ),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "place_unknown"


@pytest.mark.anyio
async def test_search_rejects_legacy_kind_collision_from_imported_catalog() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    airports = (
        *DemoAirportRepository().all(),
        Airport(
            iata_code="MOW",
            name="Moscow Test Airport",
            municipality="Moscow",
            country_code="RU",
            latitude=55.75,
            longitude=37.62,
            airport_type=AirportType.LARGE_AIRPORT,
            active=True,
            scheduled_service=True,
            commercial_provenance="test.import",
        ),
    )
    async with session_factory() as session:
        await AirportReferenceRepository(session).import_airports(
            AirportImportBatch(
                source_path="places-test.csv",
                rows_seen=len(airports),
                rows_imported=len(airports),
                airports=airports,
            ),
            imported_at=datetime(2026, 7, 17, 8, 0, tzinfo=UTC),
            source="places-test",
        )
        await session.commit()
    app = create_app(watch_session_factory=session_factory)

    with TestClient(app) as imported_client:
        ambiguous = imported_client.post(
            "/api/v1/searches",
            json=_search_json(origin="MOW", destination="CDG"),
        )
        typed = imported_client.post(
            "/api/v1/searches",
            json=_search_json(
                origin="MOW",
                destination="CDG",
                origin_kind="city",
                destination_kind="airport",
            ),
        )

    assert ambiguous.status_code == 422
    assert ambiguous.json()["error"]["code"] == "place_kind_required"
    assert typed.status_code == 201
    assert typed.json()["requested_route"]["origin"]["ref"]["kind"] == "city"
    await engine.dispose()
