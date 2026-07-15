from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.application.agent_operations import (
    OperationScheduler,
    OperationSpec,
    ProviderFailureClass,
    retry_decision,
)
from flight_hunter.domain.agent_evidence import ConfirmedOfferEvidence, DiscoverySignal
from flight_hunter.domain.agent_search import DateConstraint, DateMode, LocationScopeKind, TripShape
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentConfirmedOfferEvidenceRecord,
    AgentDiscoverySignalRecord,
    AgentEvidenceRepository,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentOperationStatus,
    AgentPlanConflict,
    AgentPlanRepository,
    AgentPlanRunRecord,
    AgentPlanStageKind,
    AgentPlanStageRecord,
    AgentRankingSnapshotRecord,
    AgentRunOperationRecord,
    AgentRunRepository,
    AgentStageStatus,
    AttemptKind,
    AttemptReservationStatus,
    CircuitPermitStatus,
    NewAgentConfirmedOfferEvidence,
    NewAgentDiscoverySignal,
    NewAgentPlanStage,
    NewAgentRankingSnapshot,
    ServerPrivateOperationLease,
)
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchHttpStatusError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    AviasalesSearchTransportError,
    AviasalesTripClass,
    SearchStartParams,
)
from flight_hunter.providers.aviasales_search.gateway import (
    AviasalesSearchCapabilityError,
    AviasalesSearchPolicyDenied,
    CalendarSearchParams,
    ExactPollOutcome,
    ExactSearchContinuation,
)
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

_PROVIDER_ID = "aviasales_search"
_TERMINAL_RUN_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
_ACTIVE_OPERATION_STATUSES = frozenset(
    {
        AgentOperationStatus.PENDING,
        AgentOperationStatus.LEASED,
        AgentOperationStatus.RETRY_WAIT,
    }
)


class AgentSearchGateway(Protocol):
    async def start_exact(
        self,
        params: SearchStartParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
    ) -> ExactSearchContinuation: ...

    async def poll_exact_once(
        self,
        continuation: ExactSearchContinuation,
        *,
        request_fingerprint: str,
    ) -> ExactPollOutcome: ...

    async def calendar(
        self,
        params: CalendarSearchParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
    ) -> tuple[DiscoverySignal, ...]: ...


class AgentExecutionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AgentExecutionPolicy:
    provider_rpm: int
    operation_lease_seconds: int
    circuit_failure_threshold: int
    circuit_cooldown_seconds: int
    circuit_probe_lease_seconds: int
    candidate_page_size: int = 100
    poll_interval_seconds: int = 2

    def __post_init__(self) -> None:
        for field_name in (
            "provider_rpm",
            "operation_lease_seconds",
            "circuit_failure_threshold",
            "circuit_cooldown_seconds",
            "circuit_probe_lease_seconds",
            "candidate_page_size",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if type(self.poll_interval_seconds) is not int or self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class AgentExecutionStep:
    operation_claimed: bool
    operation_status: str | None
    run_status: str | None


@dataclass(frozen=True, slots=True)
class _Workflow:
    origin: str
    destination: str
    date_mode: str
    departure_date: date
    departure_end_date: date
    return_date: date | None
    adults: int
    children: int
    infants: int
    currency: str
    one_way: bool
    exact_limit: int
    calendar_limit: int
    start_attempts: int
    poll_rounds: int
    attempts_per_poll: int
    approved_provider_rpm: int

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants


@dataclass(frozen=True, slots=True)
class _ExactBinding:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    adults: int
    children: int
    infants: int
    passengers: int
    currency: str


@dataclass(frozen=True, slots=True)
class _Failure:
    classification: ProviderFailureClass | None
    error_code: str
    retry_after: datetime | None
    transient: bool


class AgentExecutionService:
    """Durable orchestration over the provider-neutral Task 7 execution ledger."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        gateway: AgentSearchGateway,
        worker_id: str,
        policy: AgentExecutionPolicy,
        durability_checkpoint: Callable[[], Awaitable[None]],
        clock: Callable[[], datetime] | None = None,
        provider_preflight: Callable[[], None] | None = None,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        self._session = session
        self._gateway = gateway
        self._worker_id = worker_id
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))
        self._durability_checkpoint = durability_checkpoint
        self._provider_preflight = provider_preflight
        self._runs = AgentRunRepository(session)
        self._plans = AgentPlanRepository(session)
        self._operations = AgentOperationRepository(session)
        self._scheduler = OperationScheduler(self._operations)
        self._evidence = AgentEvidenceRepository(session)

    async def run_next(self) -> AgentExecutionStep:
        """Process at most one leased operation across household-scoped active runs."""

        after: AgentPlanRunRecord | None = None
        while True:
            candidates = await self._runs.list_execution_candidates(
                limit=self._policy.candidate_page_size,
                after=after,
            )
            if not candidates:
                break
            for run in candidates:
                step = await self.run_step(household_id=run.household_id, run_id=run.id)
                if step.operation_claimed or step.run_status in _TERMINAL_RUN_STATUSES:
                    return step
            after = candidates[-1]
            if len(candidates) < self._policy.candidate_page_size:
                break
        return AgentExecutionStep(False, None, None)

    async def run_step(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
    ) -> AgentExecutionStep:
        now = self._now()
        run = await self._runs.get_run(household_id, run_id)
        if run is None:
            raise AgentExecutionError("agent_run_not_found")
        if run.status in _TERMINAL_RUN_STATUSES:
            return AgentExecutionStep(False, None, run.status)

        if run.status == "cancel_requested":
            return await self._finish_cancel_requested(run, now)
        if now >= run.deadline_at:
            return await self._finish_deadline(run, now)

        if run.status == "queued":
            try:
                run = await self._runs.set_status(
                    household_id=run.household_id,
                    run_id=run.id,
                    status="running",
                    changed_at=now,
                )
            except AgentPlanConflict as error:
                if error.code != "agent_run_transition_conflict":
                    raise
                current = await self._runs.get_run(run.household_id, run.id)
                if current is None:
                    raise AgentExecutionError("agent_run_not_found") from error
                if current.status in _TERMINAL_RUN_STATUSES:
                    return AgentExecutionStep(False, None, current.status)
                if current.status != "running":
                    return AgentExecutionStep(False, None, current.status)
                run = current

        try:
            await self._ensure_initial_operation(run, now)
        except AgentExecutionError as error:
            failed = await self._runs.set_status(
                household_id=run.household_id,
                run_id=run.id,
                status="failed",
                changed_at=now,
                error_code=error.code,
            )
            return AgentExecutionStep(False, None, failed.status)
        lease = await self._operations.claim_next_operation(
            household_id=run.household_id,
            run_id=run.id,
            worker_id=self._worker_id,
            now=now,
            lease_seconds=self._policy.operation_lease_seconds,
        )
        if lease is None:
            terminal = await self._advance_workflow(run, now)
            return AgentExecutionStep(False, None, terminal.status if terminal else run.status)

        if lease.operation.kind in {
            AgentOperationKind.CALENDAR_SEARCH,
            AgentOperationKind.EXACT_START,
            AgentOperationKind.EXACT_POLL,
        }:
            status = await self._run_network_operation(run, lease, now)
        else:
            status = await self._run_local_operation(run, lease, now)
        post_operation_now = self._now()
        await self._refresh_stage_statuses(run, post_operation_now)
        terminal = await self._advance_workflow(run, post_operation_now)
        return AgentExecutionStep(
            True,
            status.value,
            terminal.status if terminal is not None else "running",
        )

    async def _finish_cancel_requested(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentExecutionStep:
        await self._operations.claim_next_operation(
            household_id=run.household_id,
            run_id=run.id,
            worker_id=self._worker_id,
            now=now,
            lease_seconds=self._policy.operation_lease_seconds,
        )
        await self._refresh_stage_statuses(run, now)
        operations = await self._operations.list_operations(run.household_id, run.id)
        if any(operation.status in _ACTIVE_OPERATION_STATUSES for operation in operations):
            return AgentExecutionStep(False, None, "cancel_requested")
        cancelled = await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status="cancelled",
            changed_at=now,
        )
        return AgentExecutionStep(False, None, cancelled.status)

    async def _finish_deadline(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentExecutionStep:
        if run.status == "queued":
            run = await self._runs.set_status(
                household_id=run.household_id,
                run_id=run.id,
                status="running",
                changed_at=now,
            )
        await self._operations.claim_next_operation(
            household_id=run.household_id,
            run_id=run.id,
            worker_id=self._worker_id,
            now=now,
            lease_seconds=self._policy.operation_lease_seconds,
        )
        await self._refresh_stage_statuses(run, now)
        operations = await self._operations.list_operations(run.household_id, run.id)
        if any(operation.status in _ACTIVE_OPERATION_STATUSES for operation in operations):
            return AgentExecutionStep(False, None, run.status)
        confirmed = await self._evidence.list_confirmed_evidence(run.household_id, run.id)
        terminal_status: Literal["partial", "failed"] = "partial" if confirmed else "failed"
        error_code = "agent_run_partial" if confirmed else "agent_run_deadline_exceeded"
        failed = await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status=terminal_status,
            changed_at=now,
            error_code=error_code,
        )
        return AgentExecutionStep(False, None, failed.status)

    async def _ensure_initial_operation(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> None:
        if await self._operations.list_operations(run.household_id, run.id):
            return
        workflow = await self._workflow(run)
        if workflow.date_mode == "exact":
            stage = await self._stage(
                run,
                AgentPlanStageKind.EXACT_SEARCH,
                prefix=0x02,
                now=now,
            )
            await self._materialize_exact_start(
                run,
                stage.id,
                workflow,
                departure_date=workflow.departure_date,
                return_date=workflow.return_date,
                ordinal=0,
                now=now,
            )
            return
        stage = await self._stage(
            run,
            AgentPlanStageKind.CALENDAR_DISCOVERY,
            prefix=0x01,
            now=now,
        )
        immutable_input = {
            "origin": workflow.origin,
            "destination": workflow.destination,
            "departure_date": workflow.departure_date.isoformat(),
            "return_date": workflow.return_date.isoformat() if workflow.return_date else None,
            "passengers": workflow.passengers,
            "currency": workflow.currency,
            "phase": "calendar",
        }
        await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0x10, "calendar"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=_PROVIDER_ID,
                kind=AgentOperationKind.CALENDAR_SEARCH,
                immutable_input=immutable_input,
                logical_workflow_input={
                    key: value for key, value in immutable_input.items() if key != "phase"
                },
                consumes_logical_unit=True,
                private_continuation=None,
                max_attempts=workflow.start_attempts,
                created_at=now,
            )
        )

    async def _run_network_operation(
        self,
        run: AgentPlanRunRecord,
        lease: ServerPrivateOperationLease,
        now: datetime,
    ) -> AgentOperationStatus:
        current = await self._runs.get_run(run.household_id, run.id)
        if current is None:
            raise AgentExecutionError("agent_run_not_found")
        inactive_code = _inactive_code(current, now)
        if inactive_code is not None:
            skipped = await self._operations.mark_claimed_operation_skipped(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                error_code=inactive_code,
                now=now,
            )
            return skipped.status

        try:
            workflow = await self._validate_dispatch_input(lease)
        except AgentExecutionError as error:
            failed = await self._operations.mark_operation_failed(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                error_code=error.code,
                now=now,
            )
            return failed.status

        if self._provider_preflight is not None:
            try:
                self._provider_preflight()
            except (AviasalesSearchCapabilityError, AviasalesSearchPolicyDenied) as error:
                return await self._persist_failure(
                    lease.operation,
                    _classify_failure(error, now),
                    now,
                )

        permit_result = await self._operations.acquire_circuit_permit(
            household_id=run.household_id,
            run_id=run.id,
            operation_id=lease.operation.id,
            provider_id=_PROVIDER_ID,
            worker_id=self._worker_id,
            now=now,
            probe_lease_seconds=self._policy.circuit_probe_lease_seconds,
        )
        if permit_result.status is CircuitPermitStatus.OPEN:
            if lease.operation.attempt_count >= lease.operation.max_attempts:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_circuit_open",
                    now=now,
                )
                return failed.status
            retry_at = cast(datetime, permit_result.retry_at)
            waiting = await self._operations.schedule_retry(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                next_retry_at=retry_at,
                error_code="agent_circuit_open",
                now=now,
            )
            return waiting.status

        permit = permit_result.permit
        if permit is None:
            raise RuntimeError("allowed circuit response omitted its private permit")
        reservation = await self._operations.reserve_http_attempt(
            household_id=run.household_id,
            run_id=run.id,
            operation_id=lease.operation.id,
            worker_id=self._worker_id,
            provider_id=_PROVIDER_ID,
            attempt_kind=_attempt_kind(lease.operation),
            provider_rpm=min(
                self._policy.provider_rpm,
                workflow.approved_provider_rpm,
            ),
            now=now,
            circuit_permit=permit,
        )
        if reservation.status is AttemptReservationStatus.RATE_LIMITED:
            await self._operations.abandon_circuit_permit(
                household_id=run.household_id,
                run_id=run.id,
                worker_id=self._worker_id,
                circuit_permit=permit,
                now=now,
            )
            retry_at = cast(datetime, reservation.retry_at)
            if lease.operation.attempt_count >= lease.operation.max_attempts:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_provider_rate_wait",
                    now=now,
                )
                return failed.status
            waiting = await self._operations.schedule_retry(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                next_retry_at=retry_at,
                error_code="agent_provider_rate_wait",
                now=now,
            )
            return waiting.status
        if reservation.status is AttemptReservationStatus.BUDGET_EXHAUSTED:
            await self._operations.abandon_circuit_permit(
                household_id=run.household_id,
                run_id=run.id,
                worker_id=self._worker_id,
                circuit_permit=permit,
                now=now,
            )
            failed = await self._operations.mark_operation_failed(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                error_code="agent_http_budget_exhausted",
                now=now,
            )
            return failed.status
        reservation_id = reservation.reservation_id
        if reservation_id is None:
            raise RuntimeError("reserved provider attempt omitted its identity")
        await self._durability_checkpoint()

        try:
            outcome = await self._dispatch_provider(lease)
        except (
            AviasalesSearchAuthFailed,
            AviasalesSearchBlocked,
            AviasalesSearchSchemaError,
            AviasalesSearchRateLimited,
            AviasalesSearchTransportError,
            AviasalesSearchHttpStatusError,
            AviasalesSearchCapabilityError,
            AviasalesSearchPolicyDenied,
        ) as error:
            response_now = self._now()
            failure = _classify_failure(error, response_now)
            await self._operations.record_circuit_failure(
                circuit_permit=permit,
                reservation_id=reservation_id,
                transient=failure.transient,
                failure_threshold=self._policy.circuit_failure_threshold,
                cooldown_seconds=self._policy.circuit_cooldown_seconds,
                now=response_now,
            )
            if not _lease_active_at(lease.operation, response_now):
                return AgentOperationStatus.LEASED
            return await self._persist_failure(lease.operation, failure, response_now)

        response_now = self._now()
        await self._operations.record_circuit_success(
            circuit_permit=permit,
            reservation_id=reservation_id,
            now=response_now,
        )
        if not _lease_active_at(lease.operation, response_now):
            return AgentOperationStatus.LEASED
        return await self._persist_provider_outcome(run, lease, outcome, response_now)

    async def _validate_dispatch_input(self, lease: ServerPrivateOperationLease) -> _Workflow:
        operation = lease.operation
        workflow = await self._workflow_for_ids(operation.household_id, operation.run_id)
        validation_error = AgentExecutionError("agent_operation_input_invalid")
        try:
            if operation.kind is AgentOperationKind.EXACT_START:
                binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
                if operation.immutable_input.get("phase") != "start":
                    raise AgentExecutionError("agent_operation_input_invalid")
                _start_params(operation.immutable_input, workflow)
                if binding.passengers != workflow.passengers:
                    raise AgentExecutionError("agent_operation_input_invalid")
                return workflow
            if operation.kind is AgentOperationKind.EXACT_POLL:
                await self._validate_poll_binding(lease, workflow)
                return workflow
            if operation.kind is AgentOperationKind.CALENDAR_SEARCH:
                CalendarSearchParams(
                    origin=ProviderLocation(LocationScopeKind.AIRPORT, workflow.origin),
                    destination=ProviderLocation(
                        LocationScopeKind.AIRPORT,
                        workflow.destination,
                    ),
                    depart_from=workflow.departure_date,
                    depart_to=workflow.departure_end_date,
                    one_way=workflow.one_way,
                    currency=workflow.currency,
                    adults=1,
                    children=0,
                    infants=0,
                )
                return workflow
        except (KeyError, TypeError, ValueError):
            validation_error = AgentExecutionError("agent_operation_input_invalid")
        raise validation_error

    async def _validate_poll_binding(
        self,
        lease: ServerPrivateOperationLease,
        workflow: _Workflow,
    ) -> None:
        operation = lease.operation
        binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
        if operation.immutable_input.get("phase") != "poll":
            raise AgentExecutionError("agent_operation_input_invalid")
        continuation = _continuation_from_private(lease.private_continuation)
        poll_round = _private_positive_int(lease.private_continuation, "poll_round")
        immutable_round = _positive_int(operation.immutable_input.get("poll_round"), "poll_round")
        root_id = operation.logical_root_operation_id
        if root_id is None:
            raise AgentExecutionError("agent_operation_input_invalid")
        root = await self._operations.get_operation(operation.household_id, root_id)
        if (
            root is None
            or root.run_id != operation.run_id
            or root.stage_id != operation.stage_id
            or root.kind is not AgentOperationKind.EXACT_START
            or root.immutable_input.get("phase") != "start"
        ):
            raise AgentExecutionError("agent_operation_input_invalid")
        root_binding = _exact_binding_from_immutable(root.immutable_input, workflow)
        if (
            root_binding != binding
            or continuation.evidence_namespace != root.id
            or continuation.expected_origin != binding.origin
            or continuation.expected_destination != binding.destination
            or continuation.expected_departure_date != binding.departure_date
            or continuation.expected_return_date != binding.return_date
            or continuation.expected_currency != binding.currency
            or continuation.passengers != binding.passengers
            or poll_round != immutable_round
        ):
            raise AgentExecutionError("agent_operation_input_invalid")

    async def _dispatch_provider(
        self,
        lease: ServerPrivateOperationLease,
    ) -> ExactSearchContinuation | ExactPollOutcome | tuple[DiscoverySignal, ...]:
        operation = lease.operation
        workflow = await self._workflow_for_ids(operation.household_id, operation.run_id)
        if operation.kind is AgentOperationKind.EXACT_START:
            return await self._gateway.start_exact(
                _start_params(operation.immutable_input, workflow),
                evidence_namespace=operation.id,
                request_fingerprint=operation.operation_fingerprint,
            )
        if operation.kind is AgentOperationKind.EXACT_POLL:
            continuation = _continuation_from_private(lease.private_continuation)
            return await self._gateway.poll_exact_once(
                continuation,
                request_fingerprint=operation.operation_fingerprint,
            )
        if operation.kind is AgentOperationKind.CALENDAR_SEARCH:
            return await self._gateway.calendar(
                CalendarSearchParams(
                    origin=ProviderLocation(LocationScopeKind.AIRPORT, workflow.origin),
                    destination=ProviderLocation(
                        LocationScopeKind.AIRPORT,
                        workflow.destination,
                    ),
                    depart_from=workflow.departure_date,
                    depart_to=workflow.departure_end_date,
                    one_way=workflow.one_way,
                    currency=workflow.currency,
                    adults=1,
                    children=0,
                    infants=0,
                ),
                evidence_namespace=operation.id,
                request_fingerprint=operation.operation_fingerprint,
            )
        raise AgentExecutionError("agent_operation_kind_unsupported")

    async def _persist_provider_outcome(
        self,
        run: AgentPlanRunRecord,
        lease: ServerPrivateOperationLease,
        outcome: ExactSearchContinuation | ExactPollOutcome | tuple[DiscoverySignal, ...],
        now: datetime,
    ) -> AgentOperationStatus:
        operation = lease.operation
        if operation.kind is AgentOperationKind.CALENDAR_SEARCH:
            signals = cast(tuple[DiscoverySignal, ...], outcome)
            if not signals:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_no_discovery_results",
                    now=now,
                )
                return failed.status
            stored_signals = tuple(
                [await self._append_discovery(run, operation, signal, now) for signal in signals]
            )
            await self._materialize_shortlist(run, stored_signals, now)
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.DISCOVERY_SIGNAL,
                result_id=stored_signals[0].id,
                now=now,
            )
            return succeeded.status

        if operation.kind is AgentOperationKind.EXACT_START:
            continuation = cast(ExactSearchContinuation, outcome)
            poll = await self._materialize_poll(
                run,
                root=operation,
                predecessor=operation,
                continuation=continuation,
                poll_round=1,
                now=now,
            )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.OPERATION,
                result_id=poll.id,
                now=now,
            )
            await self._defer_poll(poll, now)
            return succeeded.status

        poll_outcome = cast(ExactPollOutcome, outcome)
        if poll_outcome.evidence:
            stored_evidence = tuple(
                [
                    await self._append_confirmed(run, operation, evidence, now)
                    for evidence in poll_outcome.evidence
                ]
            )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.CONFIRMED_OFFER,
                result_id=stored_evidence[0].id,
                now=now,
            )
            return succeeded.status

        workflow = await self._workflow(run)
        continuation = _continuation_from_private(lease.private_continuation)
        poll_round = _private_positive_int(lease.private_continuation, "poll_round")
        if not poll_outcome.complete and poll_round < workflow.poll_rounds:
            next_continuation = ExactSearchContinuation(
                search_id=continuation.search_id,
                results_url=continuation.results_url,
                last_update_timestamp=poll_outcome.next_cursor,
                request_id=continuation.request_id,
                evidence_namespace=continuation.evidence_namespace,
                expected_origin=continuation.expected_origin,
                expected_destination=continuation.expected_destination,
                expected_departure_date=continuation.expected_departure_date,
                expected_return_date=continuation.expected_return_date,
                expected_currency=continuation.expected_currency,
                passengers=continuation.passengers,
            )
            root = await self._required_root(operation)
            next_poll = await self._materialize_poll(
                run,
                root=root,
                predecessor=operation,
                continuation=next_continuation,
                poll_round=poll_round + 1,
                now=now,
            )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.OPERATION,
                result_id=next_poll.id,
                now=now,
            )
            await self._defer_poll(next_poll, now)
            return succeeded.status

        failed = await self._operations.mark_operation_failed(
            household_id=run.household_id,
            operation_id=operation.id,
            worker_id=self._worker_id,
            error_code="agent_no_confirmed_offer",
            now=now,
        )
        return failed.status

    async def _persist_failure(
        self,
        operation: AgentRunOperationRecord,
        failure: _Failure,
        now: datetime,
    ) -> AgentOperationStatus:
        if failure.classification is None:
            failed = await self._operations.mark_operation_failed(
                household_id=operation.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                error_code=failure.error_code,
                now=now,
            )
            return failed.status
        decision = retry_decision(
            failure_class=failure.classification,
            attempt_count=operation.attempt_count,
            max_attempts=operation.max_attempts,
            now=now,
            retry_after=failure.retry_after,
        )
        if decision.status is AgentOperationStatus.RETRY_WAIT:
            waiting = await self._operations.schedule_retry(
                household_id=operation.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                next_retry_at=cast(datetime, decision.next_retry_at),
                error_code=decision.error_code,
                now=now,
            )
            return waiting.status
        failed = await self._operations.mark_operation_failed(
            household_id=operation.household_id,
            operation_id=operation.id,
            worker_id=self._worker_id,
            error_code=decision.error_code,
            now=now,
        )
        return failed.status

    async def _run_local_operation(
        self,
        run: AgentPlanRunRecord,
        lease: ServerPrivateOperationLease,
        now: datetime,
    ) -> AgentOperationStatus:
        operation = lease.operation
        if operation.kind is AgentOperationKind.RANKING:
            ranking = await self._create_minimal_ranking(run, now)
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.RANKING_SNAPSHOT,
                result_id=ranking.id,
                now=now,
            )
            return succeeded.status
        if operation.kind is AgentOperationKind.ANALYSIS:
            ranking_id = await self._ranking_result_id(run)
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.RANKING_SNAPSHOT,
                result_id=ranking_id,
                now=now,
            )
            return succeeded.status
        raise AgentExecutionError("agent_operation_kind_unsupported")

    async def _advance_workflow(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentPlanRunRecord | None:
        current = await self._runs.get_run(run.household_id, run.id)
        if current is None:
            raise AgentExecutionError("agent_run_not_found")
        if current.status in _TERMINAL_RUN_STATUSES:
            return current
        if current.status == "cancel_requested":
            step = await self._finish_cancel_requested(current, now)
            if step.run_status == "cancelled":
                return await self._runs.get_run(run.household_id, run.id)
            return None
        if now >= current.deadline_at:
            step = await self._finish_deadline(current, now)
            if step.run_status in _TERMINAL_RUN_STATUSES:
                return await self._runs.get_run(run.household_id, run.id)
            return None

        operations = await self._operations.list_operations(run.household_id, run.id)
        if any(operation.status in _ACTIVE_OPERATION_STATUSES for operation in operations):
            return None
        confirmed = await self._evidence.list_confirmed_evidence(run.household_id, run.id)
        if confirmed:
            ranking_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.RANKING
            )
            if not ranking_operations:
                await self._materialize_ranking(run, now)
                return None
            ranking = ranking_operations[0]
            if ranking.status is not AgentOperationStatus.SUCCEEDED:
                return await self._finish_from_failures(run, operations, confirmed, now)
            analysis_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.ANALYSIS
            )
            if not analysis_operations:
                await self._materialize_analysis(run, now)
                return None
            if analysis_operations[0].status is not AgentOperationStatus.SUCCEEDED:
                return await self._finish_from_failures(run, operations, confirmed, now)
            return await self._finish_from_failures(run, operations, confirmed, now)
        return await self._finish_from_failures(run, operations, confirmed, now)

    async def _finish_from_failures(
        self,
        run: AgentPlanRunRecord,
        operations: Sequence[AgentRunOperationRecord],
        confirmed: Sequence[AgentConfirmedOfferEvidenceRecord],
        now: datetime,
    ) -> AgentPlanRunRecord:
        if any(operation.status in _ACTIVE_OPERATION_STATUSES for operation in operations):
            raise AgentExecutionError("agent_run_active_operations")
        failed = tuple(
            operation for operation in operations if operation.status is AgentOperationStatus.FAILED
        )
        if confirmed:
            if failed:
                return await self._runs.set_status(
                    household_id=run.household_id,
                    run_id=run.id,
                    status="partial",
                    changed_at=now,
                    error_code="agent_run_partial",
                )
            return await self._runs.set_status(
                household_id=run.household_id,
                run_id=run.id,
                status="completed",
                changed_at=now,
            )
        error_code = next(
            (operation.error_code for operation in failed if operation.error_code is not None),
            "agent_no_confirmed_offer",
        )
        return await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status="failed",
            changed_at=now,
            error_code=error_code,
        )

    async def _append_discovery(
        self,
        run: AgentPlanRunRecord,
        operation: AgentRunOperationRecord,
        signal: DiscoverySignal,
        now: datetime,
    ) -> AgentDiscoverySignalRecord:
        return await self._evidence.append_discovery_signal(
            NewAgentDiscoverySignal(
                id=signal.id,
                household_id=run.household_id,
                run_id=run.id,
                stage_id=operation.stage_id,
                provider_id=signal.provider_id,
                origin=signal.origin,
                destination=signal.destination,
                departure_date=signal.departure_date,
                return_date=signal.return_date,
                amount_minor=signal.observed_amount.minor_units,
                currency=signal.observed_amount.currency,
                passengers=signal.passengers,
                passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
                source_kind=signal.source_kind,
                freshness=Freshness.LIVE,
                observed_at=signal.observed_at,
                signal_evidence={"calendar_bucket": signal.departure_date.strftime("%Y-%m")},
                fingerprint=_evidence_fingerprint(signal.id),
                created_at=max(now, signal.observed_at),
            )
        )

    async def _append_confirmed(
        self,
        run: AgentPlanRunRecord,
        operation: AgentRunOperationRecord,
        evidence: ConfirmedOfferEvidence,
        now: datetime,
    ) -> AgentConfirmedOfferEvidenceRecord:
        return await self._evidence.append_confirmed_evidence(
            NewAgentConfirmedOfferEvidence(
                id=evidence.id,
                household_id=run.household_id,
                run_id=run.id,
                stage_id=operation.stage_id,
                provider_id=evidence.provider_id,
                source="exact_search",
                observed_at=evidence.observed_at,
                freshness=Freshness.LIVE,
                passengers=evidence.passengers,
                passenger_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
                amount_minor=evidence.total_amount.minor_units,
                currency=evidence.total_amount.currency,
                itinerary_evidence={
                    "origin": evidence.origin,
                    "destination": evidence.destination,
                    "segments": [
                        {
                            "origin": segment.origin,
                            "destination": segment.destination,
                            "depart_at": segment.depart_at,
                            "arrive_at": segment.arrive_at,
                            "carrier": segment.airline_code,
                            "flight_number": segment.flight_number,
                        }
                        for segment in evidence.segments
                    ],
                    "seller": evidence.seller_name,
                    "ticket_structure": "provider_ticket",
                    "stops": max(0, len(evidence.segments) - 1),
                },
                protection_status=evidence.protection_status,
                baggage_status=None,
                transfer_status=None,
                visa_status=None,
                fingerprint=_evidence_fingerprint(evidence.id),
                created_at=max(now, evidence.observed_at),
            )
        )

    async def _materialize_shortlist(
        self,
        run: AgentPlanRunRecord,
        signals: Sequence[AgentDiscoverySignalRecord],
        now: datetime,
    ) -> None:
        workflow = await self._workflow(run)
        ordered = sorted(
            signals,
            key=lambda signal: (
                signal.amount_minor if signal.amount_minor is not None else 2**63 - 1,
                -signal.observed_at.timestamp(),
                str(signal.id),
            ),
        )
        shortlist: list[AgentDiscoverySignalRecord] = []
        seen_date_pairs: set[tuple[date, date | None]] = set()
        for signal in ordered:
            if not _discovery_matches_workflow(signal, workflow):
                continue
            date_pair = (signal.departure_date, signal.return_date)
            if date_pair in seen_date_pairs:
                continue
            seen_date_pairs.add(date_pair)
            shortlist.append(signal)
            if len(shortlist) >= workflow.exact_limit:
                break
        if not shortlist:
            return
        stage = await self._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=now,
        )
        for ordinal, signal in enumerate(shortlist):
            await self._materialize_exact_start(
                run,
                stage.id,
                workflow,
                departure_date=signal.departure_date,
                return_date=signal.return_date,
                ordinal=ordinal,
                now=now,
            )

    async def _materialize_exact_start(
        self,
        run: AgentPlanRunRecord,
        stage_id: UUID,
        workflow: _Workflow,
        *,
        departure_date: date,
        return_date: date | None,
        ordinal: int,
        now: datetime,
    ) -> AgentRunOperationRecord:
        logical_input = _exact_logical_input(
            workflow,
            departure_date=departure_date,
            return_date=return_date,
        )
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(
                    run.id,
                    0x20 + min(ordinal, 0x1F),
                    f"exact-start:{departure_date}:{return_date}",
                ),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage_id,
                provider_id=_PROVIDER_ID,
                kind=AgentOperationKind.EXACT_START,
                immutable_input={**logical_input, "phase": "start", "round": ordinal},
                logical_workflow_input=logical_input,
                consumes_logical_unit=True,
                private_continuation=None,
                max_attempts=workflow.start_attempts,
                created_at=now,
            )
        )

    async def _materialize_poll(
        self,
        run: AgentPlanRunRecord,
        *,
        root: AgentRunOperationRecord,
        predecessor: AgentRunOperationRecord,
        continuation: ExactSearchContinuation,
        poll_round: int,
        now: datetime,
    ) -> AgentRunOperationRecord:
        workflow = await self._workflow(run)
        logical_input = _exact_logical_input(
            workflow,
            departure_date=continuation.expected_departure_date,
            return_date=continuation.expected_return_date,
        )
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(
                    run.id,
                    0x80 + min(poll_round - 1, 0x1F),
                    f"poll:{root.id}:{poll_round}:{continuation.last_update_timestamp}",
                ),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=root.stage_id,
                provider_id=_PROVIDER_ID,
                kind=AgentOperationKind.EXACT_POLL,
                immutable_input={
                    **logical_input,
                    "phase": "poll",
                    "poll_round": poll_round,
                },
                logical_workflow_input=logical_input,
                consumes_logical_unit=False,
                private_continuation=_private_continuation(continuation, poll_round),
                max_attempts=workflow.attempts_per_poll,
                created_at=now,
                logical_root_operation_id=root.id,
            )
        )

    async def _defer_poll(self, poll: AgentRunOperationRecord, now: datetime) -> None:
        if poll.status is AgentOperationStatus.PENDING and self._policy.poll_interval_seconds > 0:
            await self._operations.defer_pending_operation(
                household_id=poll.household_id,
                operation_id=poll.id,
                next_retry_at=now + timedelta(seconds=self._policy.poll_interval_seconds),
                error_code="agent_poll_not_due",
                now=now,
            )

    async def _materialize_ranking(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRunOperationRecord:
        stage = await self._stage(
            run,
            AgentPlanStageKind.RANKING,
            prefix=0x05,
            now=now,
        )
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0xF0, "ranking"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=None,
                kind=AgentOperationKind.RANKING,
                immutable_input={
                    "ranking_profile": "confirmed_amount",
                    "version": "task9-v1",
                },
                logical_workflow_input={
                    "ranking_profile": "confirmed_amount",
                    "version": "task9-v1",
                },
                consumes_logical_unit=False,
                private_continuation=None,
                max_attempts=1,
                created_at=now,
            )
        )

    async def _materialize_analysis(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRunOperationRecord:
        stage = await self._stage(
            run,
            AgentPlanStageKind.ANALYSIS,
            prefix=0x06,
            now=now,
        )
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0xF1, "minimal-report"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=None,
                kind=AgentOperationKind.ANALYSIS,
                immutable_input={"analysis_mode": "minimal_report", "version": "task9-v1"},
                logical_workflow_input={
                    "analysis_mode": "minimal_report",
                    "version": "task9-v1",
                },
                consumes_logical_unit=False,
                private_continuation=None,
                max_attempts=1,
                created_at=now,
            )
        )

    async def _create_minimal_ranking(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRankingSnapshotRecord:
        confirmed = await self._evidence.list_confirmed_evidence(run.household_id, run.id)
        ordered = tuple(
            sorted(
                confirmed,
                key=lambda evidence: (
                    evidence.amount_minor if evidence.amount_minor is not None else 2**63 - 1,
                    -evidence.observed_at.timestamp(),
                    str(evidence.id),
                ),
            )
        )
        if not ordered:
            raise AgentExecutionError("agent_ranking_requires_confirmed_evidence")
        ordered_ids = tuple(evidence.id for evidence in ordered)
        return await self._evidence.create_ranking_snapshot(
            NewAgentRankingSnapshot(
                id=_stable_uuid(run.id, 0xE0, "ranking-snapshot"),
                household_id=run.household_id,
                run_id=run.id,
                confirmed_evidence_ids=ordered_ids,
                composed_candidate_ids=(),
                ranking={
                    "version": "task9-v1",
                    "profile": "confirmed_amount",
                    "ordered": [str(evidence_id) for evidence_id in ordered_ids],
                },
                fingerprint=_fingerprint(
                    "ranking|" + "|".join(str(evidence_id) for evidence_id in ordered_ids)
                ),
                created_at=now,
            )
        )

    async def _ranking_result_id(self, run: AgentPlanRunRecord) -> UUID:
        operations = await self._operations.list_operations(run.household_id, run.id)
        for operation in operations:
            if (
                operation.kind is AgentOperationKind.RANKING
                and operation.status is AgentOperationStatus.SUCCEEDED
                and operation.result_type is AgentOperationResultType.RANKING_SNAPSHOT
                and operation.result_id is not None
            ):
                return operation.result_id
        raise AgentExecutionError("agent_ranking_result_missing")

    async def _required_root(
        self,
        operation: AgentRunOperationRecord,
    ) -> AgentRunOperationRecord:
        root_id = operation.logical_root_operation_id
        if root_id is None:
            raise AgentExecutionError("agent_exact_root_missing")
        root = await self._operations.get_operation(operation.household_id, root_id)
        if root is None:
            raise AgentExecutionError("agent_exact_root_missing")
        return root

    async def _stage(
        self,
        run: AgentPlanRunRecord,
        kind: AgentPlanStageKind,
        *,
        prefix: int,
        now: datetime,
    ) -> AgentPlanStageRecord:
        return await self._operations.create_stage(
            NewAgentPlanStage(
                id=_stable_uuid(run.id, prefix, f"stage:{kind.value}"),
                household_id=run.household_id,
                run_id=run.id,
                kind=kind,
                status=AgentStageStatus.PENDING,
                created_at=now,
            )
        )

    async def _refresh_stage_statuses(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> None:
        for stage in await self._operations.list_stages(run.household_id, run.id):
            progress = await self._operations.get_stage_progress(run.household_id, stage.id)
            if progress is None or progress.total == 0:
                status = AgentStageStatus.PENDING
            elif progress.leased or progress.retry_wait:
                status = AgentStageStatus.RUNNING
            elif progress.pending:
                status = (
                    AgentStageStatus.RUNNING
                    if progress.succeeded or progress.failed or progress.skipped
                    else AgentStageStatus.PENDING
                )
            elif progress.succeeded and (progress.failed or progress.skipped):
                status = AgentStageStatus.PARTIAL
            elif progress.failed:
                status = AgentStageStatus.FAILED
            elif progress.succeeded:
                status = AgentStageStatus.COMPLETED
            elif progress.skipped and run.status in {"cancel_requested", "cancelled"}:
                status = AgentStageStatus.CANCELLED
            else:
                status = AgentStageStatus.SKIPPED
            if stage.status is not status:
                await self._operations.set_stage_status(
                    household_id=run.household_id,
                    stage_id=stage.id,
                    status=status,
                    now=now,
                )

    async def _workflow(self, run: AgentPlanRunRecord) -> _Workflow:
        return await self._workflow_for_ids(run.household_id, run.id)

    async def _workflow_for_ids(self, household_id: UUID, run_id: UUID) -> _Workflow:
        run = await self._runs.get_run(household_id, run_id)
        if run is None:
            raise AgentExecutionError("agent_run_not_found")
        revision = await self._plans.get_revision(household_id, run.revision_id)
        if revision is None:
            raise AgentExecutionError("agent_revision_not_found")
        workflow: _Workflow | None = None
        try:
            plan = _mapping(json.loads(revision.plan_json), "plan")
            scope = _mapping(json.loads(revision.scope_snapshot_json), "scope_snapshot")
            cost = _mapping(json.loads(revision.cost_model_snapshot_json), "cost_model")
            intent = _mapping(plan["intent"], "intent")
            scope_legs = _sequence(scope["legs"], "scope legs")
            first_scope_leg = _mapping(scope_legs[0], "scope leg")
            origin_scope = _mapping(first_scope_leg["origin"], "origin scope")
            destination_scope = _mapping(first_scope_leg["destination"], "destination scope")
            origin_codes = _sequence(origin_scope["airport_codes"], "origin airport codes")
            destination_codes = _sequence(
                destination_scope["airport_codes"],
                "destination airport codes",
            )
            plan_legs = _sequence(intent.get("legs", ()), "intent legs")
            first_plan_leg = _mapping(plan_legs[0], "intent leg")
            scope_constraint = _constraint_from_snapshot(
                _mapping(first_scope_leg["date_constraint"], "date constraint")
            )
            intent_constraint = _constraint_from_snapshot(
                _mapping(first_plan_leg["date_constraint"], "intent date constraint")
            )
            if scope_constraint != intent_constraint:
                raise ValueError("intent and frozen date constraints differ")
            departure, departure_end = _constraint_bounds(scope_constraint)
            trip_shape = TripShape(_text(intent.get("trip_shape", "one_way"), "trip_shape"))
            if trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}:
                raise AgentExecutionError("agent_trip_shape_unsupported")
            return_date: date | None = None
            if trip_shape is TripShape.ONE_WAY:
                if len(plan_legs) != 1 or len(scope_legs) != 1:
                    raise ValueError("one-way workflow must contain exactly one leg")
            else:
                if len(plan_legs) != 2 or len(scope_legs) != 2:
                    raise ValueError("round-trip workflow must contain exactly two legs")
                second_plan_leg = _mapping(plan_legs[1], "return intent leg")
                second_scope_leg = _mapping(scope_legs[1], "return scope leg")
                if not _reciprocal_intent_legs(first_plan_leg, second_plan_leg):
                    raise ValueError("round-trip intent legs must be reciprocal")
                if not _reciprocal_frozen_legs(first_scope_leg, second_scope_leg):
                    raise ValueError("round-trip frozen legs must be reciprocal")
                return_scope_constraint = _constraint_from_snapshot(
                    _mapping(second_scope_leg["date_constraint"], "return date constraint")
                )
                return_intent_constraint = _constraint_from_snapshot(
                    _mapping(second_plan_leg["date_constraint"], "return intent date constraint")
                )
                if (
                    return_scope_constraint != return_intent_constraint
                    or return_scope_constraint.mode is not DateMode.EXACT
                    or return_scope_constraint.start_date < departure
                ):
                    raise ValueError("round-trip return date is not approved")
                return_date = return_scope_constraint.start_date
            exact_limit = revision.estimated_exact_searches or 0
            calendar_limit = revision.estimated_calendar_searches or 0
            workflow = _Workflow(
                origin=_iata(origin_codes[0], "origin"),
                destination=_iata(destination_codes[0], "destination"),
                date_mode=scope_constraint.mode.value,
                departure_date=departure,
                departure_end_date=departure_end,
                return_date=return_date,
                adults=_positive_int(intent.get("adults", 1), "adults"),
                children=_non_negative_int(intent.get("children", 0), "children"),
                infants=_non_negative_int(intent.get("infants", 0), "infants"),
                currency=_currency(intent.get("currency", "RUB")),
                one_way=trip_shape is TripShape.ONE_WAY,
                exact_limit=max(1, exact_limit),
                calendar_limit=max(0, calendar_limit),
                start_attempts=_positive_int(cost.get("start_attempts", 1), "start_attempts"),
                poll_rounds=_positive_int(cost.get("poll_rounds", 1), "poll_rounds"),
                attempts_per_poll=_positive_int(
                    cost.get("attempts_per_poll", 1),
                    "attempts_per_poll",
                ),
                approved_provider_rpm=_positive_int(
                    cost.get("requests_per_minute"),
                    "requests_per_minute",
                ),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            workflow = None
        if workflow is None:
            raise AgentExecutionError("agent_plan_snapshot_invalid")
        return workflow

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("agent execution clock must return an aware datetime")
        return now.astimezone(UTC)


def _constraint_from_snapshot(value: Mapping[str, object]) -> DateConstraint:
    end_raw = value.get("end_date")
    return DateConstraint(
        mode=DateMode(_text(value["mode"], "date mode")),
        start_date=date.fromisoformat(_text(value["start_date"], "start_date")),
        end_date=(date.fromisoformat(_text(end_raw, "end_date")) if end_raw is not None else None),
        flex_days=_non_negative_int(value.get("flex_days", 0), "flex_days"),
    )


def _constraint_bounds(constraint: DateConstraint) -> tuple[date, date]:
    if constraint.mode is DateMode.FLEXIBLE:
        delta = timedelta(days=constraint.flex_days)
        return constraint.start_date - delta, constraint.start_date + delta
    return constraint.start_date, constraint.end_date or constraint.start_date


def _discovery_matches_workflow(
    signal: AgentDiscoverySignalRecord,
    workflow: _Workflow,
) -> bool:
    return (
        signal.origin == workflow.origin
        and signal.destination == workflow.destination
        and workflow.departure_date <= signal.departure_date <= workflow.departure_end_date
        and signal.return_date == workflow.return_date
        and (signal.return_date is None or signal.departure_date <= signal.return_date)
        and signal.currency == workflow.currency
        and signal.passengers == 1
        and signal.passenger_basis is PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
    )


def _reciprocal_intent_legs(
    outbound: Mapping[str, object],
    inbound: Mapping[str, object],
) -> bool:
    return _intent_location(inbound, "origin") == _intent_location(
        outbound, "destination"
    ) and _intent_location(inbound, "destination") == _intent_location(outbound, "origin")


def _intent_location(leg: Mapping[str, object], key: str) -> tuple[str, str]:
    location = _mapping(leg[key], f"intent {key}")
    return (
        _text(location["kind"], f"intent {key} kind"),
        _text(location["value"], f"intent {key} value").upper(),
    )


def _reciprocal_frozen_legs(
    outbound: Mapping[str, object],
    inbound: Mapping[str, object],
) -> bool:
    return _frozen_airport(inbound, "origin") == _frozen_airport(
        outbound, "destination"
    ) and _frozen_airport(inbound, "destination") == _frozen_airport(outbound, "origin")


def _frozen_airport(leg: Mapping[str, object], key: str) -> str:
    location = _mapping(leg[key], f"frozen {key}")
    codes = _sequence(location["airport_codes"], f"frozen {key} airport codes")
    return _iata(codes[0], f"frozen {key}")


def _start_params(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> SearchStartParams:
    departure = _text(immutable_input["departure_date"], "departure_date")
    return_value = immutable_input.get("return_date")
    return SearchStartParams(
        origin=ProviderLocation(LocationScopeKind.AIRPORT, workflow.origin),
        destination=ProviderLocation(LocationScopeKind.AIRPORT, workflow.destination),
        departure_date=departure,
        return_date=_text(return_value, "return_date") if return_value is not None else None,
        adults=workflow.adults,
        children=workflow.children,
        infants=workflow.infants,
        trip_class=AviasalesTripClass.ECONOMY,
        currency=workflow.currency,
        market="RU",
    )


def _exact_binding_from_immutable(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> _ExactBinding:
    binding: _ExactBinding | None = None
    try:
        return_raw = immutable_input.get("return_date")
        candidate = _ExactBinding(
            origin=_iata(immutable_input["origin"], "origin"),
            destination=_iata(immutable_input["destination"], "destination"),
            departure_date=date.fromisoformat(
                _text(immutable_input["departure_date"], "departure_date")
            ),
            return_date=(
                date.fromisoformat(_text(return_raw, "return_date"))
                if return_raw is not None
                else None
            ),
            adults=_positive_int(immutable_input["adults"], "adults"),
            children=_non_negative_int(immutable_input["children"], "children"),
            infants=_non_negative_int(immutable_input["infants"], "infants"),
            passengers=_positive_int(immutable_input["passengers"], "passengers"),
            currency=_currency(immutable_input["currency"]),
        )
        valid = (
            candidate.origin == workflow.origin
            and candidate.destination == workflow.destination
            and workflow.departure_date <= candidate.departure_date <= workflow.departure_end_date
            and candidate.return_date == workflow.return_date
            and candidate.adults == workflow.adults
            and candidate.children == workflow.children
            and candidate.infants == workflow.infants
            and candidate.passengers
            == candidate.adults + candidate.children + candidate.infants
            == workflow.passengers
            and candidate.currency == workflow.currency
            and immutable_input.get("cabin") == "economy"
        )
        if valid:
            binding = candidate
    except (KeyError, TypeError, ValueError):
        binding = None
    if binding is None:
        raise AgentExecutionError("agent_operation_input_invalid")
    return binding


def _exact_logical_input(
    workflow: _Workflow,
    *,
    departure_date: date,
    return_date: date | None,
) -> dict[str, object]:
    return {
        "origin": workflow.origin,
        "destination": workflow.destination,
        "departure_date": departure_date.isoformat(),
        "return_date": return_date.isoformat() if return_date is not None else None,
        "adults": workflow.adults,
        "children": workflow.children,
        "infants": workflow.infants,
        "passengers": workflow.passengers,
        "currency": workflow.currency,
        "cabin": "economy",
    }


def _private_continuation(
    continuation: ExactSearchContinuation,
    poll_round: int,
) -> dict[str, object]:
    return {
        "search_id": continuation.search_id,
        "search_session": continuation.results_url,
        "cursor": continuation.last_update_timestamp,
        "request_id": continuation.request_id,
        "evidence_namespace": str(continuation.evidence_namespace),
        "origin": continuation.expected_origin,
        "destination": continuation.expected_destination,
        "departure_date": continuation.expected_departure_date.isoformat(),
        "return_date": (
            continuation.expected_return_date.isoformat()
            if continuation.expected_return_date is not None
            else None
        ),
        "currency": continuation.expected_currency,
        "passengers": continuation.passengers,
        "poll_round": poll_round,
    }


def _continuation_from_private(
    private: Mapping[str, object] | None,
) -> ExactSearchContinuation:
    if private is None:
        raise AgentExecutionError("agent_private_continuation_missing")
    continuation: ExactSearchContinuation | None = None
    try:
        return_raw = private.get("return_date")
        continuation = ExactSearchContinuation(
            search_id=_text(private["search_id"], "search_id"),
            results_url=_text(private["search_session"], "search_session"),
            last_update_timestamp=_non_negative_int(private["cursor"], "cursor"),
            request_id=_text(private["request_id"], "request_id"),
            evidence_namespace=UUID(_text(private["evidence_namespace"], "evidence_namespace")),
            expected_origin=_iata(private["origin"], "origin"),
            expected_destination=_iata(private["destination"], "destination"),
            expected_departure_date=date.fromisoformat(
                _text(private["departure_date"], "departure_date")
            ),
            expected_return_date=(
                date.fromisoformat(_text(return_raw, "return_date"))
                if return_raw is not None
                else None
            ),
            expected_currency=_currency(private["currency"]),
            passengers=_positive_int(private["passengers"], "passengers"),
        )
    except (KeyError, TypeError, ValueError):
        continuation = None
    if continuation is None:
        raise AgentExecutionError("agent_private_continuation_invalid")
    return continuation


def _private_positive_int(private: Mapping[str, object] | None, key: str) -> int:
    value: int | None = None
    try:
        if private is not None and key in private:
            value = _positive_int(private[key], key)
    except (TypeError, ValueError):
        value = None
    if value is None:
        raise AgentExecutionError("agent_private_continuation_invalid")
    return value


def _attempt_kind(operation: AgentRunOperationRecord) -> AttemptKind:
    if operation.attempt_count > 1:
        return AttemptKind.RETRY
    if operation.kind is AgentOperationKind.EXACT_POLL:
        return AttemptKind.POLL
    return AttemptKind.START


def _classify_failure(error: BaseException, now: datetime) -> _Failure:
    if isinstance(error, AviasalesSearchAuthFailed):
        return _Failure(ProviderFailureClass.AUTH, "provider_auth", None, False)
    if isinstance(error, AviasalesSearchBlocked):
        return _Failure(ProviderFailureClass.FORBIDDEN, "provider_forbidden", None, False)
    if isinstance(error, AviasalesSearchSchemaError):
        return _Failure(ProviderFailureClass.SCHEMA, "provider_schema", None, False)
    if isinstance(error, AviasalesSearchRateLimited):
        delay = error.retry_after_seconds if error.retry_after_seconds is not None else 60
        return _Failure(
            ProviderFailureClass.RATE_LIMITED,
            "provider_rate_limited",
            now + timedelta(seconds=max(1, delay)),
            False,
        )
    if isinstance(error, AviasalesSearchTransportError):
        return _Failure(ProviderFailureClass.NETWORK, "provider_network", None, True)
    if isinstance(error, AviasalesSearchHttpStatusError):
        if error.status_code >= 500:
            return _Failure(ProviderFailureClass.SERVER, "provider_server", None, True)
        return _Failure(None, "provider_client_error", None, False)
    if isinstance(error, AviasalesSearchCapabilityError):
        return _Failure(None, "provider_capability", None, False)
    if isinstance(error, AviasalesSearchPolicyDenied):
        return _Failure(None, "provider_policy_denied", None, False)
    raise TypeError("unsupported provider failure")


def _inactive_code(run: AgentPlanRunRecord, now: datetime) -> str | None:
    if run.status in {"cancel_requested", "cancelled"}:
        return "agent_run_cancelled"
    if now >= run.deadline_at:
        return "agent_run_deadline_exceeded"
    if run.status in _TERMINAL_RUN_STATUSES:
        return "agent_run_terminal"
    return None


def _lease_active_at(operation: AgentRunOperationRecord, now: datetime) -> bool:
    return operation.lease_expires_at is not None and now <= operation.lease_expires_at


def _stable_uuid(namespace: UUID, prefix: int, value: str) -> UUID:
    if not 0 <= prefix <= 0xFF:
        raise ValueError("UUID ordering prefix must fit one byte")
    digest = hashlib.sha256(namespace.bytes + value.encode("utf-8")).digest()
    return UUID(bytes=bytes((prefix,)) + digest[:15])


def _evidence_fingerprint(evidence_id: UUID) -> str:
    return _fingerprint(str(evidence_id))


def _fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return cast(Mapping[str, object], value)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an ordered collection")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    return cast(Sequence[object], value)


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{field_name} must be a non-empty string")
    return value


def _iata(value: object, field_name: str) -> str:
    normalized = _text(value, field_name).upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalnum():
        raise ValueError(f"{field_name} must be a normalized IATA code")
    return normalized


def _currency(value: object) -> str:
    normalized = _text(value, "currency").upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("currency must be an ISO alpha-3 code")
    return normalized


def _positive_int(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value
