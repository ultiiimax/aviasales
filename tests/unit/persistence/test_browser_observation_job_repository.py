from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.domain.observation import ObservationErrorCode, ObservationStatus
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    NewBrowserObservationJob,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
GRANT_ID = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_browser_observation_job_repository_scopes_idempotency_and_status() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job())
        await session.commit()

    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        job = await repository.get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=JOB_ID,
        )
        other_user = await repository.get_job(
            household_id=HOUSEHOLD_ID,
            user_id=OTHER_USER_ID,
            job_id=JOB_ID,
        )
        idempotent = await repository.get_idempotent_job_id(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            idempotency_key="idem-1",
        )

        assert job is not None
        assert job.status == ObservationStatus.QUEUED
        assert job.attempts == 0
        assert job.search_intent.origin == "MOW"
        assert other_user is None
        assert idempotent == JOB_ID

        await repository.mark_running(job_id=JOB_ID, started_at=NOW + timedelta(seconds=1))
        await repository.mark_failed(
            job_id=JOB_ID,
            completed_at=NOW + timedelta(seconds=2),
            status=ObservationStatus.NO_PRICE_FOUND,
            error_code=ObservationErrorCode.SELECTOR_DRIFT,
            error_message="parser did not extract any offers",
        )
        await session.commit()

    async with session_factory() as session:
        stored = await BrowserObservationJobRepository(session).get_job_by_id(JOB_ID)

    assert stored is not None
    assert stored.status == ObservationStatus.NO_PRICE_FOUND
    assert stored.error_code == ObservationErrorCode.SELECTOR_DRIFT
    assert stored.attempts == 1
    assert stored.last_attempted_at == NOW + timedelta(seconds=1)


@pytest.mark.anyio
async def test_browser_observation_job_repository_lists_unexpired_queued_jobs_in_order() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job(id_value=UUID(int=3), created_at=NOW + timedelta(seconds=2)))
        await repository.add_job(_job(id_value=UUID(int=1), created_at=NOW))
        await repository.add_job(
            _job(
                id_value=UUID(int=2),
                created_at=NOW + timedelta(seconds=1),
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        queued = await BrowserObservationJobRepository(session).list_queued(
            now=NOW,
            limit=10,
        )

    assert [job.id for job in queued] == [UUID(int=1), UUID(int=3)]


@pytest.mark.anyio
async def test_browser_observation_job_repository_claims_queued_job_once() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job())
        await session.commit()

    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        first = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        second = await repository.claim_queued(now=NOW, limit=10, worker_id="worker-b")
        stored = await repository.get_job_by_id(JOB_ID)

    assert [job.id for job in first] == [JOB_ID]
    assert second == ()
    assert stored is not None
    assert stored.status == ObservationStatus.RUNNING
    assert stored.attempts == 1
    assert stored.locked_at == NOW
    assert stored.locked_by == "worker-a"


@pytest.mark.anyio
async def test_browser_observation_job_repository_respects_max_concurrent_claims() -> None:
    session_factory = await _session_factory()
    first_id = UUID(int=10)
    second_id = UUID(int=11)
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job(id_value=first_id, idempotency_key="idem-10"))
        await repository.add_job(
            _job(
                id_value=second_id,
                created_at=NOW + timedelta(seconds=1),
                idempotency_key="idem-11",
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        first = await repository.claim_queued(
            now=NOW,
            limit=10,
            worker_id="worker-a",
            max_concurrent=1,
        )
        second = await repository.claim_queued(
            now=NOW + timedelta(seconds=2),
            limit=10,
            worker_id="worker-b",
            max_concurrent=1,
        )
        queued = await repository.list_queued(now=NOW + timedelta(seconds=2), limit=10)

    assert [job.id for job in first] == [first_id]
    assert second == ()
    assert [job.id for job in queued] == [second_id]


@pytest.mark.anyio
async def test_browser_observation_job_repository_respects_source_min_gap() -> None:
    session_factory = await _session_factory()
    first_id = UUID(int=12)
    second_id = UUID(int=13)
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job(id_value=first_id, idempotency_key="idem-12"))
        await repository.add_job(
            _job(
                id_value=second_id,
                created_at=NOW + timedelta(seconds=1),
                idempotency_key="idem-13",
            )
        )
        claimed = await repository.claim_queued(now=NOW, limit=1, worker_id="worker-a")
        await repository.mark_succeeded(
            job_id=first_id,
            completed_at=NOW + timedelta(seconds=5),
        )
        too_soon = await repository.claim_queued(
            now=NOW + timedelta(seconds=30),
            limit=10,
            worker_id="worker-b",
            min_gap_seconds=60,
        )
        later = await repository.claim_queued(
            now=NOW + timedelta(seconds=61),
            limit=10,
            worker_id="worker-b",
            min_gap_seconds=60,
        )

    assert [job.id for job in claimed] == [first_id]
    assert too_soon == ()
    assert [job.id for job in later] == [second_id]


@pytest.mark.anyio
async def test_browser_observation_job_repository_recovers_stale_running_job() -> None:
    session_factory = await _session_factory()
    old_lock = NOW - timedelta(minutes=30)
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job())
        await repository.claim_queued(now=old_lock, limit=10, worker_id="worker-a")
        recovered = await repository.recover_stale_running(
            now=NOW,
            stale_before=NOW - timedelta(minutes=15),
            limit=10,
        )
        queued = await repository.list_queued(now=NOW, limit=10)
        stored = await repository.get_job_by_id(JOB_ID)

    assert recovered.requeued == 1
    assert recovered.failed == 0
    assert [job.id for job in queued] == [JOB_ID]
    assert stored is not None
    assert stored.status == ObservationStatus.QUEUED
    assert stored.next_retry_at == NOW
    assert stored.locked_at is None
    assert stored.locked_by is None
    assert stored.attempts == 1


