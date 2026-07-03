from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from flight_hunter.application.live_observations import GrantSource, search_intent_fingerprint
from flight_hunter.domain.observation import (
    ObservationErrorCode,
    ObservationStatus,
    OperatorCheckpointDecision,
)
from flight_hunter.domain.offers import SearchIntent, TripType
from flight_hunter.domain.policy import UserActionGrant
from flight_hunter.domain.search_results import BrowserObservedOffer
from flight_hunter.ops.structured_logging import log_event
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRecord,
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    LiveObservationRepository,
    NewBrowserObservationJob,
)
from flight_hunter.providers.ru_clickout import default_ru_aggregator_specs
from flight_hunter.providers.ru_clickout.source_specs import RuAggregatorSpec


class PersonalObservationCode(StrEnum):
    ISSUED = "issued"
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_DISABLED = "source_disabled"
    SOURCE_NOT_OBSERVABLE = "source_not_observable"
    USER_ACTION_GRANT_REQUIRED = "user_action_grant_required"
    USER_ACTION_GRANT_CONSUMED = "user_action_grant_consumed"
    USER_ACTION_GRANT_EXPIRED = "user_action_grant_expired"
    USER_ACTION_GRANT_FINGERPRINT_MISMATCH = "user_action_grant_fingerprint_mismatch"
    USER_ACTION_GRANT_PROVIDER_MISMATCH = "user_action_grant_provider_mismatch"
    USER_ACTION_GRANT_USER_MISMATCH = "user_action_grant_user_mismatch"
    JOB_NOT_FOUND = "job_not_found"
    JOB_NOT_QUEUED = "job_not_queued"
    OPERATOR_RESUME_REQUESTED = "operator_resume_requested"
    OPERATOR_ABORT_REQUESTED = "operator_abort_requested"
    OPERATOR_CHECKPOINT_NOT_ACTIVE = "operator_checkpoint_not_active"
    OPERATOR_ABORTED = "operator_aborted"
    SOURCE_CHALLENGE = "source_challenge"
    SELECTOR_DRIFT = "selector_drift"
    PARSER_NO_OFFERS = "parser_no_offers"
    RUNNER_FAILED = "runner_failed"
    JOB_EXPIRED = "job_expired"


@dataclass(frozen=True, slots=True)
class PersonalObservationGrantDecision:
    allowed: bool
    code: PersonalObservationCode
    message: str
    grant_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class PersonalObservationCreateDecision:
    accepted: bool
    code: PersonalObservationCode
    message: str
    job_id: UUID | None
    initial_status: ObservationStatus | None
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class PersonalObservationRunDecision:
    accepted: bool
    code: PersonalObservationCode
    message: str
    job: BrowserObservationJobRecord | None
    offers_persisted: int
    retry_scheduled: bool = False


@dataclass(frozen=True, slots=True)
class PersonalObservationControlDecision:
    accepted: bool
    code: PersonalObservationCode
    message: str
    job: BrowserObservationJobRecord | None


@dataclass(frozen=True, slots=True)
class PersonalObservationRunnerResult:
    offers: tuple[BrowserObservedOffer, ...]


class PersonalObservationRunnerError(RuntimeError):
    def __init__(
        self,
        code: PersonalObservationCode,
        message: str,
        *,
        status: ObservationStatus = ObservationStatus.FAILED,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class PersonalObservationRunnerPort(Protocol):
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback: Callable[[ObservationStatus], None] | None = None,
        checkpoint_callback: Callable[[], OperatorCheckpointDecision] | None = None,
    ) -> PersonalObservationRunnerResult: ...


