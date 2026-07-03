from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.deal_discovery_jobs import DealDiscoveryJobService
from flight_hunter.deals.searxng_client import SearxngClientError
from flight_hunter.deals.url_policy import DealUrlPolicyError
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.domain.search_results import Confidence, DealCandidate
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    DealCandidateRepository,
    DealDiscoveryJobRepository,
    NewDealDiscoveryJob,
    SourceHealthEventRepository,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
JOB_ID = UUID("33333333-3333-3333-3333-333333333333")
HEALTH_ID = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_deal_discovery_job_service_persists_candidates_and_marks_succeeded() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        jobs = DealDiscoveryJobRepository(session)
        await jobs.enqueue_job(_job())
        service = _service(
            session,
            discovery=SuccessfulDiscovery(),
            id_factory=lambda: HEALTH_ID,
        )

        summary = await service.run_once(
            limit=5,
            retry_delay=timedelta(minutes=1),
            worker_id="worker-a",
        )
        stored = await jobs.get_job(JOB_ID)
        candidates = await DealCandidateRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )
        health = await SourceHealthEventRepository(session).list_recent(source_id="deal_discovery")

    assert summary.jobs_processed == 1
    assert summary.jobs_succeeded == 1
    assert summary.candidates_saved == 1
    assert summary.health_events_recorded == 1
    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.result_count == 1
    assert len(candidates) == 1
    assert candidates[0].expires_at == NOW + timedelta(hours=2)
    assert health[0].status == "ok"
    assert health[0].event_type == "deal_discovery_job"


@pytest.mark.anyio
async def test_deal_discovery_job_service_schedules_retry_for_source_error() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        jobs = DealDiscoveryJobRepository(session)
        await jobs.enqueue_job(_job())
        service = _service(session, discovery=FailingDiscovery(SearxngClientError("boom")))

        summary = await service.run_once(
            limit=5,
            retry_delay=timedelta(minutes=3),
            worker_id="worker-a",
        )
        stored = await jobs.get_job(JOB_ID)
        health = await SourceHealthEventRepository(session).list_recent(source_id="deal_discovery")

    assert summary.jobs_processed == 1
    assert summary.jobs_retry_scheduled == 1
    assert stored is not None
    assert stored.status == "retry_scheduled"
    assert stored.next_retry_at == NOW + timedelta(minutes=3)
    assert stored.error_code == "deal_discovery_source_failed"
    assert "boom" not in (stored.error_message or "")
    assert health[0].status == "retry_scheduled"
    assert health[0].cooldown_until == NOW + timedelta(minutes=3)


@pytest.mark.anyio
async def test_deal_discovery_job_service_fails_unsafe_url_without_retry() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        jobs = DealDiscoveryJobRepository(session)
        await jobs.enqueue_job(_job())
        service = _service(
            session,
            discovery=FailingDiscovery(DealUrlPolicyError("deal_url_blocked_ip")),
        )

        summary = await service.run_once(
            limit=5,
            retry_delay=timedelta(minutes=1),
            worker_id="worker-a",
        )
        stored = await jobs.get_job(JOB_ID)

    assert summary.jobs_processed == 1
    assert summary.jobs_failed == 1
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "deal_discovery_url_rejected"
    assert stored.next_retry_at is None


@pytest.mark.anyio
async def test_deal_discovery_job_service_fails_when_disabled() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        jobs = DealDiscoveryJobRepository(session)
        await jobs.enqueue_job(_job())
        service = _service(session, discovery=None)

        summary = await service.run_once(
            limit=5,
            retry_delay=timedelta(minutes=1),
            worker_id="worker-a",
        )
        stored = await jobs.get_job(JOB_ID)

    assert summary.jobs_processed == 1
    assert summary.jobs_failed == 1
    assert stored is not None
    assert stored.status == "failed"
    assert stored.error_code == "deal_discovery_disabled"


class SuccessfulDiscovery:
    async def discover(self, intent: SearchIntent, *, limit: int = 5) -> tuple[DealCandidate, ...]:
        assert intent.origin == "MOW"
        return (
            DealCandidate(
                source_id="deal_discovery",
                url="https://example.com/deal?utm_source=feed",
                title="MOW IST sale",
                summary_ru="Manual verification required.",
                extracted_price=Money(18_420_00, "RUB"),
                extracted_origin="MOW",
                extracted_destination="IST",
                extracted_date_window="2026-09-10 - 2026-09-20",
                confidence=Confidence.MEDIUM,
                discovered_at=NOW,
                requires_manual_verification=True,
            ),
        )


class FailingDiscovery:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def discover(self, intent: SearchIntent, *, limit: int = 5) -> tuple[DealCandidate, ...]:
        raise self._exc


def _service(
    session,
    *,
    discovery,
    id_factory=lambda: UUID("55555555-5555-5555-5555-555555555555"),
) -> DealDiscoveryJobService:
    return DealDiscoveryJobService(
        jobs=DealDiscoveryJobRepository(session),
        candidates=DealCandidateRepository(session),
        source_health_events=SourceHealthEventRepository(session),
        discovery=discovery,
        clock=lambda: NOW,
        id_factory=id_factory,
        candidate_ttl=timedelta(hours=2),
    )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _job() -> NewDealDiscoveryJob:
    return NewDealDiscoveryJob(
        id=JOB_ID,
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        search_id="sha256:search",
        idempotency_key="deal-discovery:1",
        status="queued",
        attempts=0,
        max_attempts=3,
        deadline_at=NOW + timedelta(minutes=15),
        created_at=NOW - timedelta(minutes=1),
        search_intent_json=(
            '{"origin":"MOW","destination":"IST","departure_date":"2026-09-10",'
            '"return_date":"2026-09-20","passengers":1,"currency":"RUB"}'
        ),
        limit=3,
    )
