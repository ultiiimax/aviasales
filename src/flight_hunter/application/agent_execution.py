from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Literal, Protocol, cast
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.application.agent_operations import (
    OperationScheduler,
    OperationSpec,
    ProviderFailureClass,
    retry_decision,
)
from flight_hunter.domain.agent_evidence import (
    ConfirmedOfferEvidence,
    DiscoverySignal,
    DiscoverySource,
)
from flight_hunter.domain.agent_search import (
    DateConstraint,
    DateMode,
    LocationScopeKind,
    RouteStrategy,
    TripShape,
)
from flight_hunter.domain.offers import FlightSegmentSummary, Freshness, PriceBasis
from flight_hunter.execution_limits import MAX_AGENT_EXECUTION_INTERVAL_SECONDS
from flight_hunter.persistence.agent_repositories import (
    AgentConfirmedOfferEvidenceRecord,
    AgentDiscoverySignalRecord,
    AgentEvidenceRepository,
    AgentOperationConflict,
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
    recompute_agent_plan_revision_content_hash,
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
_EXACT_POLL_EVIDENCE_LIMIT = 50
_PROVIDER_CLOCK_SKEW = timedelta(minutes=5)
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
        for field_name in (
            "operation_lease_seconds",
            "circuit_cooldown_seconds",
            "circuit_probe_lease_seconds",
            "poll_interval_seconds",
        ):
            if getattr(self, field_name) > MAX_AGENT_EXECUTION_INTERVAL_SECONDS:
                raise ValueError(
                    f"{field_name} cannot exceed {MAX_AGENT_EXECUTION_INTERVAL_SECONDS} seconds"
                )


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
    strategies: tuple[RouteStrategy, ...]
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
        for ordinal in range(workflow.calendar_limit):
            departure_date = workflow.departure_date + timedelta(days=ordinal)
            immutable_input = {
                "origin": workflow.origin,
                "destination": workflow.destination,
                "departure_date": departure_date.isoformat(),
                "return_date": (workflow.return_date.isoformat() if workflow.return_date else None),
                "passengers": workflow.passengers,
                "currency": workflow.currency,
                "phase": "calendar",
            }
            await self._scheduler.materialize(
                OperationSpec(
                    id=_stable_uuid(
                        run.id,
                        0x10 + min(ordinal, 0x0F),
                        f"calendar:{departure_date}:{workflow.return_date}",
                    ),
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
        inactive = await self._skip_claimed_if_inactive(run, lease, now)
        if inactive is not None:
            return inactive

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

        before_preflight_now = self._now()
        inactive = await self._skip_claimed_if_inactive(
            run,
            lease,
            before_preflight_now,
        )
        if inactive is not None:
            return inactive
        if self._provider_preflight is not None:
            try:
                self._provider_preflight()
            except (AviasalesSearchCapabilityError, AviasalesSearchPolicyDenied) as error:
                preflight_failure_now = self._now()
                inactive = await self._skip_claimed_if_inactive(
                    run,
                    lease,
                    preflight_failure_now,
                )
                if inactive is not None:
                    return inactive
                return await self._persist_failure(
                    lease.operation,
                    _classify_failure(error, preflight_failure_now),
                    preflight_failure_now,
                )

        preflight_now = self._now()
        inactive = await self._skip_claimed_if_inactive(run, lease, preflight_now)
        if inactive is not None:
            return inactive
        permit_result = await self._operations.acquire_circuit_permit(
            household_id=run.household_id,
            run_id=run.id,
            operation_id=lease.operation.id,
            provider_id=_PROVIDER_ID,
            worker_id=self._worker_id,
            now=preflight_now,
            probe_lease_seconds=self._policy.circuit_probe_lease_seconds,
        )
        permit_now = self._now()
        inactive_code = await self._fresh_inactive_code(run, permit_now)
        if inactive_code is not None:
            if permit_result.permit is not None:
                try:
                    await self._operations.abandon_circuit_permit(
                        household_id=run.household_id,
                        run_id=run.id,
                        worker_id=self._worker_id,
                        circuit_permit=permit_result.permit,
                        now=permit_now,
                    )
                except AgentOperationConflict as error:
                    if error.code in {
                        "agent_circuit_permit_stale",
                        "agent_operation_not_reservable",
                    }:
                        return AgentOperationStatus.LEASED
                    raise
            inactive = await self._skip_claimed_if_inactive(run, lease, permit_now)
            return inactive or AgentOperationStatus.LEASED
        if permit_result.status is CircuitPermitStatus.OPEN:
            if lease.operation.attempt_count >= lease.operation.max_attempts:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_circuit_open",
                    now=permit_now,
                )
                return failed.status
            retry_at = cast(datetime, permit_result.retry_at)
            waiting = await self._operations.schedule_retry(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                next_retry_at=retry_at,
                error_code="agent_circuit_open",
                now=permit_now,
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
            now=permit_now,
            circuit_permit=permit,
        )
        if reservation.status is AttemptReservationStatus.RATE_LIMITED:
            await self._operations.abandon_circuit_permit(
                household_id=run.household_id,
                run_id=run.id,
                worker_id=self._worker_id,
                circuit_permit=permit,
                now=permit_now,
            )
            retry_at = cast(datetime, reservation.retry_at)
            if lease.operation.attempt_count >= lease.operation.max_attempts:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_provider_rate_wait",
                    now=permit_now,
                )
                return failed.status
            waiting = await self._operations.schedule_retry(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                next_retry_at=retry_at,
                error_code="agent_provider_rate_wait",
                now=permit_now,
            )
            return waiting.status
        if reservation.status is AttemptReservationStatus.BUDGET_EXHAUSTED:
            await self._operations.abandon_circuit_permit(
                household_id=run.household_id,
                run_id=run.id,
                worker_id=self._worker_id,
                circuit_permit=permit,
                now=permit_now,
            )
            failed = await self._operations.mark_operation_failed(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                error_code="agent_http_budget_exhausted",
                now=permit_now,
            )
            return failed.status
        reservation_id = reservation.reservation_id
        if reservation_id is None:
            raise RuntimeError("reserved provider attempt omitted its identity")
        await self._durability_checkpoint()
        dispatch_now = self._now()
        inactive_code = await self._fresh_inactive_code(run, dispatch_now)
        if inactive_code is not None:
            try:
                await self._operations.abandon_reserved_http_attempt(
                    household_id=run.household_id,
                    run_id=run.id,
                    worker_id=self._worker_id,
                    circuit_permit=permit,
                    reservation_id=reservation_id,
                    now=dispatch_now,
                )
            except AgentOperationConflict as error:
                if error.code in {
                    "agent_circuit_permit_stale",
                    "agent_operation_not_reservable",
                }:
                    return AgentOperationStatus.LEASED
                raise
            inactive = await self._skip_claimed_if_inactive(run, lease, dispatch_now)
            return inactive or AgentOperationStatus.LEASED

        try:
            raw_outcome = await self._dispatch_provider(lease)
            response_now = self._now()
            outcome = _validated_provider_outcome(
                run=run,
                operation=lease.operation,
                private_continuation=lease.private_continuation,
                workflow=workflow,
                outcome=raw_outcome,
                observed_by=response_now,
            )
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
            failure_checkpoint_now = self._now()
            inactive = await self._skip_claimed_if_inactive(
                run,
                lease,
                failure_checkpoint_now,
            )
            if inactive is not None:
                return inactive
            return await self._persist_failure(
                lease.operation,
                failure,
                failure_checkpoint_now,
            )

        await self._operations.record_circuit_success(
            circuit_permit=permit,
            reservation_id=reservation_id,
            now=response_now,
        )
        if not _lease_active_at(lease.operation, response_now):
            return AgentOperationStatus.LEASED
        outcome_checkpoint_now = self._now()
        preserves_confirmed_evidence = isinstance(outcome, ExactPollOutcome) and any(
            _evidence_allowed_by_strategy(workflow, evidence) for evidence in outcome.evidence
        )
        if not preserves_confirmed_evidence:
            inactive = await self._skip_claimed_if_inactive(
                run,
                lease,
                outcome_checkpoint_now,
            )
            if inactive is not None:
                return inactive
        return await self._persist_provider_outcome(
            run,
            lease,
            outcome,
            outcome_checkpoint_now,
        )

    async def _fresh_inactive_code(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> str | None:
        current = await self._runs.get_run(run.household_id, run.id)
        if current is None:
            raise AgentExecutionError("agent_run_not_found")
        return _inactive_code(current, now)

    async def _skip_claimed_if_inactive(
        self,
        run: AgentPlanRunRecord,
        lease: ServerPrivateOperationLease,
        now: datetime,
    ) -> AgentOperationStatus | None:
        inactive_code = await self._fresh_inactive_code(run, now)
        if inactive_code is None:
            return None
        try:
            skipped = await self._operations.mark_claimed_operation_skipped(
                household_id=run.household_id,
                operation_id=lease.operation.id,
                worker_id=self._worker_id,
                error_code=inactive_code,
                now=now,
            )
        except AgentOperationConflict as error:
            if error.code in {
                "agent_operation_transition_conflict",
                "agent_operation_skip_reason_invalid",
            }:
                return AgentOperationStatus.LEASED
            raise
        return skipped.status

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
                _calendar_params(operation.immutable_input, workflow)
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
        continuation_digest = _private_continuation_digest(lease.private_continuation)
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
            or root.provider_id != _PROVIDER_ID
            or root.logical_root_operation_id is not None
            or root.status is not AgentOperationStatus.SUCCEEDED
            or root.result_type is not AgentOperationResultType.OPERATION
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
            or poll_round > workflow.poll_rounds
            or operation.provider_id != _PROVIDER_ID
            or operation.logical_operation_fingerprint != root.logical_operation_fingerprint
            or operation.id
            != _stable_uuid(
                operation.run_id,
                0x80 + min(poll_round - 1, 0x1F),
                f"poll:{root.id}:{poll_round}:{continuation_digest}",
            )
        ):
            raise AgentExecutionError("agent_operation_input_invalid")
        current = operation
        for expected_round in range(poll_round, 0, -1):
            if (
                current.kind is not AgentOperationKind.EXACT_POLL
                or current.run_id != operation.run_id
                or current.stage_id != root.stage_id
                or current.provider_id != _PROVIDER_ID
                or current.logical_root_operation_id != root.id
                or current.logical_operation_fingerprint != root.logical_operation_fingerprint
                or current.immutable_input.get("phase") != "poll"
                or _positive_int(
                    current.immutable_input.get("poll_round"),
                    "poll_round",
                )
                != expected_round
                or current.handoff_predecessor_operation_id is None
            ):
                raise AgentExecutionError("agent_operation_input_invalid")
            predecessor = await self._operations.get_operation(
                operation.household_id,
                current.handoff_predecessor_operation_id,
            )
            expected_predecessor = root if expected_round == 1 else None
            if (
                predecessor is None
                or (expected_predecessor is not None and predecessor.id != expected_predecessor.id)
                or predecessor.run_id != operation.run_id
                or predecessor.stage_id != root.stage_id
                or predecessor.status is not AgentOperationStatus.SUCCEEDED
                or predecessor.result_type is not AgentOperationResultType.OPERATION
                or predecessor.result_id != current.id
            ):
                raise AgentExecutionError("agent_operation_input_invalid")
            if expected_round > 1 and (
                predecessor.kind is not AgentOperationKind.EXACT_POLL
                or predecessor.logical_root_operation_id != root.id
                or predecessor.provider_id != _PROVIDER_ID
            ):
                raise AgentExecutionError("agent_operation_input_invalid")
            current = predecessor

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
                _calendar_params(operation.immutable_input, workflow),
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
        workflow = await self._workflow(run)
        eligible_evidence = tuple(
            evidence
            for evidence in poll_outcome.evidence
            if _evidence_allowed_by_strategy(workflow, evidence)
        )
        if eligible_evidence:
            stored_evidence = tuple(
                [
                    await self._append_confirmed(run, operation, evidence, now)
                    for evidence in eligible_evidence
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
            current = await self._runs.get_run(operation.household_id, operation.run_id)
            if current is None:
                raise AgentExecutionError("agent_run_not_found")
            next_retry_at = cast(datetime, decision.next_retry_at)
            if next_retry_at >= current.deadline_at:
                failed = await self._operations.mark_operation_failed(
                    household_id=operation.household_id,
                    operation_id=operation.id,
                    worker_id=self._worker_id,
                    error_code=decision.error_code,
                    now=now,
                )
                return failed.status
            waiting = await self._operations.schedule_retry(
                household_id=operation.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                next_retry_at=next_retry_at,
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
            material_failures = tuple(
                operation
                for operation in failed
                if operation.error_code != "agent_no_discovery_results"
            )
            if material_failures:
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
                itinerary_evidence=_confirmed_itinerary_evidence(evidence),
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
        private_continuation = _private_continuation(continuation, poll_round)
        continuation_digest = _private_continuation_digest(private_continuation)
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(
                    run.id,
                    0x80 + min(poll_round - 1, 0x1F),
                    f"poll:{root.id}:{poll_round}:{continuation_digest}",
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
                private_continuation=private_continuation,
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
            approval = await self._runs.get_approval(household_id, run.approval_id)
            if approval is None:
                raise ValueError("run approval is missing")
            plan = _mapping(json.loads(revision.plan_json), "plan")
            scope = _mapping(json.loads(revision.scope_snapshot_json), "scope_snapshot")
            capability = _mapping(
                json.loads(revision.capability_snapshot_json),
                "capability_snapshot",
            )
            cost = _mapping(json.loads(revision.cost_model_snapshot_json), "cost_model")
            intent = _mapping(plan["intent"], "intent")
            scope_legs = _sequence(scope["legs"], "scope legs")
            plan_legs = _sequence(intent.get("legs", ()), "intent legs")
            requested_strategy_values = intent.get("requested_strategies", ())
            if isinstance(
                requested_strategy_values,
                (str, bytes, bytearray),
            ) or not isinstance(requested_strategy_values, Sequence):
                raise TypeError("requested strategies must be an ordered collection")
            requested_strategies = tuple(
                RouteStrategy(_text(value, "requested strategy"))
                for value in requested_strategy_values
            )
            approved_strategies = tuple(
                RouteStrategy(_text(value, "approved strategy"))
                for value in approval.snapshot.approved_strategies
            )
            calendar_estimate = _non_negative_int(
                revision.estimated_calendar_searches,
                "estimated calendar searches",
            )
            exact_estimate = _non_negative_int(
                revision.estimated_exact_searches,
                "estimated exact searches",
            )
            logical_estimate = _positive_int(
                revision.estimated_logical_operations,
                "estimated logical operations",
            )
            http_estimate = _positive_int(
                revision.estimated_http_attempts,
                "estimated http attempts",
            )
            deadline_seconds = _positive_int(
                revision.estimated_deadline_seconds,
                "estimated deadline seconds",
            )
            expected_budget = {
                "calendar_searches": calendar_estimate,
                "exact_searches": exact_estimate,
                "logical_operations": logical_estimate,
                "http_attempts": http_estimate,
                "deadline_seconds": deadline_seconds,
            }
            if (
                approval.id != run.approval_id
                or approval.household_id != household_id
                or approval.plan_id != run.plan_id
                or approval.revision_id != revision.id
                or run.revision_id != revision.id
                or revision.plan_id != run.plan_id
                or approval.run_id != run.id
                or approval.consumed_at is None
                or revision.consumed_at is None
                or approval.approved_at != run.created_at
                or approval.consumed_at != run.created_at
                or revision.consumed_at != run.created_at
                or not (approval.approved_at <= run.created_at < approval.expires_at)
                or approval.snapshot.revision_content_hash != revision.content_hash
                or recompute_agent_plan_revision_content_hash(revision) != revision.content_hash
                or dict(approval.snapshot.approved_budget) != expected_budget
                or run.logical_operation_budget != logical_estimate
                or run.http_attempt_budget != http_estimate
                or run.deadline_at - run.created_at != timedelta(seconds=deadline_seconds)
            ):
                raise ValueError("approval is not bound to the immutable revision")
            if logical_estimate != calendar_estimate + exact_estimate:
                raise ValueError("logical estimate is inconsistent")
            if requested_strategies != approved_strategies:
                raise AgentExecutionError("agent_strategy_unsupported")
            expected_warning_versions = (
                {RouteStrategy.HIDDEN_CITY.value: "hidden-city-v1"}
                if RouteStrategy.HIDDEN_CITY in requested_strategies
                else {}
            )
            if dict(approval.snapshot.risk_warning_versions) != expected_warning_versions:
                raise AgentExecutionError("agent_strategy_unsupported")
            supported_strategies = {
                RouteStrategy.DIRECT,
                RouteStrategy.THROUGH_TICKET,
            }
            if not set(requested_strategies) <= supported_strategies:
                raise AgentExecutionError("agent_strategy_unsupported")
            analysis_modes = intent.get("analysis_modes", ())
            if isinstance(analysis_modes, (str, bytes, bytearray)) or not isinstance(
                analysis_modes,
                Sequence,
            ):
                raise TypeError("analysis modes must be an ordered collection")
            if analysis_modes:
                tuple(_text(value, "analysis mode") for value in analysis_modes)
                raise AgentExecutionError("agent_analysis_unsupported")

            trip_shape = TripShape(_text(intent.get("trip_shape", "one_way"), "trip_shape"))
            if trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}:
                raise AgentExecutionError("agent_trip_shape_unsupported")
            expected_leg_count = 1 if trip_shape is TripShape.ONE_WAY else 2
            if len(plan_legs) != expected_leg_count or len(scope_legs) != expected_leg_count:
                raise ValueError("approved workflow leg count is invalid")
            if _text(plan["coverage"], "plan coverage") != _text(
                scope["coverage"],
                "scope coverage",
            ):
                raise ValueError("plan and scope coverage differ")
            if _text(capability["provider_id"], "provider_id") != _PROVIDER_ID:
                raise ValueError("capability provider differs")
            _text(capability["version"], "capability version")
            if (
                _text(
                    capability["airport_location_semantics"],
                    "airport location semantics",
                )
                != "supported"
            ):
                raise ValueError("airport location semantics are unsupported")
            trip_capability_key = "one_way" if trip_shape is TripShape.ONE_WAY else "round_trip"
            if _text(capability[trip_capability_key], trip_capability_key) != "supported":
                raise ValueError("trip shape capability is unsupported")
            intent_routes = tuple(
                _supported_intent_route(_mapping(value, "intent leg")) for value in plan_legs
            )
            frozen_routes = tuple(
                _supported_frozen_route(_mapping(value, "scope leg")) for value in scope_legs
            )
            if intent_routes != frozen_routes:
                raise ValueError("intent and frozen routes differ")

            first_scope_leg = _mapping(scope_legs[0], "scope leg")
            first_plan_leg = _mapping(plan_legs[0], "intent leg")
            scope_constraint = _constraint_from_snapshot(
                _mapping(first_scope_leg["date_constraint"], "date constraint")
            )
            intent_constraint = _constraint_from_snapshot(
                _mapping(first_plan_leg["date_constraint"], "intent date constraint")
            )
            if scope_constraint != intent_constraint:
                raise ValueError("intent and frozen date constraints differ")
            if (
                DateMode(_text(intent["date_mode"], "intent date mode"))
                is not scope_constraint.mode
            ):
                raise ValueError("top-level and leg date modes differ")
            departure, departure_end = _constraint_bounds(scope_constraint)
            origin, destination = frozen_routes[0]
            return_date: date | None = None
            if trip_shape is TripShape.ROUND_TRIP:
                second_plan_leg = _mapping(plan_legs[1], "return intent leg")
                second_scope_leg = _mapping(scope_legs[1], "return scope leg")
                if intent_routes[1] != (destination, origin):
                    raise ValueError("round-trip intent legs must be reciprocal")
                if frozen_routes[1] != (destination, origin):
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
                    or return_scope_constraint.start_date < departure_end
                ):
                    raise ValueError("round-trip return date is not approved")
                return_date = return_scope_constraint.start_date
            start_attempts = _positive_int(cost.get("start_attempts", 1), "start_attempts")
            poll_rounds = _positive_int(cost.get("poll_rounds", 1), "poll_rounds")
            attempts_per_poll = _positive_int(
                cost.get("attempts_per_poll", 1),
                "attempts_per_poll",
            )
            _text(cost["version"], "cost model version")
            worst_case_exact_http_attempts = _positive_int(
                cost.get("worst_case_exact_http_attempts"),
                "worst_case_exact_http_attempts",
            )
            if worst_case_exact_http_attempts != (start_attempts + poll_rounds * attempts_per_poll):
                raise ValueError("cost model exact attempt estimate is inconsistent")
            if http_estimate != (
                exact_estimate * worst_case_exact_http_attempts + calendar_estimate * start_attempts
            ):
                raise ValueError("http estimate is inconsistent")
            approved_date_surface = (departure_end - departure).days + 1
            if scope_constraint.mode is DateMode.EXACT:
                if calendar_estimate != 0 or exact_estimate != 1:
                    raise ValueError("exact workflow estimates are inconsistent")
            elif (
                calendar_estimate != approved_date_surface
                or exact_estimate != approved_date_surface
            ):
                raise ValueError("calendar workflow estimates are inconsistent")
            effective_strategies = requested_strategies or (RouteStrategy.THROUGH_TICKET,)
            workflow = _Workflow(
                origin=origin,
                destination=destination,
                date_mode=scope_constraint.mode.value,
                departure_date=departure,
                departure_end_date=departure_end,
                return_date=return_date,
                adults=_positive_int(intent.get("adults", 1), "adults"),
                children=_non_negative_int(intent.get("children", 0), "children"),
                infants=_non_negative_int(intent.get("infants", 0), "infants"),
                currency=_currency(intent.get("currency", "RUB")),
                one_way=trip_shape is TripShape.ONE_WAY,
                strategies=effective_strategies,
                exact_limit=exact_estimate,
                calendar_limit=calendar_estimate,
                start_attempts=start_attempts,
                poll_rounds=poll_rounds,
                attempts_per_poll=attempts_per_poll,
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


def _validated_provider_outcome(
    *,
    run: AgentPlanRunRecord,
    operation: AgentRunOperationRecord,
    private_continuation: Mapping[str, object] | None,
    workflow: _Workflow,
    outcome: object,
    observed_by: datetime,
) -> ExactSearchContinuation | ExactPollOutcome | tuple[DiscoverySignal, ...]:
    try:
        if operation.kind is AgentOperationKind.EXACT_START:
            if not isinstance(outcome, ExactSearchContinuation):
                raise TypeError("exact start returned an invalid outcome")
            binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
            if (
                outcome.last_update_timestamp != 0
                or outcome.evidence_namespace != operation.id
                or outcome.expected_origin != binding.origin
                or outcome.expected_destination != binding.destination
                or outcome.expected_departure_date != binding.departure_date
                or outcome.expected_return_date != binding.return_date
                or outcome.expected_currency != binding.currency
                or outcome.passengers != binding.passengers
            ):
                raise ValueError("exact start continuation is not request-bound")
            return outcome

        if operation.kind is AgentOperationKind.CALENDAR_SEARCH:
            if type(outcome) is not tuple or not all(
                isinstance(signal, DiscoverySignal) for signal in outcome
            ):
                raise TypeError("calendar returned an invalid outcome")
            return _validated_calendar_signals(
                cast(tuple[DiscoverySignal, ...], outcome),
                run=run,
                operation=operation,
                workflow=workflow,
                observed_by=observed_by,
            )

        if operation.kind is AgentOperationKind.EXACT_POLL:
            if not isinstance(outcome, ExactPollOutcome):
                raise TypeError("exact poll returned an invalid outcome")
            continuation = _continuation_from_private(private_continuation)
            if outcome.next_cursor < continuation.last_update_timestamp or (
                not outcome.complete and outcome.next_cursor <= continuation.last_update_timestamp
            ):
                raise ValueError("exact poll cursor did not advance")
            if len(outcome.evidence) > _EXACT_POLL_EVIDENCE_LIMIT:
                raise ValueError("exact poll exceeded its provider result limit")
            return ExactPollOutcome(
                evidence=_validated_exact_evidence(
                    outcome.evidence,
                    run=run,
                    continuation=continuation,
                    observed_by=observed_by,
                ),
                next_cursor=outcome.next_cursor,
                complete=outcome.complete,
            )
        raise TypeError("network operation returned an unsupported outcome")
    except (AgentExecutionError, OverflowError, TypeError, ValueError):
        raise AviasalesSearchSchemaError() from None


def _validated_calendar_signals(
    signals: tuple[DiscoverySignal, ...],
    *,
    run: AgentPlanRunRecord,
    operation: AgentRunOperationRecord,
    workflow: _Workflow,
    observed_by: datetime,
) -> tuple[DiscoverySignal, ...]:
    requested_date = _calendar_params(operation.immutable_input, workflow).depart_from
    best_by_date: dict[tuple[date, date | None], DiscoverySignal] = {}
    id_bindings: dict[UUID, tuple[date, date | None]] = {}
    for signal in signals:
        date_pair = (signal.departure_date, signal.return_date)
        if (
            signal.id != _calendar_discovery_signal_id(operation.id, signal)
            or signal.provider_id != _PROVIDER_ID
            or signal.observed_amount.currency != workflow.currency
            or signal.passengers != 1
            or signal.source_kind is not DiscoverySource.CALENDAR
            or not _live_observation(signal.observed_at, run, observed_by)
        ):
            raise ValueError("calendar signal is not request-bound")
        if (
            signal.origin != workflow.origin
            or signal.destination != workflow.destination
            or signal.departure_date != requested_date
            or signal.return_date != workflow.return_date
        ):
            continue
        previous_binding = id_bindings.setdefault(signal.id, date_pair)
        if previous_binding != date_pair:
            raise ValueError("calendar signal identity is ambiguous")
        existing = best_by_date.get(date_pair)
        if existing is None or _calendar_signal_order(signal) < _calendar_signal_order(existing):
            best_by_date[date_pair] = signal

    if len(best_by_date) > 1:
        raise ValueError("calendar response exceeded the approved date surface")
    return tuple(
        sorted(
            best_by_date.values(),
            key=lambda signal: (
                signal.departure_date,
                signal.return_date or date.min,
                *_calendar_signal_order(signal),
            ),
        )
    )


def _calendar_signal_order(signal: DiscoverySignal) -> tuple[int, float, str]:
    return (
        signal.observed_amount.minor_units,
        -signal.observed_at.timestamp(),
        str(signal.id),
    )


def _calendar_discovery_signal_id(
    evidence_namespace: UUID,
    signal: DiscoverySignal,
) -> UUID:
    identity = "|".join(
        (
            _PROVIDER_ID,
            "calendar",
            signal.origin,
            signal.destination,
            signal.departure_date.isoformat(),
            signal.return_date.isoformat() if signal.return_date is not None else "",
            str(signal.observed_amount.minor_units),
            signal.observed_amount.currency,
        )
    )
    return uuid5(evidence_namespace, f"discovery|{identity}")


def _validated_exact_evidence(
    evidence_items: tuple[ConfirmedOfferEvidence, ...],
    *,
    run: AgentPlanRunRecord,
    continuation: ExactSearchContinuation,
    observed_by: datetime,
) -> tuple[ConfirmedOfferEvidence, ...]:
    best_by_offer: dict[str, ConfirmedOfferEvidence] = {}
    id_bindings: dict[UUID, str] = {}
    for evidence in evidence_items:
        expected_id = uuid5(
            continuation.evidence_namespace,
            f"exact|{evidence.provider_offer_id}|{continuation.passengers}",
        )
        if (
            evidence.id != expected_id
            or evidence.provider_id != _PROVIDER_ID
            or evidence.origin != continuation.expected_origin
            or evidence.destination != continuation.expected_destination
            or evidence.departure_date != continuation.expected_departure_date
            or evidence.return_date != continuation.expected_return_date
            or evidence.total_amount.currency != continuation.expected_currency
            or evidence.passengers != continuation.passengers
            or not _live_observation(evidence.observed_at, run, observed_by)
            or not _confirmed_segments_are_bound(evidence)
        ):
            raise ValueError("confirmed evidence is not request-bound")
        previous_binding = id_bindings.setdefault(evidence.id, evidence.provider_offer_id)
        if previous_binding != evidence.provider_offer_id:
            raise ValueError("confirmed evidence identity is ambiguous")
        existing = best_by_offer.get(evidence.provider_offer_id)
        if existing is None or _confirmed_evidence_order(evidence) < _confirmed_evidence_order(
            existing
        ):
            best_by_offer[evidence.provider_offer_id] = evidence
    return tuple(sorted(best_by_offer.values(), key=_confirmed_evidence_order))


def _confirmed_evidence_order(
    evidence: ConfirmedOfferEvidence,
) -> tuple[int, float, str]:
    return (
        evidence.total_amount.minor_units,
        -evidence.observed_at.timestamp(),
        str(evidence.id),
    )


def _live_observation(
    observed_at: datetime,
    run: AgentPlanRunRecord,
    observed_by: datetime,
) -> bool:
    normalized = observed_at.astimezone(UTC)
    response_time = observed_by.astimezone(UTC)
    lower_bound = max(
        run.created_at.astimezone(UTC),
        response_time - _PROVIDER_CLOCK_SKEW,
    )
    return lower_bound <= normalized <= response_time + _PROVIDER_CLOCK_SKEW


def _confirmed_segments_are_bound(evidence: ConfirmedOfferEvidence) -> bool:
    directions = _confirmed_directions(evidence)
    if directions is None:
        return False
    expected_dates = (
        (evidence.departure_date,)
        if evidence.return_date is None
        else (evidence.departure_date, evidence.return_date)
    )
    if len(directions) != len(expected_dates):
        return False
    try:
        parsed_directions = tuple(
            tuple(
                (
                    datetime.fromisoformat(segment.depart_at.replace("Z", "+00:00")),
                    datetime.fromisoformat(segment.arrive_at.replace("Z", "+00:00")),
                )
                for segment in direction
            )
            for direction in directions
        )
    except (AttributeError, TypeError, ValueError):
        return False
    awareness = {
        moment.tzinfo is not None and moment.utcoffset() is not None
        for direction in parsed_directions
        for pair in direction
        for moment in pair
    }
    if len(awareness) != 1:
        return False
    aware = awareness.pop()
    for direction, parsed, expected_date in zip(
        directions,
        parsed_directions,
        expected_dates,
        strict=True,
    ):
        if not parsed or parsed[0][0].date() != expected_date:
            return False
        previous_arrival: datetime | None = None
        for segment, (departure, arrival) in zip(direction, parsed, strict=True):
            normalized_departure = (
                departure.astimezone(UTC).replace(tzinfo=None) if aware else departure
            )
            normalized_arrival = arrival.astimezone(UTC).replace(tzinfo=None) if aware else arrival
            if normalized_arrival < normalized_departure or (
                previous_arrival is not None and normalized_departure < previous_arrival
            ):
                return False
            if not segment.origin or not segment.destination:
                return False
            previous_arrival = normalized_arrival
    return True


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


def _evidence_allowed_by_strategy(
    workflow: _Workflow,
    evidence: ConfirmedOfferEvidence,
) -> bool:
    direct_only = (
        RouteStrategy.DIRECT in workflow.strategies
        and RouteStrategy.THROUGH_TICKET not in workflow.strategies
    )
    return not direct_only or _confirmed_stop_count(evidence) == 0


def _confirmed_itinerary_evidence(evidence: ConfirmedOfferEvidence) -> dict[str, object]:
    itinerary: dict[str, object] = {
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
    }
    stops = _confirmed_stop_count(evidence)
    if stops is not None:
        itinerary["stops"] = stops
    return itinerary


def _confirmed_stop_count(evidence: ConfirmedOfferEvidence) -> int | None:
    directions = _confirmed_directions(evidence)
    if directions is None:
        return None
    return sum(max(0, len(direction) - 1) for direction in directions)


def _confirmed_directions(
    evidence: ConfirmedOfferEvidence,
) -> tuple[tuple[FlightSegmentSummary, ...], ...] | None:
    segments = evidence.segments
    if not segments or segments[0].origin != evidence.origin:
        return None
    if evidence.return_date is None:
        if segments[-1].destination != evidence.destination or not _continuous_segments(segments):
            return None
        return (segments,)

    for boundary in range(1, len(segments)):
        outbound = segments[:boundary]
        inbound = segments[boundary:]
        if (
            outbound[-1].destination == evidence.destination
            and inbound[0].origin == evidence.destination
            and inbound[-1].destination == evidence.origin
            and _continuous_segments(outbound)
            and _continuous_segments(inbound)
        ):
            return (outbound, inbound)
    return None


def _continuous_segments(segments: Sequence[FlightSegmentSummary]) -> bool:
    return all(previous.destination == current.origin for previous, current in pairwise(segments))


def _supported_intent_route(leg: Mapping[str, object]) -> tuple[str, str]:
    return (
        _supported_intent_airport(leg, "origin"),
        _supported_intent_airport(leg, "destination"),
    )


def _supported_intent_airport(leg: Mapping[str, object], key: str) -> str:
    location = _mapping(leg[key], f"intent {key}")
    kind = LocationScopeKind(_text(location["kind"], f"intent {key} kind"))
    if kind is not LocationScopeKind.AIRPORT:
        raise AgentExecutionError("agent_scope_unsupported")
    return _iata(location["value"], f"intent {key}")


def _supported_frozen_route(leg: Mapping[str, object]) -> tuple[str, str]:
    if leg.get("anywhere") is not None:
        raise AgentExecutionError("agent_scope_unsupported")
    return (
        _supported_frozen_airport(leg, "origin"),
        _supported_frozen_airport(leg, "destination"),
    )


def _supported_frozen_airport(leg: Mapping[str, object], key: str) -> str:
    location = _mapping(leg[key], f"frozen {key}")
    requested = _mapping(location["requested_scope"], f"frozen {key} requested scope")
    kind = LocationScopeKind(_text(requested["kind"], f"frozen {key} requested kind"))
    codes = _sequence(location["airport_codes"], f"frozen {key} airport codes")
    nearby_radius_km = _non_negative_int(
        location.get("nearby_radius_km", 0),
        f"frozen {key} nearby radius",
    )
    if kind is not LocationScopeKind.AIRPORT or len(codes) != 1 or nearby_radius_km != 0:
        raise AgentExecutionError("agent_scope_unsupported")
    code = _iata(codes[0], f"frozen {key}")
    if _iata(requested["value"], f"frozen {key} requested value") != code:
        raise ValueError(f"frozen {key} requested scope differs from airport codes")
    return code


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


def _calendar_params(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> CalendarSearchParams:
    departure_date = date.fromisoformat(_text(immutable_input["departure_date"], "departure_date"))
    return_raw = immutable_input.get("return_date")
    return_date = (
        date.fromisoformat(_text(return_raw, "return_date")) if return_raw is not None else None
    )
    if (
        immutable_input.get("phase") != "calendar"
        or _iata(immutable_input["origin"], "origin") != workflow.origin
        or _iata(immutable_input["destination"], "destination") != workflow.destination
        or not workflow.departure_date <= departure_date <= workflow.departure_end_date
        or return_date != workflow.return_date
        or _positive_int(immutable_input["passengers"], "passengers") != workflow.passengers
        or _currency(immutable_input["currency"]) != workflow.currency
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    return CalendarSearchParams(
        origin=ProviderLocation(LocationScopeKind.AIRPORT, workflow.origin),
        destination=ProviderLocation(LocationScopeKind.AIRPORT, workflow.destination),
        depart_from=departure_date,
        depart_to=departure_date,
        one_way=workflow.one_way,
        currency=workflow.currency,
        adults=1,
        children=0,
        infants=0,
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


def _private_continuation_digest(private: Mapping[str, object] | None) -> str:
    continuation = _continuation_from_private(private)
    poll_round = _private_positive_int(private, "poll_round")
    canonical = _private_continuation(continuation, poll_round)
    if private is None or set(private) != set(canonical):
        raise AgentExecutionError("agent_private_continuation_invalid")
    if any(
        type(private[key]) is not type(value) or private[key] != value
        for key, value in canonical.items()
    ):
        raise AgentExecutionError("agent_private_continuation_invalid")
    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
    except (AviasalesSearchSchemaError, KeyError, RuntimeError, TypeError, ValueError):
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
        raw_delay = error.retry_after_seconds
        delay = raw_delay if type(raw_delay) is int else 60
        delay = min(MAX_AGENT_EXECUTION_INTERVAL_SECONDS, max(1, delay))
        return _Failure(
            ProviderFailureClass.RATE_LIMITED,
            "provider_rate_limited",
            now + timedelta(seconds=delay),
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