class PersonalObservationService:
    def __init__(
        self,
        *,
        jobs: BrowserObservationJobRepository,
        grants: LiveObservationRepository,
        observed_offers: BrowserObservedOfferRepository,
        runner: PersonalObservationRunnerPort | None = None,
        observer_enabled: bool,
        specs: Sequence[RuAggregatorSpec] | None = None,
        clock: Callable[[], datetime] | None = None,
        grant_ttl: timedelta = timedelta(minutes=5),
        result_ttl: timedelta = timedelta(minutes=5),
        max_attempts: int = 1,
        retry_delay: timedelta = timedelta(minutes=1),
        runtime_status_committer: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._jobs = jobs
        self._grants = grants
        self._observed_offers = observed_offers
        self._runner = runner
        self._observer_enabled = observer_enabled
        self._specs = tuple(specs or default_ru_aggregator_specs())
        self._spec_by_id = {spec.source_id: spec for spec in self._specs}
        self._clock = clock or (lambda: datetime.now(UTC))
        self._grant_ttl = grant_ttl
        self._result_ttl = result_ttl
        self._max_attempts = max(1, max_attempts)
        self._retry_delay = retry_delay
        self._runtime_status_committer = runtime_status_committer

    async def issue_grant(
        self,
        *,
        user_id: UUID,
        source_id: str,
        search_intent: SearchIntent,
        source: GrantSource,
    ) -> PersonalObservationGrantDecision:
        source_denial = self._validate_source(source_id)
        if source_denial is not None:
            return PersonalObservationGrantDecision(
                allowed=False,
                code=source_denial,
                message=source_denial.value,
                grant_token=None,
                expires_at=None,
            )

        now = self._clock()
        grant_id = uuid4()
        expires_at = now + self._grant_ttl
        grant = UserActionGrant(
            id=grant_id,
            user_id=user_id,
            provider_id=source_id,
            action_type="personal_observation",
            request_fingerprint=search_intent_fingerprint(search_intent),
            issued_at=now,
            expires_at=expires_at,
            source=source.value,
            consumed_at=None,
        )
        await self._grants.add_grant(grant)
        return PersonalObservationGrantDecision(
            allowed=True,
            code=PersonalObservationCode.ISSUED,
            message="personal observation grant issued",
            grant_token=str(grant_id),
            expires_at=expires_at,
        )

    async def create_job(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        source_id: str,
        search_id: str,
        search_intent: SearchIntent,
        grant_token: str,
        idempotency_key: str,
    ) -> PersonalObservationCreateDecision:
        existing = await self._jobs.get_idempotent_job_id(
            household_id=household_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            return PersonalObservationCreateDecision(
                accepted=True,
                code=PersonalObservationCode.QUEUED,
                message="idempotent personal observation request already accepted",
                job_id=existing,
                initial_status=ObservationStatus.QUEUED,
                idempotent_replay=True,
            )

        source_denial = self._validate_source(source_id)
        if source_denial is not None:
            return _create_denial(source_denial)

        grant_id = _grant_id_from_token(grant_token)
        grant = await self._grants.get_grant(user_id, grant_id) if grant_id is not None else None
        if grant is None:
            return _create_denial(PersonalObservationCode.USER_ACTION_GRANT_REQUIRED)

        fingerprint = search_intent_fingerprint(search_intent)
        grant_denial = _validate_grant(
            grant=grant,
            user_id=user_id,
            source_id=source_id,
            request_fingerprint=fingerprint,
            now=self._clock(),
        )
        if grant_denial is not None:
            return _create_denial(grant_denial)

        now = self._clock()
        consumed = await self._grants.consume_grant(grant.id, consumed_at=now)
        if not consumed:
            return _create_denial(PersonalObservationCode.USER_ACTION_GRANT_CONSUMED)

        passenger_mix = search_intent.passenger_mix
        trip_type = search_intent.trip_type
        trip_type_value = trip_type.value if isinstance(trip_type, TripType) else str(trip_type)
        job_id = uuid4()
        await self._jobs.add_job(
            NewBrowserObservationJob(
                id=job_id,
                household_id=household_id,
                user_id=user_id,
                source_id=source_id,
                search_id=search_id,
                search_intent_hash=fingerprint,
                idempotency_key=idempotency_key,
                grant_id=grant.id,
                origin=search_intent.origin,
                destination=search_intent.destination,
                departure_date=search_intent.departure_date,
                return_date=search_intent.return_date,
                passengers=search_intent.passengers,
                adults=passenger_mix.adults,
                children=passenger_mix.children,
                infants=passenger_mix.infants,
                trip_type=trip_type_value,
                currency=search_intent.currency,
                status=ObservationStatus.QUEUED,
                created_at=now,
                expires_at=now + self._result_ttl,
            )
        )
        return PersonalObservationCreateDecision(
            accepted=True,
            code=PersonalObservationCode.QUEUED,
            message="personal observation queued",
            job_id=job_id,
            initial_status=ObservationStatus.QUEUED,
        )

    async def get_job(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> BrowserObservationJobRecord | None:
        return await self._jobs.get_job(
            household_id=household_id,
            user_id=user_id,
            job_id=job_id,
        )

    async def request_operator_resume(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> PersonalObservationControlDecision:
        job = await self.get_job(household_id=household_id, user_id=user_id, job_id=job_id)
        if job is None:
            return PersonalObservationControlDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_FOUND,
                message="personal observation job not found",
                job=None,
            )
        if job.status != ObservationStatus.WAITING_FOR_USER:
            return PersonalObservationControlDecision(
                accepted=False,
                code=PersonalObservationCode.OPERATOR_CHECKPOINT_NOT_ACTIVE,
                message="personal observation is not waiting for operator input",
                job=job,
            )
        updated = await self._jobs.request_operator_resume(
            household_id=household_id,
            user_id=user_id,
            job_id=job_id,
            requested_at=self._clock(),
        )
        return PersonalObservationControlDecision(
            accepted=updated is not None,
            code=(
                PersonalObservationCode.OPERATOR_RESUME_REQUESTED
                if updated is not None
                else PersonalObservationCode.OPERATOR_CHECKPOINT_NOT_ACTIVE
            ),
            message=(
                "operator resume requested"
                if updated is not None
                else "personal observation is not waiting for operator input"
            ),
            job=updated or job,
        )

    async def request_operator_abort(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> PersonalObservationControlDecision:
        job = await self.get_job(household_id=household_id, user_id=user_id, job_id=job_id)
        if job is None:
            return PersonalObservationControlDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_FOUND,
                message="personal observation job not found",
                job=None,
            )
        if job.status != ObservationStatus.WAITING_FOR_USER:
            return PersonalObservationControlDecision(
                accepted=False,
                code=PersonalObservationCode.OPERATOR_CHECKPOINT_NOT_ACTIVE,
                message="personal observation is not waiting for operator input",
                job=job,
            )
        updated = await self._jobs.request_operator_abort(
            household_id=household_id,
            user_id=user_id,
            job_id=job_id,
            requested_at=self._clock(),
        )
        return PersonalObservationControlDecision(
            accepted=updated is not None,
            code=(
                PersonalObservationCode.OPERATOR_ABORT_REQUESTED
                if updated is not None
                else PersonalObservationCode.OPERATOR_CHECKPOINT_NOT_ACTIVE
            ),
            message=(
                "operator abort requested"
                if updated is not None
                else "personal observation is not waiting for operator input"
            ),
            job=updated or job,
        )

    async def run_job(
        self,
        *,
        job_id: UUID,
        fixture_html_path: Path | None = None,
    ) -> PersonalObservationRunDecision:
        job = await self._jobs.get_job_by_id(job_id)
        if job is None:
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_FOUND,
                message="personal observation job not found",
                job=None,
                offers_persisted=0,
            )
        if job.status != ObservationStatus.QUEUED:
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_QUEUED,
                message="personal observation job is not queued",
                job=job,
                offers_persisted=0,
            )

        now = self._clock()
        expired = await self._expire_if_deadline_passed(
            job,
            now=now,
            message="personal observation job expired before execution",
        )
        if expired is not None:
            return expired

        await self._jobs.mark_running(job_id=job.id, started_at=now)
        running_job = await self._jobs.get_job_by_id(job.id)
        if running_job is None:
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_FOUND,
                message="personal observation job not found",
                job=None,
                offers_persisted=0,
            )
        return await self.run_claimed_job(
            running_job,
            fixture_html_path=fixture_html_path,
        )

    async def run_claimed_job(
        self,
        job: BrowserObservationJobRecord,
        *,
        fixture_html_path: Path | None = None,
    ) -> PersonalObservationRunDecision:
        if job.status != ObservationStatus.RUNNING:
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.JOB_NOT_QUEUED,
                message="personal observation job is not claimed by a runner",
                job=job,
                offers_persisted=0,
            )
        now = self._clock()
        expired = await self._expire_if_deadline_passed(
            job,
            now=now,
            message="personal observation job expired before execution",
        )
        if expired is not None:
            return expired
        if self._runner is None:
            await self._jobs.mark_failed(
                job_id=job.id,
                completed_at=self._clock(),
                status=ObservationStatus.FAILED,
                error_code=ObservationErrorCode.FAILED,
                error_message="personal observation runner is not configured",
            )
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.RUNNER_FAILED,
                message="personal observation runner is not configured",
                job=await self._jobs.get_job_by_id(job.id),
                offers_persisted=0,
            )

        log_event(
            "browser_observation_started",
            source=job.source_id,
            job_id=job.id,
            search_id=job.search_id,
            attempt=job.attempts,
            fixture_mode=fixture_html_path is not None,
        )
        try:
            result = await self._observe_with_runtime_progress(
                job,
                fixture_html_path=fixture_html_path,
            )
        except PersonalObservationRunnerError as exc:
            attempted_at = self._clock()
            error_code = _error_code_for_status(exc.status)
            next_retry_at = attempted_at + self._retry_delay
            if (
                _is_retryable_status(exc.status)
                and job.attempts < self._max_attempts
                and next_retry_at < job.expires_at
            ):
                await self._jobs.mark_retry_scheduled(
                    job_id=job.id,
                    attempted_at=attempted_at,
                    next_retry_at=next_retry_at,
                    error_code=error_code,
                    error_message=exc.message,
                )
                return PersonalObservationRunDecision(
                    accepted=False,
                    code=exc.code,
                    message=exc.message,
                    job=await self._jobs.get_job_by_id(job.id),
                    offers_persisted=0,
                    retry_scheduled=True,
                )

            await self._jobs.mark_failed(
                job_id=job.id,
                completed_at=attempted_at,
                status=exc.status,
                error_code=error_code,
                error_message=exc.message,
            )
            return PersonalObservationRunDecision(
                accepted=False,
                code=exc.code,
                message=exc.message,
                job=await self._jobs.get_job_by_id(job.id),
                offers_persisted=0,
            )

        expired = await self._expire_if_deadline_passed(
            job,
            now=self._clock(),
            message="personal observation job expired before result persistence",
        )
        if expired is not None:
            return expired

        if not result.offers:
            await self._jobs.mark_failed(
                job_id=job.id,
                completed_at=self._clock(),
                status=ObservationStatus.NO_PRICE_FOUND,
                error_code=ObservationErrorCode.SELECTOR_DRIFT,
                error_message="parser did not extract any offers",
            )
            return PersonalObservationRunDecision(
                accepted=False,
                code=PersonalObservationCode.PARSER_NO_OFFERS,
                message="parser did not extract any offers",
                job=await self._jobs.get_job_by_id(job.id),
                offers_persisted=0,
            )

        for offer in result.offers:
            await self._observed_offers.add_offer(
                household_id=job.household_id,
                user_id=job.user_id,
                search_id=job.search_id,
                offer=offer,
                expires_at=offer.observed_at + self._result_ttl,
            )
        completed_at = self._clock()
        await self._jobs.mark_succeeded(job_id=job.id, completed_at=completed_at)
        return PersonalObservationRunDecision(
            accepted=True,
            code=PersonalObservationCode.SUCCEEDED,
            message="personal observation succeeded",
            job=await self._jobs.get_job_by_id(job.id),
            offers_persisted=len(result.offers),
        )

    async def _observe_with_runtime_progress(
        self,
        job: BrowserObservationJobRecord,
        *,
        fixture_html_path: Path | None,
    ) -> PersonalObservationRunnerResult:
        if self._runner is None:
            raise PersonalObservationRunnerError(
                PersonalObservationCode.RUNNER_FAILED,
                "personal observation runner is not configured",
            )
        loop = asyncio.get_running_loop()

        def mark_status(status: ObservationStatus) -> None:
            future = asyncio.run_coroutine_threadsafe(
                self._mark_runtime_status(job.id, status),
                loop,
            )
            future.result(timeout=5)

        def checkpoint_signal() -> OperatorCheckpointDecision:
            future = asyncio.run_coroutine_threadsafe(
                self._operator_checkpoint_signal(job.id),
                loop,
            )
            return future.result(timeout=5)

        return await asyncio.to_thread(
            self._runner.observe,
            source_id=job.source_id,
            intent=job.search_intent,
            user_action=True,
            fixture_html_path=fixture_html_path,
            progress_callback=mark_status,
            checkpoint_callback=checkpoint_signal,
        )

    async def _expire_if_deadline_passed(
        self,
        job: BrowserObservationJobRecord,
        *,
        now: datetime,
        message: str,
    ) -> PersonalObservationRunDecision | None:
        if job.expires_at > now:
            return None
        await self._jobs.mark_failed(
            job_id=job.id,
            completed_at=now,
            status=ObservationStatus.EXPIRED,
            error_code=ObservationErrorCode.EXPIRED,
            error_message=message,
        )
        return PersonalObservationRunDecision(
            accepted=False,
            code=PersonalObservationCode.JOB_EXPIRED,
            message=message,
            job=await self._jobs.get_job_by_id(job.id),
            offers_persisted=0,
        )

    async def _mark_runtime_status(self, job_id: UUID, status: ObservationStatus) -> None:
        await self._jobs.mark_runtime_status(
            job_id=job_id,
            status=status,
            observed_at=self._clock(),
        )
        if self._runtime_status_committer is not None:
            await self._runtime_status_committer()

    async def _operator_checkpoint_signal(self, job_id: UUID) -> OperatorCheckpointDecision:
        job = await self._jobs.get_job_by_id(job_id)
        if job is None:
            return OperatorCheckpointDecision.ABORT
        if job.operator_abort_requested_at is not None:
            return OperatorCheckpointDecision.ABORT
        if job.operator_resume_requested_at is not None:
            return OperatorCheckpointDecision.RESUME
        return OperatorCheckpointDecision.WAITING

    def _validate_source(self, source_id: str) -> PersonalObservationCode | None:
        spec = self._spec_by_id.get(source_id)
        if spec is None:
            return PersonalObservationCode.SOURCE_NOT_FOUND
        if not spec.browser_observation_allowed:
            return PersonalObservationCode.SOURCE_NOT_OBSERVABLE
        if not self._observer_enabled:
            return PersonalObservationCode.SOURCE_DISABLED
        return None