@pytest.mark.anyio
async def test_browser_observation_job_repository_tracks_runtime_status_and_waiting_since() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job())
        await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        await repository.mark_runtime_status(
            job_id=JOB_ID,
            status=ObservationStatus.WAITING_FOR_USER,
            observed_at=NOW + timedelta(seconds=5),
        )
        waiting = await repository.get_job_by_id(JOB_ID)
        await repository.mark_runtime_status(
            job_id=JOB_ID,
            status=ObservationStatus.PARSING,
            observed_at=NOW + timedelta(seconds=10),
        )
        parsing = await repository.get_job_by_id(JOB_ID)

    assert waiting is not None
    assert waiting.status == ObservationStatus.WAITING_FOR_USER
    assert waiting.waiting_since == NOW + timedelta(seconds=5)
    assert waiting.locked_at == NOW + timedelta(seconds=5)
    assert parsing is not None
    assert parsing.status == ObservationStatus.PARSING
    assert parsing.waiting_since is None
    assert parsing.locked_at == NOW + timedelta(seconds=10)


@pytest.mark.anyio
async def test_browser_observation_job_repository_records_operator_checkpoint_controls() -> None:
    session_factory = await _session_factory()
    resume_id = UUID(int=21)
    abort_id = UUID(int=22)
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job(id_value=resume_id, idempotency_key="resume"))
        await repository.add_job(_job(id_value=abort_id, idempotency_key="abort"))
        await repository.claim_queued(now=NOW, limit=10, worker_id="worker-a")
        await repository.mark_runtime_status(
            job_id=resume_id,
            status=ObservationStatus.WAITING_FOR_USER,
            observed_at=NOW + timedelta(seconds=5),
        )
        await repository.mark_runtime_status(
            job_id=abort_id,
            status=ObservationStatus.WAITING_FOR_USER,
            observed_at=NOW + timedelta(seconds=5),
        )

        resumed = await repository.request_operator_resume(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=resume_id,
            requested_at=NOW + timedelta(seconds=6),
        )
        abort_after_resume = await repository.request_operator_abort(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=resume_id,
            requested_at=NOW + timedelta(seconds=7),
        )
        aborted = await repository.request_operator_abort(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=abort_id,
            requested_at=NOW + timedelta(seconds=8),
        )
        other_user_resume = await repository.request_operator_resume(
            household_id=HOUSEHOLD_ID,
            user_id=OTHER_USER_ID,
            job_id=abort_id,
            requested_at=NOW + timedelta(seconds=9),
        )

    assert resumed is not None
    assert resumed.operator_resume_requested_at == NOW + timedelta(seconds=6)
    assert resumed.operator_abort_requested_at is None
    assert abort_after_resume is None
    assert aborted is not None
    assert aborted.operator_abort_requested_at == NOW + timedelta(seconds=8)
    assert aborted.operator_resume_requested_at is None
    assert other_user_resume is None


