from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import DealDiscoveryJobRepository, NewDealDiscoveryJob

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_deal_discovery_job_repository_claims_due_job_once() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
        created = await repository.enqueue_job(_job())
        duplicate = await repository.enqueue_job(_job(id_value=UUID(int=9)))
        await session.commit()

    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
        first = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        second = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-b")
        stored = await repository.get_job(JOB_ID)

    assert created is True
    assert duplicate is False
    assert [job.id for job in first] == [JOB_ID]
    assert second == ()
    assert stored is not None
    assert stored.status == "running"
    assert stored.attempts == 1
    assert stored.locked_at == NOW
    assert stored.locked_by == "worker-a"
    assert stored.limit == 3


@pytest.mark.anyio
async def test_deal_discovery_job_repository_recovers_stale_running_job() -> None:
    session_factory = await _session_factory()
    old_lock = NOW - timedelta(minutes=30)
    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
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
async def test_deal_discovery_job_repository_marks_terminal_states() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
        await repository.enqueue_job(_job())
        await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        await repository.mark_succeeded(
            job_id=JOB_ID,
            completed_at=NOW + timedelta(seconds=5),
            result_count=2,
        )
        stored = await repository.get_job(JOB_ID)

    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.completed_at == NOW + timedelta(seconds=5)
    assert stored.result_count == 2
    assert stored.locked_at is None
    assert stored.locked_by is None
    assert stored.error_code is None


@pytest.mark.anyio
async def test_deal_discovery_job_repository_does_not_claim_until_retry_time() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
        await repository.enqueue_job(_job(status="retry_scheduled", next_retry_at=NOW))
        await session.commit()

    async with session_factory() as session:
        repository = DealDiscoveryJobRepository(session)
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
    id_value: UUID = JOB_ID,
    status: str = "queued",
    next_retry_at: datetime | None = None,
) -> NewDealDiscoveryJob:
    return NewDealDiscoveryJob(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        search_id="sha256:search",
        idempotency_key="deal-discovery:1",
        status=status,
        attempts=0,
        max_attempts=3,
        next_retry_at=next_retry_at,
        deadline_at=NOW + timedelta(minutes=5),
        created_at=NOW - timedelta(minutes=1),
        search_intent_json=(
            '{"origin":"MOW","destination":"IST","departure_date":"2026-09-10",'
            '"return_date":"2026-09-20","passengers":1,"currency":"RUB"}'
        ),
        limit=3,
    )