def _grant_id_from_token(token: str) -> UUID | None:
    try:
        return UUID(token)
    except ValueError:
        return None


def _validate_grant(
    *,
    grant: UserActionGrant,
    user_id: UUID,
    source_id: str,
    request_fingerprint: str,
    now: datetime,
) -> PersonalObservationCode | None:
    if grant.user_id != user_id:
        return PersonalObservationCode.USER_ACTION_GRANT_USER_MISMATCH
    if grant.provider_id != source_id:
        return PersonalObservationCode.USER_ACTION_GRANT_PROVIDER_MISMATCH
    if grant.request_fingerprint != request_fingerprint:
        return PersonalObservationCode.USER_ACTION_GRANT_FINGERPRINT_MISMATCH
    if grant.consumed_at is not None:
        return PersonalObservationCode.USER_ACTION_GRANT_CONSUMED
    if grant.is_expired(now):
        return PersonalObservationCode.USER_ACTION_GRANT_EXPIRED
    return None


def _create_denial(code: PersonalObservationCode) -> PersonalObservationCreateDecision:
    return PersonalObservationCreateDecision(
        accepted=False,
        code=code,
        message=code.value,
        job_id=None,
        initial_status=None,
    )


def _error_code_for_status(status: ObservationStatus) -> ObservationErrorCode:
    return {
        ObservationStatus.NO_PRICE_FOUND: ObservationErrorCode.SELECTOR_DRIFT,
        ObservationStatus.SOURCE_CHALLENGE: ObservationErrorCode.SOURCE_CHALLENGE,
        ObservationStatus.SELECTOR_DRIFT: ObservationErrorCode.SELECTOR_DRIFT,
        ObservationStatus.TIMED_OUT: ObservationErrorCode.TIMED_OUT,
        ObservationStatus.SOURCE_UNAVAILABLE: ObservationErrorCode.SOURCE_UNAVAILABLE,
        ObservationStatus.POLICY_DENIED: ObservationErrorCode.POLICY_DENIED,
        ObservationStatus.NEEDS_HUMAN: ObservationErrorCode.OPERATOR_ABORTED,
        ObservationStatus.EXPIRED: ObservationErrorCode.EXPIRED,
    }.get(status, ObservationErrorCode.FAILED)


def _is_retryable_status(status: ObservationStatus) -> bool:
    return status in {ObservationStatus.TIMED_OUT, ObservationStatus.SOURCE_UNAVAILABLE}
