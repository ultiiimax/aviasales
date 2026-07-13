from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    NewPriceSnapshot,
    PriceSnapshotRepository,
)

HOUSEHOLD_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
HOUSEHOLD_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
USER_B = "bbbbbbbb-0000-0000-0000-000000000001"


@pytest.mark.anyio
async def test_create_watch_requires_household_context() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    response = client.post(
        "/api/v1/watches",
        json=_watch_payload(),
    )

    assert response.status_code == 401
    assert response.json() == {
        "code": "auth_context_missing",
        "message": "household context is required",
    }


@pytest.mark.anyio
async def test_create_watch_and_list_only_same_household() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    created_a = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(origin="waw", destination="bcn"),
    )
    created_b = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_B, USER_B),
        json=_watch_payload(origin="WAW", destination="NRT"),
    )
    list_a = client.get("/api/v1/watches", headers=_headers(HOUSEHOLD_A, USER_A))

    assert created_a.status_code == 201
    assert created_b.status_code == 201
    assert UUID(created_a.json()["id"])
    assert created_a.json()["origin"] == "WAW"
    assert created_a.json()["destination"] == "BCN"
    assert created_a.json()["passengers"] == 1
    assert created_a.json()["currency"] == "RUB"
    assert created_a.json()["enabled"] is True
    assert created_a.json()["version"] == 1
    assert created_a.json()["updated_at"] == created_a.json()["created_at"]
    assert [item["destination"] for item in list_a.json()["watches"]] == ["BCN"]


@pytest.mark.anyio
async def test_get_pause_resume_watch_requires_same_household() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))
    created = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(),
    )
    watch_id = created.json()["id"]
    paused_until = (datetime(2026, 6, 30, 12, 0, tzinfo=UTC)).isoformat()

    hidden = client.get(f"/api/v1/watches/{watch_id}", headers=_headers(HOUSEHOLD_B, USER_B))
    detail = client.get(f"/api/v1/watches/{watch_id}", headers=_headers(HOUSEHOLD_A, USER_A))
    paused = client.post(
        f"/api/v1/watches/{watch_id}/pause",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"paused_until": paused_until},
    )
    resumed = client.post(
        f"/api/v1/watches/{watch_id}/resume",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )

    assert hidden.status_code == 404
    assert hidden.json()["code"] == "watch_not_found"
    assert detail.status_code == 200
    assert detail.json()["id"] == watch_id
    assert paused.status_code == 200
    assert paused.json()["paused_until"] == paused_until
    assert paused.json()["next_eligible_at"] == paused_until
    assert paused.json()["version"] == 2
    assert resumed.status_code == 200
    assert resumed.json()["paused_until"] is None
    assert resumed.json()["enabled"] is True
    assert resumed.json()["version"] == 3


@pytest.mark.anyio
async def test_patch_watch_uses_version_and_preserves_household_isolation() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))
    created = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(destination="BCN"),
    )
    watch_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/watches/{watch_id}",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={
            "expected_version": 1,
            "destination": "nrt",
            "return_date": None,
            "enabled": False,
            "allowed_provider_ids": ["fake", "aviasales_search"],
        },
    )
    stale = client.patch(
        f"/api/v1/watches/{watch_id}",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"expected_version": 1, "enabled": True},
    )
    hidden = client.patch(
        f"/api/v1/watches/{watch_id}",
        headers=_headers(HOUSEHOLD_B, USER_B),
        json={"expected_version": 2, "enabled": True},
    )

    assert updated.status_code == 200
    assert updated.json()["destination"] == "NRT"
    assert updated.json()["return_date"] is None
    assert updated.json()["enabled"] is False
    assert updated.json()["allowed_provider_ids"] == ["fake", "aviasales_search"]
    assert updated.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json() == {
        "code": "watch_version_conflict",
        "message": "watch version is stale",
        "current_version": 2,
    }
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "watch_not_found"


