from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.live_observations import GrantSource
from flight_hunter.application.personal_observations import (
    PersonalObservationCode,
    PersonalObservationRunnerError,
    PersonalObservationRunnerResult,
    PersonalObservationService,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.domain.offers import Freshness, SearchIntent
from flight_hunter.domain.search_results import BrowserObservedOffer, Confidence
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    LiveObservationRepository,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 6, 29, 18, 30, tzinfo=UTC)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, SearchIntent, bool, Path | None]] = []

    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        self.calls.append((source_id, intent, user_action, fixture_html_path))
        return PersonalObservationRunnerResult(offers=(_offer(source_id, intent),))


class ExpiringAfterRunner(FakeRunner):
    def __init__(self, expire: Callable[[], None]) -> None:
        super().__init__()
        self._expire = expire

    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        result = super().observe(
            source_id=source_id,
            intent=intent,
            user_action=user_action,
            fixture_html_path=fixture_html_path,
            progress_callback=progress_callback,
            checkpoint_callback=checkpoint_callback,
        )
        self._expire()
        return result


class TimeoutRunner:
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        raise PersonalObservationRunnerError(
            PersonalObservationCode.RUNNER_FAILED,
            "browser timed out",
            status=ObservationStatus.TIMED_OUT,
        )


class SourceChallengeRunner:
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        raise PersonalObservationRunnerError(
            PersonalObservationCode.SOURCE_CHALLENGE,
            "source presented a challenge page",
            status=ObservationStatus.SOURCE_CHALLENGE,
        )


class PhaseReportingRunner:
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        assert progress_callback is not None
        progress_callback(ObservationStatus.OPENING_BROWSER)
        progress_callback(ObservationStatus.WAITING_FOR_USER)
        progress_callback(ObservationStatus.CAPTURING_DOM)
        progress_callback(ObservationStatus.PARSING)
        return PersonalObservationRunnerResult(offers=(_offer(source_id, intent),))


class OperatorAbortRunner:
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ) -> PersonalObservationRunnerResult:
        raise PersonalObservationRunnerError(
            PersonalObservationCode.OPERATOR_ABORTED,
            "operator aborted the browser checkpoint",
            status=ObservationStatus.NEEDS_HUMAN,
        )


@pytest.mark.anyio
async def test_personal_observation_job_runs_and_persists_browser_offers(caplog) -> None:
    caplog.set_level(logging.INFO, logger="flight_hunter.observability")
    session_factory = await _session_factory()
    runner = FakeRunner()
    async with session_factory() as session:
        service = _service(session, runner=runner, enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-1",
        )
        await session.commit()

        assert created.accepted
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        offers = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert run.accepted
    assert run.offers_persisted == 1
    assert runner.calls[0][2] is True
    assert job is not None
    assert job.status == ObservationStatus.SUCCEEDED
    assert len(offers) == 1
    assert offers[0].freshness == Freshness.BROWSER_OBSERVED
    payload = _logged_event(caplog, "browser_observation_started")
    assert payload["source"] == "tutu"
    assert payload["job_id"] == str(created.job_id)
    assert payload["search_id"] == "sha256:search"
    assert payload["attempt"] == 1
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "grant" not in log_text.lower()
    assert "https://" not in log_text


@pytest.mark.anyio
async def test_personal_observation_runtime_phases_are_persisted_and_cleared() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(session, runner=PhaseReportingRunner(), enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-phases",
        )
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )

    assert run.accepted
    assert job is not None
    assert job.status == ObservationStatus.SUCCEEDED
    assert job.waiting_since is None
    assert job.locked_at is None


