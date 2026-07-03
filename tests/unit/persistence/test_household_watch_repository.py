from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    HouseholdWatchRepository,
    NewAuditEvent,
    NewWatch,
)

HOUSEHOLD_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
WATCH_A = UUID("11111111-1111-1111-1111-111111111111")
WATCH_B = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_repository_lists_only_watches_for_requested_household() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date="2026-10-19",
                created_at=NOW,
            )
        )
        await repository.add_watch(
            NewWatch(
                id=WATCH_B,
                household_id=HOUSEHOLD_B,
                owner_user_id=UUID("bbbbbbbb-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="NRT",
                departure_date="2026-11-02",
                return_date=None,
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        watches = await repository.list_watches(HOUSEHOLD_A)

    assert [watch.id for watch in watches] == [WATCH_A]


@pytest.mark.anyio
async def test_repository_get_by_id_requires_matching_household() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        visible = await repository.get_watch(HOUSEHOLD_A, WATCH_A)
        hidden = await repository.get_watch(HOUSEHOLD_B, WATCH_A)

    assert visible is not None
    assert hidden is None


@pytest.mark.anyio
async def test_repository_lists_archived_and_deleted_watches_for_privacy_export() -> None:
    session_factory = await _session_factory()
    user_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=user_id,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        await repository.add_watch(
            NewWatch(
                id=WATCH_B,
                household_id=HOUSEHOLD_A,
                owner_user_id=user_id,
                origin="WAW",
                destination="IST",
                departure_date="2026-11-02",
                return_date=None,
                created_at=NOW + timedelta(minutes=1),
            )
        )
        await repository.delete_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_B,
            expected_version=1,
            deleted_at=NOW + timedelta(minutes=2),
            deleted_by_user_id=user_id,
        )
        await repository.add_watch(
            NewWatch(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                household_id=HOUSEHOLD_B,
                owner_user_id=user_id,
                origin="WAW",
                destination="NRT",
                departure_date="2026-12-02",
                return_date=None,
                created_at=NOW + timedelta(minutes=3),
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        active = await repository.list_watches(HOUSEHOLD_A)
        exported = await repository.list_watches_for_export(HOUSEHOLD_A, limit=10)
        limited = await repository.list_watches_for_export(HOUSEHOLD_A, limit=1)

    assert [watch.id for watch in active] == [WATCH_A]
    assert [watch.id for watch in exported] == [WATCH_A, WATCH_B]
    assert exported[1].deleted_by_user_id == user_id
    assert [watch.id for watch in limited] == [WATCH_A]


@pytest.mark.anyio
async def test_repository_lists_due_watches_and_records_scan_result() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date="2026-10-19",
                created_at=NOW - timedelta(hours=1),
                next_eligible_at=NOW - timedelta(minutes=1),
                scan_interval_seconds=3600,
                allowed_provider_ids=("fake",),
            )
        )
        await repository.add_watch(
            NewWatch(
                id=WATCH_B,
                household_id=HOUSEHOLD_B,
                owner_user_id=UUID("bbbbbbbb-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="NRT",
                departure_date="2026-11-02",
                return_date=None,
                created_at=NOW - timedelta(hours=1),
                next_eligible_at=NOW + timedelta(hours=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        due = await repository.list_due_watches(now=NOW, limit=10)
        await repository.record_scan_result(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            scanned_at=NOW,
            next_eligible_at=NOW + timedelta(hours=1),
            status="succeeded",
            error_code=None,
        )
        updated = await repository.get_watch(HOUSEHOLD_A, WATCH_A)

    assert [watch.id for watch in due] == [WATCH_A]
    assert due[0].passengers == 1
    assert due[0].currency == "RUB"
    assert due[0].allowed_provider_ids == ("fake",)
    assert updated is not None
    assert updated.last_scan_status == "succeeded"
    assert updated.next_eligible_at == NOW + timedelta(hours=1)


@pytest.mark.anyio
async def test_repository_pauses_and_resumes_watch_without_cross_household_access() -> None:
    session_factory = await _session_factory()
    paused_until = NOW + timedelta(hours=24)
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        hidden_pause = await repository.pause_watch(
            household_id=HOUSEHOLD_B,
            watch_id=WATCH_A,
            paused_until=paused_until,
            updated_at=NOW,
        )
        paused = await repository.pause_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            paused_until=paused_until,
            updated_at=NOW,
        )
        due_while_paused = await repository.list_due_watches(now=NOW + timedelta(hours=1), limit=10)
        resumed = await repository.resume_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            resumed_at=NOW + timedelta(hours=2),
        )

    assert hidden_pause is None
    assert paused is not None
    assert paused.paused_until == paused_until
    assert paused.next_eligible_at == paused_until
    assert due_while_paused == ()
    assert resumed is not None
    assert resumed.paused_until is None
    assert resumed.next_eligible_at == NOW + timedelta(hours=2)


@pytest.mark.anyio
async def test_repository_updates_watch_with_optimistic_version() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=UUID("aaaaaaaa-0000-0000-0000-000000000001"),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        updated = await repository.update_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            expected_version=1,
            updated_at=NOW + timedelta(minutes=5),
            updates={
                "enabled": False,
                "scan_interval_seconds": 7200,
                "allowed_provider_ids": ("fake", "aviasales_data"),
            },
        )
        stale = await repository.update_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            expected_version=1,
            updated_at=NOW + timedelta(minutes=10),
            updates={"enabled": True},
        )
        hidden = await repository.update_watch(
            household_id=HOUSEHOLD_B,
            watch_id=WATCH_A,
            expected_version=2,
            updated_at=NOW + timedelta(minutes=10),
            updates={"enabled": True},
        )

    assert updated.status == "updated"
    assert updated.watch is not None
    assert updated.watch.version == 2
    assert updated.watch.enabled is False
    assert updated.watch.scan_interval_seconds == 7200
    assert updated.watch.allowed_provider_ids == ("fake", "aviasales_data")
    assert updated.watch.updated_at == NOW + timedelta(minutes=5)
    assert stale.status == "version_conflict"
    assert stale.current_version == 2
    assert hidden.status == "not_found"


@pytest.mark.anyio
async def test_repository_archives_watch_and_excludes_it_from_active_queries() -> None:
    session_factory = await _session_factory()
    archived_at = NOW + timedelta(minutes=5)
    archived_by = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        await repository.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=archived_by,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
                next_eligible_at=NOW - timedelta(minutes=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        archived = await repository.archive_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            expected_version=1,
            archived_at=archived_at,
            archived_by_user_id=archived_by,
        )
        active = await repository.list_watches(HOUSEHOLD_A)
        due = await repository.list_due_watches(now=NOW + timedelta(minutes=10), limit=10)
        hidden_detail = await repository.get_watch(HOUSEHOLD_A, WATCH_A)
        stale_archive = await repository.archive_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            expected_version=1,
            archived_at=archived_at + timedelta(minutes=1),
            archived_by_user_id=archived_by,
        )

    assert archived.status == "archived"
    assert archived.current_version == 2
    assert active == ()
    assert due == ()
    assert hidden_detail is None
    assert stale_archive.status == "not_found"


@pytest.mark.anyio
async def test_audit_repository_records_household_scoped_watch_events() -> None:
    session_factory = await _session_factory()
    user_id = UUID("aaaaaaaa-0000-0000-0000-000000000001")
    async with session_factory() as session:
        repository = AuditEventRepository(session)
        await repository.add_event(
            NewAuditEvent(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                household_id=HOUSEHOLD_A,
                actor_user_id=user_id,
                action="watch.archived",
                entity_type="watch",
                entity_id=WATCH_A,
                summary="watch archived",
                created_at=NOW,
            )
        )
        await repository.add_event(
            NewAuditEvent(
                id=UUID("33333333-3333-3333-3333-333333333334"),
                household_id=HOUSEHOLD_A,
                actor_user_id=user_id,
                action="watch.deleted",
                entity_type="watch",
                entity_id=WATCH_A,
                summary="watch deleted",
                created_at=NOW + timedelta(minutes=1),
            )
        )
        await repository.add_event(
            NewAuditEvent(
                id=UUID("44444444-4444-4444-4444-444444444444"),
                household_id=HOUSEHOLD_B,
                actor_user_id=user_id,
                action="watch.archived",
                entity_type="watch",
                entity_id=WATCH_B,
                summary="other household watch archived",
                created_at=NOW,
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = AuditEventRepository(session)
        events = await repository.list_events(HOUSEHOLD_A)
        recent_page = await repository.list_recent(HOUSEHOLD_A, limit=1, offset=1)

    assert [event.entity_id for event in events] == [WATCH_A, WATCH_A]
    assert events[0].action == "watch.archived"
    assert events[0].actor_user_id == user_id
    assert [event.action for event in recent_page] == ["watch.archived"]


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