@pytest.mark.anyio
async def test_browser_observation_job_repository_recovers_stale_runtime_status() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job())
        await repository.claim_queued(now=NOW - timedelta(minutes=30), limit=10, worker_id="a")
        await repository.mark_runtime_status(
            job_id=JOB_ID,
            status=ObservationStatus.WAITING_FOR_USER,
            observed_at=NOW - timedelta(minutes=30),
        )
        recovered = await repository.recover_stale_running(
            now=NOW,
            stale_before=NOW - timedelta(minutes=15),
            limit=10,
        )
        stored = await repository.get_job_by_id(JOB_ID)

    assert recovered.requeued == 1
    assert stored is not None
    assert stored.status == ObservationStatus.QUEUED
    assert stored.waiting_since is None
    assert stored.next_retry_at == NOW


@pytest.mark.anyio
async def test_browser_observation_job_repository_expires_stale_running_after_deadline() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(
            _job(
                created_at=NOW - timedelta(minutes=10),
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        await repository.mark_running(
            job_id=JOB_ID,
            started_at=NOW - timedelta(minutes=5),
        )
        recovered = await repository.recover_stale_running(
            now=NOW,
            stale_before=NOW - timedelta(minutes=1),
            limit=10,
        )
        stored = await repository.get_job_by_id(JOB_ID)

    assert recovered.requeued == 0
    assert recovered.failed == 1
    assert stored is not None
    assert stored.status == ObservationStatus.EXPIRED
    assert stored.error_code == ObservationErrorCode.EXPIRED
    assert stored.next_retry_at is None
    assert stored.locked_at is None
    assert stored.locked_by is None


@pytest.mark.anyio
async def test_browser_observation_job_repository_skips_jobs_until_retry_time() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        await repository.add_job(_job(id_value=UUID(int=4), created_at=NOW))
        await repository.mark_running(job_id=UUID(int=4), started_at=NOW + timedelta(seconds=1))
        await repository.mark_retry_scheduled(
            job_id=UUID(int=4),
            attempted_at=NOW + timedelta(seconds=2),
            next_retry_at=NOW + timedelta(minutes=1),
            error_code=ObservationErrorCode.TIMED_OUT,
            error_message="browser timed out",
        )
        await session.commit()

    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        queued_now = await repository.list_queued(now=NOW + timedelta(seconds=30))
        queued_later = await repository.list_queued(now=NOW + timedelta(minutes=2))

    assert queued_now == ()
    assert [job.id for job in queued_later] == [UUID(int=4)]
    assert queued_later[0].attempts == 1
    assert queued_later[0].next_retry_at == NOW + timedelta(minutes=1)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _job(
    *,
    id_value: UUID = JOB_ID,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
    idempotency_key: str = "idem-1",
    source_id: str = "tutu",
) -> NewBrowserObservationJob:
    return NewBrowserObservationJob(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        source_id=source_id,
        search_id="sha256:search",
        search_intent_hash="sha256:intent",
        idempotency_key=idempotency_key,
        grant_id=GRANT_ID,
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        adults=1,
        children=0,
        infants=0,
        trip_type="round_trip",
        currency="RUB",
        status=ObservationStatus.QUEUED,
        created_at=created_at,
        expires_at=expires_at or (created_at + timedelta(minutes=5)),
    )