@pytest.mark.anyio
async def test_personal_observation_service_requests_operator_resume_only_while_waiting() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(session, runner=FakeRunner(), enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-control",
        )
        assert created.job_id is not None
        not_waiting = await service.request_operator_resume(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        repository = BrowserObservationJobRepository(session)
        await repository.mark_running(job_id=created.job_id, started_at=NOW + timedelta(seconds=1))
        await repository.mark_runtime_status(
            job_id=created.job_id,
            status=ObservationStatus.WAITING_FOR_USER,
            observed_at=NOW + timedelta(seconds=2),
        )
        resumed = await service.request_operator_resume(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )

    assert not_waiting.accepted is False
    assert not_waiting.code == PersonalObservationCode.OPERATOR_CHECKPOINT_NOT_ACTIVE
    assert resumed.accepted is True
    assert resumed.code == PersonalObservationCode.OPERATOR_RESUME_REQUESTED
    assert resumed.job is not None
    assert resumed.job.operator_resume_requested_at == NOW


@pytest.mark.anyio
async def test_personal_observation_create_is_idempotent_and_consumes_grant_once() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(session, runner=FakeRunner(), enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        first = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-1",
        )
        replay = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-1",
        )
        second_key = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-2",
        )

    assert replay.accepted
    assert replay.idempotent_replay
    assert replay.job_id == first.job_id
    assert second_key.code == PersonalObservationCode.USER_ACTION_GRANT_CONSUMED


@pytest.mark.anyio
async def test_personal_observation_expired_job_is_not_run() -> None:
    session_factory = await _session_factory()
    runner = FakeRunner()
    async with session_factory() as session:
        service = _service(
            session,
            runner=runner,
            enabled=True,
            result_ttl=timedelta(seconds=0),
        )
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-expired",
        )
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        offers = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert run.accepted is False
    assert run.code == PersonalObservationCode.JOB_EXPIRED
    assert runner.calls == []
    assert job is not None
    assert job.status == ObservationStatus.EXPIRED
    assert job.error_code is not None
    assert job.error_code.value == "expired"
    assert offers == ()


@pytest.mark.anyio
async def test_personal_observation_expired_claimed_job_is_not_run() -> None:
    session_factory = await _session_factory()
    runner = FakeRunner()
    async with session_factory() as session:
        service = _service(session, runner=runner, enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-expired-claimed",
        )
        assert created.job_id is not None
        repository = BrowserObservationJobRepository(session)
        await repository.mark_running(
            job_id=created.job_id,
            started_at=NOW + timedelta(seconds=1),
        )
        running_job = await repository.get_job_by_id(created.job_id)
        assert running_job is not None

        late_service = _service(
            session,
            runner=runner,
            enabled=True,
            clock=lambda: NOW + timedelta(minutes=6),
        )
        run = await late_service.run_claimed_job(running_job)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        offers = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert run.accepted is False
    assert run.code == PersonalObservationCode.JOB_EXPIRED
    assert runner.calls == []
    assert job is not None
    assert job.status == ObservationStatus.EXPIRED
    assert job.error_code is not None
    assert job.error_code.value == "expired"
    assert offers == ()


@pytest.mark.anyio
async def test_personal_observation_expiring_after_runner_does_not_persist_offers() -> None:
    session_factory = await _session_factory()
    clock_value = NOW + timedelta(seconds=2)

    def expire_job() -> None:
        nonlocal clock_value
        clock_value = NOW + timedelta(minutes=6)

    runner = ExpiringAfterRunner(expire_job)
    async with session_factory() as session:
        service = _service(session, runner=runner, enabled=True)
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-expiring-after-runner",
        )
        assert created.job_id is not None
        repository = BrowserObservationJobRepository(session)
        await repository.mark_running(
            job_id=created.job_id,
            started_at=NOW + timedelta(seconds=1),
        )
        running_job = await repository.get_job_by_id(created.job_id)
        assert running_job is not None

        service_after_claim = _service(
            session,
            runner=runner,
            enabled=True,
            clock=lambda: clock_value,
        )
        run = await service_after_claim.run_claimed_job(running_job)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        offers = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert run.accepted is False
    assert run.code == PersonalObservationCode.JOB_EXPIRED
    assert len(runner.calls) == 1
    assert job is not None
    assert job.status == ObservationStatus.EXPIRED
    assert offers == ()


