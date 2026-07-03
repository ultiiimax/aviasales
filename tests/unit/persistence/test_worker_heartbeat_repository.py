from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    NewWorkerHeartbeat,
    WorkerControlRepository,
    WorkerHeartbeatRepository,
)

NOW = datetime(2026, 6, 29, 23, 10, tzinfo=UTC)
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.mark.anyio
async def test_worker_heartbeat_repository_upserts_and_lists_newest_first() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = WorkerHeartbeatRepository(session)
        await repository.upsert(
            NewWorkerHeartbeat(
                worker_id="worker-a",
                role="flight_hunter_worker",
                status="running",
                current_phase="claiming",
                started_at=NOW,
                last_seen_at=NOW,
            )
        )
        await repository.upsert(
            NewWorkerHeartbeat(
                worker_id="worker-b",
                role="flight_hunter_worker",
                status="idle",
                current_phase="idle",
                started_at=NOW,
                last_seen_at=NOW + timedelta(seconds=1),
                last_summary_json='{"browser_jobs_seen": 0}',
            )
        )
        await repository.upsert(
            NewWorkerHeartbeat(
                worker_id="worker-a",
                role="flight_hunter_worker",
                status="stopped",
                current_phase="stopped",
                started_at=NOW,
                last_seen_at=NOW + timedelta(seconds=2),
                stopped_at=NOW + timedelta(seconds=2),
                last_summary_json='{"browser_jobs_seen": 1}',
            )
        )
        await session.commit()

    async with session_factory() as session:
        heartbeats = await WorkerHeartbeatRepository(session).list_recent(limit=10)
        second_page = await WorkerHeartbeatRepository(session).list_recent(limit=1, offset=1)

    assert [heartbeat.worker_id for heartbeat in heartbeats] == ["worker-a", "worker-b"]
    assert [heartbeat.worker_id for heartbeat in second_page] == ["worker-b"]
    assert heartbeats[0].status == "stopped"
    assert heartbeats[0].stopped_at == NOW + timedelta(seconds=2)
    assert heartbeats[0].last_summary_json == '{"browser_jobs_seen": 1}'


@pytest.mark.anyio
async def test_worker_control_repository_defaults_sets_and_clears_drain() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = WorkerControlRepository(session)

        default_state = await repository.get_state()
        drained = await repository.set_drain(
            drain_requested=True,
            reason="deploy window",
            requested_by_household_id=HOUSEHOLD_ID,
            requested_by_user_id=USER_ID,
            changed_at=NOW,
        )
        cleared = await repository.set_drain(
            drain_requested=False,
            reason="ignored after clear",
            requested_by_household_id=HOUSEHOLD_ID,
            requested_by_user_id=USER_ID,
            changed_at=NOW + timedelta(minutes=5),
        )
        await session.commit()

    assert default_state.drain_requested is False
    assert default_state.updated_at is None
    assert drained.drain_requested is True
    assert drained.reason == "deploy window"
    assert drained.requested_by_household_id == HOUSEHOLD_ID
    assert drained.requested_by_user_id == USER_ID
    assert drained.requested_at == NOW
    assert drained.cleared_at is None
    assert cleared.drain_requested is False
    assert cleared.reason is None
    assert cleared.requested_by_household_id is None
    assert cleared.requested_by_user_id is None
    assert cleared.requested_at is None
    assert cleared.cleared_at == NOW + timedelta(minutes=5)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