@pytest.mark.anyio
async def test_archive_watch_hides_it_from_list_detail_and_history() -> None:
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    created = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(destination="BCN"),
    )
    watch_id = created.json()["id"]
    await _add_snapshot(session_factory, household_id=UUID(HOUSEHOLD_A), watch_id=UUID(watch_id))

    archived = client.post(
        f"/api/v1/watches/{watch_id}/archive",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"expected_version": 1},
    )
    list_after = client.get("/api/v1/watches", headers=_headers(HOUSEHOLD_A, USER_A))
    detail_after = client.get(f"/api/v1/watches/{watch_id}", headers=_headers(HOUSEHOLD_A, USER_A))
    history_after = client.get(
        f"/api/v1/watches/{watch_id}/history",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )

    assert archived.status_code == 200
    assert archived.json() == {"watch_id": watch_id, "status": "archived", "version": 2}
    assert list_after.json()["watches"] == []
    assert detail_after.status_code == 404
    assert history_after.status_code == 404
    async with session_factory() as session:
        events = await AuditEventRepository(session).list_events(UUID(HOUSEHOLD_A))
    assert [event.action for event in events] == ["watch.created", "watch.archived"]


@pytest.mark.anyio
async def test_delete_watch_is_soft_delete_with_version_conflict() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))
    created = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(destination="BCN"),
    )
    watch_id = created.json()["id"]

    stale = client.request(
        "DELETE",
        f"/api/v1/watches/{watch_id}",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"expected_version": 2},
    )
    deleted = client.request(
        "DELETE",
        f"/api/v1/watches/{watch_id}",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"expected_version": 1},
    )
    detail_after = client.get(f"/api/v1/watches/{watch_id}", headers=_headers(HOUSEHOLD_A, USER_A))

    assert stale.status_code == 409
    assert stale.json()["current_version"] == 1
    assert deleted.status_code == 200
    assert deleted.json() == {"watch_id": watch_id, "status": "deleted", "version": 2}
    assert detail_after.status_code == 404


@pytest.mark.anyio
async def test_watch_history_returns_only_household_scoped_snapshots() -> None:
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))
    created_a = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json=_watch_payload(destination="BCN"),
    )
    created_b = client.post(
        "/api/v1/watches",
        headers=_headers(HOUSEHOLD_B, USER_B),
        json=_watch_payload(destination="NRT"),
    )
    watch_a = UUID(created_a.json()["id"])
    watch_b = UUID(created_b.json()["id"])
    await _add_snapshot(session_factory, household_id=UUID(HOUSEHOLD_A), watch_id=watch_a)
    await _add_snapshot(session_factory, household_id=UUID(HOUSEHOLD_B), watch_id=watch_b)

    history = client.get(
        f"/api/v1/watches/{watch_a}/history", headers=_headers(HOUSEHOLD_A, USER_A)
    )
    hidden = client.get(f"/api/v1/watches/{watch_a}/history", headers=_headers(HOUSEHOLD_B, USER_B))

    assert history.status_code == 200
    body = history.json()
    assert body["watch_id"] == str(watch_a)
    assert len(body["snapshots"]) == 1
    assert body["snapshots"][0]["provider_id"] == "fake"
    assert body["snapshots"][0]["amount_minor"] == 123_456
    assert body["snapshots"][0]["freshness"] == "cached"
    assert hidden.status_code == 404


def _headers(household_id: str, user_id: str) -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": household_id,
        "X-Flight-Hunter-User-Id": user_id,
    }


def _watch_payload(
    *,
    origin: str = "WAW",
    destination: str = "BCN",
) -> dict[str, object]:
    return {
        "origin": origin,
        "destination": destination,
        "departure_date": "2026-10-12",
        "return_date": "2026-10-19",
    }


async def _add_snapshot(session_factory, *, household_id: UUID, watch_id: UUID) -> None:
    async with session_factory() as session:
        await PriceSnapshotRepository(session).add_snapshot(
            NewPriceSnapshot(
                id=UUID(int=watch_id.int % (2**128)),
                household_id=household_id,
                watch_id=watch_id,
                provider_id="fake",
                itinerary_fingerprint="fake:route",
                observed_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
                price=Money(123_456, "RUB"),
                freshness=Freshness.CACHED,
                requires_live_confirmation=True,
            )
        )
        await session.commit()


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