@pytest.mark.anyio
async def test_personal_observation_transient_failure_schedules_retry() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(
            session,
            runner=TimeoutRunner(),
            enabled=True,
            max_attempts=2,
            retry_delay=timedelta(seconds=30),
        )
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-retry",
        )
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        job = await repository.get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )
        queued_now = await repository.list_queued(now=NOW)
        queued_later = await repository.list_queued(now=NOW + timedelta(seconds=31))

    assert run.retry_scheduled is True
    assert job is not None
    assert job.status == ObservationStatus.QUEUED
    assert job.attempts == 1
    assert job.next_retry_at == NOW + timedelta(seconds=30)
    assert queued_now == ()
    assert [queued_job.id for queued_job in queued_later] == [created.job_id]


@pytest.mark.anyio
async def test_personal_observation_source_challenge_is_not_retried() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(
            session,
            runner=SourceChallengeRunner(),
            enabled=True,
            max_attempts=3,
            retry_delay=timedelta(seconds=30),
        )
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-challenge",
        )
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )

    assert run.accepted is False
    assert run.retry_scheduled is False
    assert run.code == PersonalObservationCode.SOURCE_CHALLENGE
    assert job is not None
    assert job.status == ObservationStatus.SOURCE_CHALLENGE
    assert job.error_code is not None
    assert job.error_code.value == "source_challenge"


@pytest.mark.anyio
async def test_personal_observation_operator_abort_becomes_needs_human_without_retry() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _service(
            session,
            runner=OperatorAbortRunner(),
            enabled=True,
            max_attempts=3,
            retry_delay=timedelta(seconds=30),
        )
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="idem-abort",
        )
        assert created.job_id is not None

        run = await service.run_job(job_id=created.job_id)
        await session.commit()

    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=created.job_id,
        )

    assert run.accepted is False
    assert run.retry_scheduled is False
    assert run.code == PersonalObservationCode.OPERATOR_ABORTED
    assert job is not None
    assert job.status == ObservationStatus.NEEDS_HUMAN
    assert job.error_code is not None
    assert job.error_code.value == "operator_aborted"


@pytest.mark.anyio
async def test_personal_observation_denies_disabled_or_non_observable_source() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        disabled = _service(session, runner=FakeRunner(), enabled=False)
        disabled_grant = await disabled.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        non_observable = _service(session, runner=FakeRunner(), enabled=True)
        non_observable_grant = await non_observable.issue_grant(
            user_id=USER_ID,
            source_id="aeroflot",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )

    assert disabled_grant.code == PersonalObservationCode.SOURCE_DISABLED
    assert non_observable_grant.code == PersonalObservationCode.SOURCE_NOT_OBSERVABLE


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _service(
    session,
    *,
    runner,
    enabled: bool,
    clock: Callable[[], datetime] | None = None,
    max_attempts: int = 1,
    retry_delay: timedelta = timedelta(minutes=1),
    result_ttl: timedelta = timedelta(minutes=5),
) -> PersonalObservationService:
    return PersonalObservationService(
        jobs=BrowserObservationJobRepository(session),
        grants=LiveObservationRepository(session),
        observed_offers=BrowserObservedOfferRepository(session),
        runner=runner,
        observer_enabled=enabled,
        clock=clock or (lambda: NOW),
        result_ttl=result_ttl,
        max_attempts=max_attempts,
        retry_delay=retry_delay,
    )


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )


def _logged_event(caplog, event: str) -> dict[str, object]:
    for record in caplog.records:
        if record.name != "flight_hunter.observability":
            continue
        payload = json.loads(record.getMessage())
        if payload.get("event") == event:
            return payload
    raise AssertionError(f"missing structured log event {event}")


def _offer(source_id: str, intent: SearchIntent) -> BrowserObservedOffer:
    return BrowserObservedOffer(
        observation_id=UUID("33333333-3333-3333-3333-333333333333"),
        source_id=source_id,
        source_name="Туту",
        provider_offer_id="tutu-card-1",
        origin=intent.origin,
        destination=intent.destination,
        departure_date=intent.departure_date,
        return_date=intent.return_date,
        total_price=Money(1_842_000, "RUB"),
        passengers=intent.passengers,
        observed_at=NOW,
        final_url="https://www.tutu.ru/",
        display_url="www.tutu.ru",
        freshness=Freshness.BROWSER_OBSERVED,
        confidence=Confidence.MEDIUM,
        parser_version="fake",
        parser_warnings=(),
    )
