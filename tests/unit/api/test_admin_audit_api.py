from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import AuditEventRepository, NewAuditEvent

HOUSEHOLD_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_B = UUID("bbbbbbbb-0000-0000-0000-000000000001")
WATCH_A = UUID("11111111-1111-1111-1111-111111111111")
WATCH_B = UUID("22222222-2222-2222-2222-222222222222")


@pytest.mark.anyio
async def test_admin_audit_events_require_household_context() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    response = client.get("/api/v1/admin/audit-events")

    assert response.status_code == 401
    assert response.json() == {
        "code": "auth_context_missing",
        "message": "household context is required",
    }


@pytest.mark.anyio
async def test_admin_audit_events_are_household_scoped_and_newest_first() -> None:
    session_factory = await _session_factory()
    await _add_events(session_factory)
    client = TestClient(create_app(watch_session_factory=session_factory))

    response_a = client.get(
        "/api/v1/admin/audit-events?limit=2",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )
    response_b = client.get(
        "/api/v1/admin/audit-events",
        headers=_headers(HOUSEHOLD_B, USER_B),
    )
    response_a_page_2 = client.get(
        "/api/v1/admin/audit-events?limit=1&offset=1",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert response_a_page_2.status_code == 200
    body_a = response_a.json()
    body_a_page_2 = response_a_page_2.json()
    assert body_a["limit"] == 2
    assert body_a["offset"] == 0
    assert body_a_page_2["limit"] == 1
    assert body_a_page_2["offset"] == 1
    events_a = body_a["audit_events"]
    events_b = response_b.json()["audit_events"]
    assert [event["action"] for event in events_a] == [
        "watch.deleted",
        "watch.paused",
    ]
    assert {event["entity_id"] for event in events_a} == {str(WATCH_A)}
    assert all(event["actor_user_id"] == str(USER_A) for event in events_a)
    assert events_a[0]["summary"] == "watch deleted"
    assert events_a[0]["created_at"] == "2026-06-29T12:03:00+00:00"
    assert [event["action"] for event in body_a_page_2["audit_events"]] == ["watch.paused"]
    assert [event["action"] for event in events_b] == ["watch.created"]
    assert events_b[0]["entity_id"] == str(WATCH_B)


async def _add_events(session_factory: async_sessionmaker) -> None:
    async with session_factory() as session:
        repository = AuditEventRepository(session)
        await repository.add_event(
            NewAuditEvent(
                id=UUID("33333333-3333-3333-3333-333333333331"),
                household_id=HOUSEHOLD_A,
                actor_user_id=USER_A,
                action="watch.created",
                entity_type="watch",
                entity_id=WATCH_A,
                summary="watch created",
                created_at=datetime(2026, 6, 29, 12, 1, tzinfo=UTC),
            )
        )
        await repository.add_event(
            NewAuditEvent(
                id=UUID("33333333-3333-3333-3333-333333333332"),
                household_id=HOUSEHOLD_A,
                actor_user_id=USER_A,
                action="watch.paused",
                entity_type="watch",
                entity_id=WATCH_A,
                summary="watch paused",
                created_at=datetime(2026, 6, 29, 12, 2, tzinfo=UTC),
            )
        )
        await repository.add_event(
            NewAuditEvent(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                household_id=HOUSEHOLD_A,
                actor_user_id=USER_A,
                action="watch.deleted",
                entity_type="watch",
                entity_id=WATCH_A,
                summary="watch deleted",
                created_at=datetime(2026, 6, 29, 12, 3, tzinfo=UTC),
            )
        )
        await repository.add_event(
            NewAuditEvent(
                id=UUID("44444444-4444-4444-4444-444444444444"),
                household_id=HOUSEHOLD_B,
                actor_user_id=USER_B,
                action="watch.created",
                entity_type="watch",
                entity_id=WATCH_B,
                summary="other household watch created",
                created_at=datetime(2026, 6, 29, 12, 4, tzinfo=UTC),
            )
        )
        await session.commit()


def _headers(household_id: UUID, user_id: UUID) -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": str(household_id),
        "X-Flight-Hunter-User-Id": str(user_id),
    }


async def _session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
