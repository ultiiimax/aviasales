from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import NewWatchScanJob, WatchScanJobRepository

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
WATCH_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_watch_scan_job_repository_claims_due_job_once() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = WatchScanJobRepository(session)
        created = await repository.enqueue_job(_job())
        await session.commit()

    async with session_factory() as session:
        repository = WatchScanJobRepository(session)
        first = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        second = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-b")
        stored = await repository.get_job(JOB_ID)

    assert created
    assert [job.id for job in first] == [JOB_ID]
    assert second == ()
    assert stored is not None
    assert stored.status == "running"
    assert stored.attempts == 1
    assert stored.locked_at == NOW
    assert stored.locked_by == "worker-a"


@pytest.mark.anyio
async def test_watch_scan_job_repository_recovers_stale_running_job() -> None:
    session_factory = await _session_factory()
    old_lock = NOW - timedelta(minutes=30)
    async with session_factory() as session:
        repository = WatchScanJobRepository(session)
        await repository.enqueue_job(_job())
        await repository.claim_queued(now=old_lock, limit=10, worker_id="worker-a")
        recovered = await repository.recover_stale_running(
            now=NOW,
            stale_before=NOW - timedelta(minutes=15),
            limit=10,
        )
        queued = await repository.list_queued(now=NOW, limit=10)
        stored = await repository.get_job(JOB_ID)

    assert recovered.requeued == 1
    assert recovered.failed == 0
    assert [job.id for job in queued] == [JOB_ID]
    assert stored is not None
    assert stored.status == "retry_scheduled"
    assert stored.next_retry_at == NOW
    assert stored.locked_at is None
    assert stored.locked_by is None
    assert stored.attempts == 1


@pytest.mark.anyio
async def test_watch_scan_job_repository_does_not_claim_until_retry_time() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = WatchScanJobRepository(session)
        await repository.enqueue_job(_job(status="retry_scheduled", next_retry_at=NOW))
        await session.commit()

    async with session_factory() as session:
        repository = WatchScanJobRepository(session)
        before = await repository.claim_queued(
            now=NOW - timedelta(seconds=1),
            limit=10,
            worker_id="worker-a",
        )
        due = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")

    assert before == ()
    assert [job.id for job in due] == [JOB_ID]


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _job(
    *,
    status: str = "queued",
    next_retry_at: datetime | None = None,
) -> NewWatchScanJob:
    return NewWatchScanJob(
        id=JOB_ID,
        household_id=HOUSEHOLD_ID,
        watch_id=WATCH_ID,
        idempotency_key="watch-scan:1",
        status=status,
        attempts=0,
        max_attempts=3,
        next_retry_at=next_retry_at,
        deadline_at=NOW + timedelta(minutes=5),
        created_at=NOW - timedelta(minutes=1),
        provider_ids=("fake",),
        provider_denials={},
    )
