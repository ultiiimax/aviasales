from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Literal, Protocol, cast
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.agent.presets import AnalysisMode
from flight_hunter.application.agent_analysis import (
    CURRENCY_COMPARISON_VERSION,
    AnomalyAssessment,
    BuyTimingAssessment,
    assess_anomaly,
    assess_buy_timing,
    history_series_hash,
)
from flight_hunter.application.agent_composition import (
    CompositionPolicy,
    CompositionRequest,
    FrozenCompositionLeg,
    LegEvidencePool,
    RouteComposer,
)
from flight_hunter.application.agent_hidden_city import (
    HIDDEN_CITY_WARNING_VERSION,
    HiddenCityCandidate,
    HiddenCityContext,
    classify_hidden_city,
)
from flight_hunter.application.agent_operations import (
    OperationScheduler,
    OperationSpec,
    ProviderFailureClass,
    retry_decision,
)
from flight_hunter.application.agent_reporting import (
    CandidateRanker,
    ranking_snapshot_to_payload,
)
from flight_hunter.application.agent_result_records import (
    StoredAgentEvidenceError,
    composed_record_to_candidate,
    confirmed_record_to_evidence,
    new_composed_candidate,
)
from flight_hunter.application.agent_scope import finite_route_pairs
from flight_hunter.domain.agent_evidence import (
    BaggageKey,
    CheckedBaggageState,
    ComposedRouteCandidate,
    ConfirmedOfferEvidence,
    CurrencyBasis,
    DiscoverySignal,
    DiscoverySource,
    HistoryAggregationMode,
    HistoryLegKey,
    HistoryObservation,
    HistorySeriesKey,
    ProtectionStatus,
    RiskClass,
    StayWindow,
    TicketStructure,
)
from flight_hunter.domain.agent_search import (
    MAX_ANYWHERE_DISCOVERY_MONTHS,
    CapabilityState,
    DateConstraint,
    DateMode,
    LocationScopeKind,
    RouteStrategy,
    TripShape,
    inclusive_month_count,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import (
    FlightSegmentSummary,
    Freshness,
    PassengerMix,
    PriceBasis,
)
from flight_hunter.execution_limits import MAX_AGENT_EXECUTION_INTERVAL_SECONDS
from flight_hunter.persistence.agent_repositories import (
    AgentAnalysisSnapshotRecord,
    AgentComposedRouteCandidateRecord,
    AgentConfirmedOfferEvidenceRecord,
    AgentDiscoverySignalRecord,
    AgentEvidenceError,
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
    AgentRunScopeSnapshotRecord,
    AgentStageStatus,
    AttemptKind,
    AttemptReservationStatus,
    BaggageEvidenceStatus,
    CircuitPermitStatus,
    NewAgentAnalysisSnapshot,
    NewAgentBookingActionDescriptor,
    NewAgentConfirmedOfferEvidence,
    NewAgentDiscoverySignal,
    NewAgentPlanStage,
    NewAgentRankingSnapshot,
    NewAgentRunScopeSnapshot,
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
    AnywhereDiscoveryParams,
    AviasalesSearchCapabilityError,
    AviasalesSearchPolicyDenied,
    CalendarSearchParams,
    ExactPollOutcome,
    ExactSearchContinuation,
    PrivateBookingActionDescriptor,
)
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

_PROVIDER_ID = "aviasales_search"
_EXACT_POLL_EVIDENCE_LIMIT = 50
_PROVIDER_CLOCK_SKEW = timedelta(minutes=5)
_BOOKING_DESCRIPTOR_TTL = timedelta(minutes=30)
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

    async def discover_anywhere(
        self,
        params: AnywhereDiscoveryParams,
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
    recovered_operation: bool = False
    household_id: UUID | None = None
    run_id: UUID | None = None
    terminal_transitioned: bool = False
    operation_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class _RoutePair:
    origin: str
    destination: str


@dataclass(frozen=True, slots=True)
class _AnywhereRule:
    origins: tuple[str, ...]
    date_start: date
    date_end: date
    discovery_source_ids: tuple[str, ...]
    max_destination_seeds: int
    exact_verification_limit: int
    catalog_checksum: str
    taxonomy_version: str
    coverage: str
    eligible_destination_countries: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _HiddenCityRule:
    version: str
    plan_leg_index: int
    desired_airports: tuple[str, ...]
    discovery_rule: _AnywhereRule


@dataclass(frozen=True, slots=True)
class _SearchLeg:
    ordinal: int
    route_pairs: tuple[_RoutePair, ...]
    date_mode: str
    departure_date: date
    departure_end_date: date
    return_date: date | None = None


@dataclass(frozen=True, slots=True)
class _Workflow:
    trip_shape: TripShape
    search_legs: tuple[_SearchLeg, ...]
    origin: str
    destination: str
    route_pairs: tuple[_RoutePair, ...]
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
    analysis_modes: tuple[AnalysisMode, ...]
    exact_limit: int
    calendar_limit: int
    start_attempts: int
    poll_rounds: int
    attempts_per_poll: int
    approved_provider_rpm: int
    composition_rule_version: str | None = None
    max_split_hubs_per_leg: int = 0
    split_bindings: tuple[_SplitBinding, ...] = ()
    anywhere_rule: _AnywhereRule | None = None
    anywhere_signals: tuple[AgentDiscoverySignalRecord, ...] = ()
    hidden_city_rule: _HiddenCityRule | None = None
    hidden_city_signals: tuple[AgentDiscoverySignalRecord, ...] = ()

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants


@dataclass(frozen=True, slots=True)
class _ExactBinding:
    leg_ordinal: int
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
class _SplitBinding:
    binding: _ExactBinding
    source_evidence_id: UUID
    component_ordinal: int


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
            return AgentExecutionStep(
                False,
                None,
                run.status,
                household_id=run.household_id,
                run_id=run.id,
            )

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
                    return AgentExecutionStep(
                        False,
                        None,
                        current.status,
                        household_id=current.household_id,
                        run_id=current.id,
                    )
                if current.status != "running":
                    return AgentExecutionStep(
                        False,
                        None,
                        current.status,
                        household_id=current.household_id,
                        run_id=current.id,
                    )
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
            return AgentExecutionStep(
                False,
                None,
                failed.status,
                household_id=failed.household_id,
                run_id=failed.id,
                terminal_transitioned=True,
            )
        lease = await self._operations.claim_next_operation(
            household_id=run.household_id,
            run_id=run.id,
            worker_id=self._worker_id,
            now=now,
            lease_seconds=self._policy.operation_lease_seconds,
        )
        if lease is None:
            terminal = await self._advance_or_fail(run, now)
            return AgentExecutionStep(
                False,
                None,
                terminal.status if terminal else run.status,
                household_id=run.household_id,
                run_id=run.id,
                terminal_transitioned=(
                    terminal is not None and terminal.status in _TERMINAL_RUN_STATUSES
                ),
            )

        if lease.operation.kind in {
            AgentOperationKind.CALENDAR_SEARCH,
            AgentOperationKind.EXACT_START,
            AgentOperationKind.EXACT_POLL,
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.HIDDEN_CITY_DISCOVERY,
        }:
            status = await self._run_network_operation(run, lease, now)
        else:
            status = await self._run_local_operation(run, lease, now)
        post_operation_now = self._now()
        await self._refresh_stage_statuses(run, post_operation_now)
        terminal = await self._advance_or_fail(run, post_operation_now)
        completed_operation = await self._operations.get_operation(
            run.household_id,
            lease.operation.id,
        )
        return AgentExecutionStep(
            True,
            status.value,
            terminal.status if terminal is not None else "running",
            lease.recovered_expired_lease,
            run.household_id,
            run.id,
            terminal is not None and terminal.status in _TERMINAL_RUN_STATUSES,
            completed_operation.error_code if completed_operation is not None else None,
        )

    async def _advance_or_fail(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentPlanRunRecord | None:
        try:
            return await self._advance_workflow(run, now)
        except (AgentExecutionError, AgentEvidenceError) as error:
            return await self._runs.set_status(
                household_id=run.household_id,
                run_id=run.id,
                status="failed",
                changed_at=now,
                error_code=error.code,
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
            return AgentExecutionStep(
                False,
                None,
                "cancel_requested",
                household_id=run.household_id,
                run_id=run.id,
            )
        cancelled = await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status="cancelled",
            changed_at=now,
        )
        return AgentExecutionStep(
            False,
            None,
            cancelled.status,
            household_id=cancelled.household_id,
            run_id=cancelled.id,
            terminal_transitioned=True,
        )

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
            return AgentExecutionStep(
                False,
                None,
                run.status,
                household_id=run.household_id,
                run_id=run.id,
            )
        confirmed = await self._evidence.list_confirmed_evidence(run.household_id, run.id)
        ranking_id = await self._saved_ranking_result_id(run, operations)
        hidden_city_confirmed = any(
            record.itinerary_evidence.get("search_role") == "hidden_city" for record in confirmed
        )
        normal_confirmed = any(
            record.itinerary_evidence.get("search_role", "base") != "hidden_city"
            for record in confirmed
        )
        has_publishable_results = hidden_city_confirmed or (
            normal_confirmed and ranking_id is not None
        )
        terminal_status: Literal["partial", "failed"] = (
            "partial" if has_publishable_results else "failed"
        )
        error_code = (
            "agent_run_partial" if has_publishable_results else "agent_run_deadline_exceeded"
        )
        failed = await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status=terminal_status,
            changed_at=now,
            error_code=error_code,
        )
        return AgentExecutionStep(
            False,
            None,
            failed.status,
            household_id=failed.household_id,
            run_id=failed.id,
            terminal_transitioned=True,
        )

    async def _ensure_initial_operation(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> None:
        if await self._operations.list_operations(run.household_id, run.id):
            return
        workflow = await self._workflow(run)
        if workflow.anywhere_rule is not None:
            materialized = await self._materialize_next_anywhere_discovery(
                run,
                workflow,
                (),
                now,
            )
            if not materialized:
                raise AgentExecutionError("agent_plan_snapshot_invalid")
            return
        if all(leg.date_mode == "exact" for leg in workflow.search_legs):
            stage = await self._stage(
                run,
                AgentPlanStageKind.EXACT_SEARCH,
                prefix=0x02,
                now=now,
            )
            ordinal = 0
            for search_leg in workflow.search_legs:
                for route_pair in search_leg.route_pairs:
                    await self._materialize_exact_start(
                        run,
                        stage.id,
                        workflow,
                        origin=route_pair.origin,
                        destination=route_pair.destination,
                        departure_date=search_leg.departure_date,
                        return_date=search_leg.return_date,
                        ordinal=ordinal,
                        leg_ordinal=search_leg.ordinal,
                        now=now,
                    )
                    ordinal += 1
            return
        stage = await self._stage(
            run,
            AgentPlanStageKind.CALENDAR_DISCOVERY,
            prefix=0x01,
            now=now,
        )
        ordinal = 0
        for search_leg in workflow.search_legs:
            date_count = (search_leg.departure_end_date - search_leg.departure_date).days + 1
            for route_pair in search_leg.route_pairs:
                for date_offset in range(date_count):
                    departure_date = search_leg.departure_date + timedelta(days=date_offset)
                    immutable_input = {
                        "leg_ordinal": search_leg.ordinal,
                        "origin": route_pair.origin,
                        "destination": route_pair.destination,
                        "departure_date": departure_date.isoformat(),
                        "return_date": (
                            search_leg.return_date.isoformat() if search_leg.return_date else None
                        ),
                        "passengers": workflow.passengers,
                        "currency": workflow.currency,
                        "phase": "calendar",
                    }
                    await self._scheduler.materialize(
                        OperationSpec(
                            id=_stable_uuid(
                                run.id,
                                0x10 + min(ordinal, 0x0F),
                                (
                                    f"calendar:{search_leg.ordinal}:{route_pair.origin}:"
                                    f"{route_pair.destination}:{departure_date}:"
                                    f"{search_leg.return_date}"
                                ),
                            ),
                            household_id=run.household_id,
                            run_id=run.id,
                            stage_id=stage.id,
                            provider_id=_PROVIDER_ID,
                            kind=AgentOperationKind.CALENDAR_SEARCH,
                            immutable_input=immutable_input,
                            logical_workflow_input={
                                key: value
                                for key, value in immutable_input.items()
                                if key != "phase"
                            },
                            consumes_logical_unit=True,
                            private_continuation=None,
                            max_attempts=workflow.start_attempts,
                            created_at=now,
                        )
                    )
                    ordinal += 1

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

        anywhere_existing: tuple[AgentDiscoverySignalRecord, ...] = ()
        anywhere_remaining_capacity: int | None = None
        if lease.operation.kind in {
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.HIDDEN_CITY_DISCOVERY,
        }:
            try:
                (
                    anywhere_existing,
                    anywhere_remaining_capacity,
                ) = await self._validated_existing_anywhere_capacity(
                    run,
                    workflow,
                    lease.operation,
                )
            except AgentExecutionError as error:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    error_code=error.code,
                    now=now,
                )
                return failed.status
            if anywhere_remaining_capacity == 0:
                current_origin = _iata(lease.operation.immutable_input["origin"], "origin")
                current_source = _text(
                    lease.operation.immutable_input["source_id"],
                    "source_id",
                )
                current_record = next(
                    record
                    for record in anywhere_existing
                    if record.origin == current_origin
                    and _text(record.signal_evidence.get("source_id"), "source_id")
                    == current_source
                )
                succeeded = await self._operations.mark_operation_succeeded(
                    household_id=run.household_id,
                    operation_id=lease.operation.id,
                    worker_id=self._worker_id,
                    result_type=AgentOperationResultType.DISCOVERY_SIGNAL,
                    result_id=current_record.id,
                    now=now,
                )
                return succeeded.status

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
            raw_outcome = await self._dispatch_provider(
                lease,
                workflow=workflow,
                anywhere_remaining_capacity=anywhere_remaining_capacity,
                anywhere_existing=anywhere_existing,
            )
            response_now = self._now()
            outcome = _validated_provider_outcome(
                run=run,
                operation=lease.operation,
                private_continuation=lease.private_continuation,
                workflow=workflow,
                outcome=raw_outcome,
                observed_by=response_now,
                anywhere_remaining_capacity=anywhere_remaining_capacity,
                anywhere_existing_candidate_bindings=frozenset(
                    (
                        signal.origin,
                        _text(signal.signal_evidence.get("source_id"), "source_id"),
                        signal.destination,
                    )
                    for signal in anywhere_existing
                ),
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
        try:
            return await self._persist_provider_outcome(
                run,
                lease,
                outcome,
                outcome_checkpoint_now,
            )
        except (AgentExecutionError, AgentEvidenceError) as error:
            return await self._fail_claimed_operation(
                run,
                lease.operation,
                error.code,
                outcome_checkpoint_now,
            )

    async def _validated_existing_anywhere_capacity(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        operation: AgentRunOperationRecord,
    ) -> tuple[tuple[AgentDiscoverySignalRecord, ...], int]:
        rule = _operation_discovery_rule(workflow, operation.kind)
        search_role = _discovery_search_role(operation.kind)
        _anywhere_params(operation.immutable_input, workflow, rule=rule)
        current_origin = _iata(operation.immutable_input["origin"], "origin")
        current_source = _text(operation.immutable_input["source_id"], "source_id")
        current_limit = _anywhere_binding_seed_limit(rule, current_origin, current_source)
        ordered = await self._validated_durable_discovery_records(
            run,
            workflow,
            rule=rule,
            search_role=search_role,
        )
        current_count = sum(
            record.origin == current_origin
            and _text(record.signal_evidence.get("source_id"), "source_id") == current_source
            for record in ordered
        )
        return ordered, current_limit - current_count

    async def _validated_durable_anywhere_records(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
    ) -> tuple[AgentDiscoverySignalRecord, ...]:
        rule = workflow.anywhere_rule
        if rule is None:
            raise AgentExecutionError("agent_operation_input_invalid")
        return await self._validated_durable_discovery_records(
            run,
            workflow,
            rule=rule,
            search_role="anywhere",
        )

    async def _validated_durable_hidden_city_records(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
    ) -> tuple[AgentDiscoverySignalRecord, ...]:
        hidden_city_rule = workflow.hidden_city_rule
        if hidden_city_rule is None:
            raise AgentExecutionError("agent_operation_input_invalid")
        return await self._validated_durable_discovery_records(
            run,
            workflow,
            rule=hidden_city_rule.discovery_rule,
            search_role="hidden_city",
        )

    async def _validated_durable_discovery_records(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        *,
        rule: _AnywhereRule,
        search_role: str,
    ) -> tuple[AgentDiscoverySignalRecord, ...]:
        records = await self._evidence.list_discovery_signals(run.household_id, run.id)
        eligible_destinations = dict(rule.eligible_destination_countries)
        candidate_bindings: set[tuple[str, str, str]] = set()
        counts_by_binding: dict[tuple[str, str], int] = {}
        for record in records:
            record_role = record.signal_evidence.get(
                "search_role",
                "anywhere" if record.source_kind is DiscoverySource.HOT_OFFER else "base",
            )
            if record_role != search_role:
                continue
            source_id = _text(record.signal_evidence.get("source_id"), "source_id")
            binding = (record.origin, source_id)
            candidate_binding = (*binding, record.destination)
            if (
                record.provider_id != _PROVIDER_ID
                or record.origin not in rule.origins
                or source_id not in rule.discovery_source_ids
                or record.destination not in eligible_destinations
                or not rule.date_start <= record.departure_date <= rule.date_end
                or record.return_date is not None
                or record.amount_minor is None
                or record.currency != workflow.currency
                or record.passengers != 1
                or record.passenger_basis is not PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
                or record.source_kind is not DiscoverySource.HOT_OFFER
                or record.freshness is not Freshness.API_CACHED
                or record.fingerprint != _evidence_fingerprint(record.id)
                or not _durable_provider_observation(record, run)
                or candidate_binding in candidate_bindings
            ):
                raise AgentExecutionError("agent_discovery_evidence_invalid")
            candidate_bindings.add(candidate_binding)
            counts_by_binding[binding] = counts_by_binding.get(binding, 0) + 1
            if counts_by_binding[binding] > _anywhere_binding_seed_limit(
                rule,
                *binding,
            ):
                raise AgentExecutionError("agent_discovery_evidence_invalid")
        ordered = tuple(
            sorted(
                (
                    record
                    for record in records
                    if record.signal_evidence.get(
                        "search_role",
                        ("anywhere" if record.source_kind is DiscoverySource.HOT_OFFER else "base"),
                    )
                    == search_role
                ),
                key=_stored_discovery_order,
            )
        )
        if len(ordered) > rule.max_destination_seeds:
            raise AgentExecutionError("agent_discovery_evidence_invalid")
        return ordered

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
            if workflow.anywhere_rule is not None and operation.kind in {
                AgentOperationKind.EXACT_START,
                AgentOperationKind.EXACT_POLL,
            }:
                exact_operations = tuple(
                    candidate
                    for candidate in await self._operations.list_operations(
                        operation.household_id,
                        operation.run_id,
                    )
                    if candidate.kind is AgentOperationKind.EXACT_START
                )
                _validated_anywhere_exact_source_ids(exact_operations, workflow)
            if (
                workflow.hidden_city_rule is not None
                and operation.kind
                in {
                    AgentOperationKind.EXACT_START,
                    AgentOperationKind.EXACT_POLL,
                }
                and operation.immutable_input.get("search_role") == "hidden_city"
            ):
                exact_operations = tuple(
                    candidate
                    for candidate in await self._operations.list_operations(
                        operation.household_id,
                        operation.run_id,
                    )
                    if candidate.kind is AgentOperationKind.EXACT_START
                    and candidate.immutable_input.get("search_role") == "hidden_city"
                )
                _validated_hidden_city_exact_source_ids(exact_operations, workflow)
            if operation.kind is AgentOperationKind.EXACT_START:
                binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
                if operation.immutable_input.get("phase") != "start":
                    raise AgentExecutionError("agent_operation_input_invalid")
                if workflow.anywhere_rule is not None or (
                    workflow.hidden_city_rule is not None
                    and operation.immutable_input.get("search_role") == "hidden_city"
                ):
                    _source_signal_id_for_binding(operation.immutable_input, workflow, binding)
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
            if operation.kind in {
                AgentOperationKind.SUGGEST_DISCOVERY,
                AgentOperationKind.HIDDEN_CITY_DISCOVERY,
            }:
                _anywhere_params(
                    operation.immutable_input,
                    workflow,
                    rule=_operation_discovery_rule(workflow, operation.kind),
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
        if workflow.anywhere_rule is not None or (
            workflow.hidden_city_rule is not None
            and root.immutable_input.get("search_role") == "hidden_city"
        ):
            _source_signal_id_for_binding(root.immutable_input, workflow, root_binding)
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
        *,
        workflow: _Workflow,
        anywhere_remaining_capacity: int | None,
        anywhere_existing: tuple[AgentDiscoverySignalRecord, ...],
    ) -> ExactSearchContinuation | ExactPollOutcome | tuple[DiscoverySignal, ...]:
        operation = lease.operation
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
        if operation.kind in {
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.HIDDEN_CITY_DISCOVERY,
        }:
            if anywhere_remaining_capacity is None or anywhere_remaining_capacity <= 0:
                raise AgentExecutionError("agent_operation_input_invalid")
            current_origin = _iata(operation.immutable_input["origin"], "origin")
            current_source = _text(operation.immutable_input["source_id"], "source_id")
            excluded_destinations = frozenset(
                record.destination
                for record in anywhere_existing
                if record.origin == current_origin
                and _text(record.signal_evidence.get("source_id"), "source_id") == current_source
            )
            return await self._gateway.discover_anywhere(
                _anywhere_params(
                    operation.immutable_input,
                    workflow,
                    rule=_operation_discovery_rule(workflow, operation.kind),
                    max_results=anywhere_remaining_capacity,
                    excluded_destination_airports=excluded_destinations,
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
        if operation.kind in {
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.HIDDEN_CITY_DISCOVERY,
        }:
            signals = cast(tuple[DiscoverySignal, ...], outcome)
            if not signals:
                workflow = await self._workflow(run)
                existing, _remaining = await self._validated_existing_anywhere_capacity(
                    run,
                    workflow,
                    operation,
                )
                current_origin = _iata(operation.immutable_input["origin"], "origin")
                current_source = _text(operation.immutable_input["source_id"], "source_id")
                existing_for_binding = tuple(
                    record
                    for record in existing
                    if record.origin == current_origin
                    and _text(record.signal_evidence.get("source_id"), "source_id")
                    == current_source
                )
                if existing_for_binding:
                    succeeded = await self._operations.mark_operation_succeeded(
                        household_id=run.household_id,
                        operation_id=operation.id,
                        worker_id=self._worker_id,
                        result_type=AgentOperationResultType.DISCOVERY_SIGNAL,
                        result_id=existing_for_binding[0].id,
                        now=now,
                    )
                    return succeeded.status
                skipped = await self._operations.mark_claimed_operation_skipped(
                    household_id=run.household_id,
                    operation_id=operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_no_discovery_results",
                    now=now,
                )
                return skipped.status
            stored_signals = tuple(
                [await self._append_discovery(run, operation, signal, now) for signal in signals]
            )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.DISCOVERY_SIGNAL,
                result_id=stored_signals[0].id,
                now=now,
            )
            return succeeded.status
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
        hidden_city_search = operation.immutable_input.get("search_role") == "hidden_city"
        strategy_eligible_evidence = (
            poll_outcome.evidence
            if hidden_city_search
            else tuple(
                evidence
                for evidence in poll_outcome.evidence
                if _evidence_allowed_by_strategy(workflow, evidence)
            )
        )
        hidden_city_candidates: dict[UUID, HiddenCityCandidate] = {}
        if hidden_city_search:
            hidden_city_rule = workflow.hidden_city_rule
            if hidden_city_rule is None:
                raise AgentExecutionError("agent_operation_input_invalid")
            context = HiddenCityContext(
                plan_leg_index=hidden_city_rule.plan_leg_index,
                final_plan_leg_index=len(workflow.search_legs) - 1,
            )
            for evidence in strategy_eligible_evidence:
                for desired_airport in hidden_city_rule.desired_airports:
                    decision = classify_hidden_city(
                        evidence,
                        desired_airport,
                        context,
                    )
                    if decision.candidate is not None:
                        hidden_city_candidates[evidence.id] = decision.candidate
                        break
            eligible_evidence = tuple(
                evidence
                for evidence in strategy_eligible_evidence
                if evidence.id in hidden_city_candidates
            )
        else:
            eligible_evidence = strategy_eligible_evidence
        if eligible_evidence:
            stored_evidence = tuple(
                [
                    await self._append_confirmed(
                        run,
                        operation,
                        evidence,
                        now,
                        hidden_city_candidate=hidden_city_candidates.get(evidence.id),
                    )
                    for evidence in eligible_evidence
                ]
            )
            descriptors_by_evidence = {
                descriptor.evidence_id: descriptor
                for descriptor in poll_outcome.booking_descriptors
            }
            if operation.immutable_input.get("search_role") != "hidden_city":
                for stored in stored_evidence:
                    descriptor = descriptors_by_evidence.get(stored.id)
                    if descriptor is not None:
                        await self._append_booking_descriptor(
                            run,
                            stored,
                            descriptor,
                            now,
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
        if operation.kind is AgentOperationKind.SCOPE_FREEZE:
            try:
                snapshot = await self._freeze_anywhere_scope(run, now)
            except (AgentExecutionError, AgentEvidenceError) as error:
                return await self._fail_claimed_operation(
                    run,
                    operation,
                    error.code,
                    now,
                )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.SCOPE_SNAPSHOT,
                result_id=snapshot.id,
                now=now,
            )
            return succeeded.status
        if operation.kind is AgentOperationKind.RANKING:
            try:
                ranking = await self._create_ranking(run, now)
            except (AgentExecutionError, AgentEvidenceError) as error:
                return await self._fail_claimed_operation(
                    run,
                    operation,
                    error.code,
                    now,
                )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.RANKING_SNAPSHOT,
                result_id=ranking.id,
                now=now,
            )
            return succeeded.status
        if operation.kind is AgentOperationKind.COMPOSITION:
            try:
                candidates = await self._persist_composed_candidates(
                    run,
                    operation,
                    now,
                )
            except (AgentExecutionError, AgentEvidenceError) as error:
                return await self._fail_claimed_operation(
                    run,
                    operation,
                    error.code,
                    now,
                )
            if not candidates:
                failed = await self._operations.mark_operation_failed(
                    household_id=run.household_id,
                    operation_id=operation.id,
                    worker_id=self._worker_id,
                    error_code="agent_no_composed_route",
                    now=now,
                )
                return failed.status
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.COMPOSED_CANDIDATE,
                result_id=candidates[0].id,
                now=now,
            )
            return succeeded.status
        if operation.kind is AgentOperationKind.ANALYSIS:
            try:
                analysis_snapshot = await self._create_analysis_snapshot(
                    run,
                    operation,
                    now,
                )
            except (AgentExecutionError, AgentEvidenceError) as error:
                return await self._fail_claimed_operation(
                    run,
                    operation,
                    error.code,
                    now,
                )
            succeeded = await self._operations.mark_operation_succeeded(
                household_id=run.household_id,
                operation_id=operation.id,
                worker_id=self._worker_id,
                result_type=AgentOperationResultType.ANALYSIS_SNAPSHOT,
                result_id=analysis_snapshot.id,
                now=now,
            )
            return succeeded.status
        raise AgentExecutionError("agent_operation_kind_unsupported")

    async def _fail_claimed_operation(
        self,
        run: AgentPlanRunRecord,
        operation: AgentRunOperationRecord,
        error_code: str,
        now: datetime,
    ) -> AgentOperationStatus:
        failed = await self._operations.mark_operation_failed(
            household_id=run.household_id,
            operation_id=operation.id,
            worker_id=self._worker_id,
            error_code=error_code,
            now=now,
        )
        return failed.status

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
        workflow = await self._workflow(current)
        if workflow.anywhere_rule is not None:
            snapshot = await self._operations.get_scope_snapshot_for_run(
                current.household_id,
                current.id,
            )
            if snapshot is None:
                discovery_operations = tuple(
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.SUGGEST_DISCOVERY
                )
                has_successful_discovery = any(
                    operation.status is AgentOperationStatus.SUCCEEDED
                    for operation in discovery_operations
                )
                scope_operations = tuple(
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.SCOPE_FREEZE
                )
                if await self._materialize_next_anywhere_discovery(
                    current,
                    workflow,
                    discovery_operations,
                    now,
                ):
                    await self._refresh_stage_statuses(current, now)
                    return None
                if has_successful_discovery and not scope_operations:
                    await self._materialize_scope_freeze(run, now)
                    await self._refresh_stage_statuses(current, now)
                    return None
                if (
                    has_successful_discovery
                    and scope_operations
                    and all(
                        operation.status is AgentOperationStatus.SUCCEEDED
                        for operation in scope_operations
                    )
                ):
                    raise AgentExecutionError("agent_scope_snapshot_missing")
            else:
                exact_operations = tuple(
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.EXACT_START
                )
                if not exact_operations:
                    await self._materialize_anywhere_exact(run, workflow, now)
                    return None
                try:
                    _validated_anywhere_exact_source_ids(exact_operations, workflow)
                except AgentExecutionError:
                    return await self._runs.set_status(
                        household_id=run.household_id,
                        run_id=run.id,
                        status="failed",
                        changed_at=now,
                        error_code="agent_operation_input_invalid",
                    )
        if workflow.hidden_city_rule is not None:
            hidden_discovery_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.HIDDEN_CITY_DISCOVERY
            )
            if await self._materialize_next_hidden_city_discovery(
                current,
                workflow,
                hidden_discovery_operations,
                now,
            ):
                await self._refresh_stage_statuses(current, now)
                return None
            hidden_exact_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.EXACT_START
                and operation.immutable_input.get("search_role") == "hidden_city"
            )
            if workflow.hidden_city_signals and not hidden_exact_operations:
                await self._materialize_hidden_city_exact(
                    current,
                    workflow,
                    now,
                )
                return None
            if hidden_exact_operations:
                try:
                    _validated_hidden_city_exact_source_ids(
                        hidden_exact_operations,
                        workflow,
                    )
                except AgentExecutionError:
                    return await self._runs.set_status(
                        household_id=run.household_id,
                        run_id=run.id,
                        status="failed",
                        changed_at=now,
                        error_code="agent_operation_input_invalid",
                    )
        confirmed = await self._evidence.list_confirmed_evidence(run.household_id, run.id)
        normal_confirmed = tuple(
            record
            for record in confirmed
            if record.itinerary_evidence.get("search_role", "base") != "hidden_city"
        )
        if normal_confirmed:
            if (
                workflow.composition_rule_version is not None
                and await self._materialize_split_exact(
                    current,
                    workflow,
                    operations,
                    now,
                )
            ):
                await self._refresh_stage_statuses(current, now)
                return None
            composed = await self._composition_candidates(
                current,
                workflow,
                normal_confirmed,
            )
            composition_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.COMPOSITION
            )
            if composed and not composition_operations:
                await self._materialize_composition(
                    current,
                    normal_confirmed,
                    now,
                )
                return None
            if composition_operations:
                composition = composition_operations[0]
                if (
                    composition.status is not AgentOperationStatus.SUCCEEDED
                    and workflow.trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}
                ):
                    return await self._finish_from_failures(
                        run,
                        operations,
                        confirmed,
                        now,
                    )
            elif workflow.trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}:
                return await self._runs.set_status(
                    household_id=run.household_id,
                    run_id=run.id,
                    status="failed",
                    changed_at=now,
                    error_code="agent_no_composed_route",
                )
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

    async def _materialize_next_anywhere_discovery(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        existing: Sequence[AgentRunOperationRecord],
        now: datetime,
    ) -> bool:
        rule = workflow.anywhere_rule
        if rule is None:
            raise AgentExecutionError("agent_plan_snapshot_invalid")
        existing_bindings: set[tuple[str, str]] = set()
        for operation in existing:
            if operation.kind is not AgentOperationKind.SUGGEST_DISCOVERY:
                raise AgentExecutionError("agent_operation_input_invalid")
            try:
                binding = (
                    _iata(operation.immutable_input["origin"], "origin"),
                    _text(operation.immutable_input["source_id"], "source_id"),
                )
            except (KeyError, TypeError, ValueError):
                raise AgentExecutionError("agent_operation_input_invalid") from None
            if binding in existing_bindings:
                raise AgentExecutionError("agent_operation_input_invalid")
            existing_bindings.add(binding)
        stage = await self._stage(
            run,
            AgentPlanStageKind.SCOPE,
            prefix=0x00,
            now=now,
        )
        for ordinal, (origin, source_id) in enumerate(_anywhere_bindings(rule)):
            if (origin, source_id) in existing_bindings:
                continue
            immutable_input = {
                "origin": origin,
                "date_from": rule.date_start.isoformat(),
                "date_to": rule.date_end.isoformat(),
                "max_destination_seeds": rule.max_destination_seeds,
                "seed_limit": _anywhere_binding_seed_limit(rule, origin, source_id),
                "source_id": source_id,
                "currency": workflow.currency,
                "adults": 1,
                "children": 0,
                "infants": 0,
            }
            await self._scheduler.materialize(
                OperationSpec(
                    id=_stable_uuid(
                        run.id,
                        0x08 + min(ordinal, 0x07),
                        f"anywhere:{origin}:{source_id}",
                    ),
                    household_id=run.household_id,
                    run_id=run.id,
                    stage_id=stage.id,
                    provider_id=_PROVIDER_ID,
                    kind=AgentOperationKind.SUGGEST_DISCOVERY,
                    immutable_input=immutable_input,
                    logical_workflow_input=immutable_input,
                    consumes_logical_unit=True,
                    private_continuation=None,
                    max_attempts=workflow.start_attempts,
                    created_at=now,
                )
            )
            return True
        return False

    async def _materialize_next_hidden_city_discovery(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        existing: Sequence[AgentRunOperationRecord],
        now: datetime,
    ) -> bool:
        hidden_city_rule = workflow.hidden_city_rule
        if hidden_city_rule is None:
            raise AgentExecutionError("agent_plan_snapshot_invalid")
        rule = hidden_city_rule.discovery_rule
        existing_bindings: set[tuple[str, str]] = set()
        for operation in existing:
            if operation.kind is not AgentOperationKind.HIDDEN_CITY_DISCOVERY:
                raise AgentExecutionError("agent_operation_input_invalid")
            try:
                binding = (
                    _iata(operation.immutable_input["origin"], "origin"),
                    _text(operation.immutable_input["source_id"], "source_id"),
                )
            except (KeyError, TypeError, ValueError):
                raise AgentExecutionError("agent_operation_input_invalid") from None
            if binding in existing_bindings:
                raise AgentExecutionError("agent_operation_input_invalid")
            existing_bindings.add(binding)
        stage = await self._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=now,
        )
        for ordinal, (origin, source_id) in enumerate(_anywhere_bindings(rule)):
            if (origin, source_id) in existing_bindings:
                continue
            immutable_input = {
                "origin": origin,
                "date_from": rule.date_start.isoformat(),
                "date_to": rule.date_end.isoformat(),
                "max_destination_seeds": rule.max_destination_seeds,
                "seed_limit": _anywhere_binding_seed_limit(rule, origin, source_id),
                "source_id": source_id,
                "currency": workflow.currency,
                "adults": 1,
                "children": 0,
                "infants": 0,
                "search_role": "hidden_city",
            }
            await self._scheduler.materialize(
                OperationSpec(
                    id=_stable_uuid(
                        run.id,
                        0x70 + min(ordinal, 0x07),
                        f"hidden-city-discovery:{origin}:{source_id}",
                    ),
                    household_id=run.household_id,
                    run_id=run.id,
                    stage_id=stage.id,
                    provider_id=_PROVIDER_ID,
                    kind=AgentOperationKind.HIDDEN_CITY_DISCOVERY,
                    immutable_input=immutable_input,
                    logical_workflow_input=immutable_input,
                    consumes_logical_unit=True,
                    private_continuation=None,
                    max_attempts=workflow.start_attempts,
                    created_at=now,
                )
            )
            return True
        return False

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
        skipped = tuple(
            operation
            for operation in operations
            if operation.status is AgentOperationStatus.SKIPPED
        )
        if confirmed:
            normal_confirmed = tuple(
                record
                for record in confirmed
                if record.itinerary_evidence.get("search_role", "base") != "hidden_city"
            )
            if normal_confirmed and await self._saved_ranking_result_id(run, operations) is None:
                error_code = next(
                    (
                        operation.error_code
                        for operation in (*failed, *skipped)
                        if operation.error_code is not None
                    ),
                    "agent_ranking_result_missing",
                )
                return await self._runs.set_status(
                    household_id=run.household_id,
                    run_id=run.id,
                    status="failed",
                    changed_at=now,
                    error_code=error_code,
                )
            workflow = await self._workflow(run)
            if failed or skipped or not _expected_coverage_is_confirmed(workflow, operations):
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
            (
                operation.error_code
                for operation in (*failed, *skipped)
                if operation.error_code is not None
            ),
            "agent_no_confirmed_offer",
        )
        return await self._runs.set_status(
            household_id=run.household_id,
            run_id=run.id,
            status="failed",
            changed_at=now,
            error_code=error_code,
        )

    async def _materialize_scope_freeze(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRunOperationRecord:
        stage = await self._stage(
            run,
            AgentPlanStageKind.SCOPE,
            prefix=0x00,
            now=now,
        )
        immutable_input = {"phase": "scope_freeze", "version": "anywhere-v1"}
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0x09, "anywhere-scope-freeze-v1"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=None,
                kind=AgentOperationKind.SCOPE_FREEZE,
                immutable_input=immutable_input,
                logical_workflow_input=immutable_input,
                consumes_logical_unit=False,
                private_continuation=None,
                max_attempts=1,
                created_at=now,
            )
        )

    async def _freeze_anywhere_scope(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRunScopeSnapshotRecord:
        existing = await self._operations.get_scope_snapshot_for_run(run.household_id, run.id)
        if existing is not None:
            return existing
        workflow = await self._workflow(run)
        rule = workflow.anywhere_rule
        if rule is None:
            raise AgentExecutionError("agent_scope_freeze_invalid")
        candidates = await self._validated_durable_anywhere_records(run, workflow)
        best_by_destination: dict[str, AgentDiscoverySignalRecord] = {}
        for signal in candidates:
            current = best_by_destination.get(signal.destination)
            if current is None or _stored_discovery_order(signal) < _stored_discovery_order(
                current
            ):
                best_by_destination[signal.destination] = signal
        ordered = sorted(best_by_destination.values(), key=_stored_discovery_order)
        selected = tuple(ordered[: min(rule.max_destination_seeds, rule.exact_verification_limit)])
        if not selected:
            raise AgentExecutionError("agent_no_discovery_results")
        payload: dict[str, object] = {
            "origins": list(rule.origins),
            "destinations": [signal.destination for signal in selected],
            "source_signal_ids": [str(signal.id) for signal in selected],
            "catalog_checksum": rule.catalog_checksum,
            "taxonomy_version": rule.taxonomy_version,
            "coverage": rule.coverage,
        }
        candidate = NewAgentRunScopeSnapshot(
            id=_stable_uuid(run.id, 0x0A, "anywhere-scope-snapshot-v1"),
            household_id=run.household_id,
            run_id=run.id,
            fingerprint=_scope_snapshot_fingerprint(payload),
            snapshot=payload,
            created_at=now,
        )
        try:
            return await self._operations.append_scope_snapshot(candidate)
        except AgentOperationConflict as error:
            if error.code != "agent_run_scope_conflict":
                raise
            winner = await self._operations.get_scope_snapshot_for_run(
                run.household_id,
                run.id,
            )
            if winner is None:
                raise AgentExecutionError("agent_scope_snapshot_missing") from error
            return winner

    async def _materialize_anywhere_exact(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        now: datetime,
    ) -> None:
        if workflow.anywhere_rule is None or not workflow.anywhere_signals:
            raise AgentExecutionError("agent_scope_snapshot_invalid")
        stage = await self._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=now,
        )
        for ordinal, signal in enumerate(workflow.anywhere_signals):
            await self._materialize_exact_start(
                run,
                stage.id,
                workflow,
                origin=signal.origin,
                destination=signal.destination,
                departure_date=signal.departure_date,
                return_date=workflow.return_date,
                ordinal=ordinal,
                now=now,
                source_signal_id=signal.id,
            )

    async def _materialize_hidden_city_exact(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        now: datetime,
    ) -> None:
        hidden_city_rule = workflow.hidden_city_rule
        if hidden_city_rule is None or not workflow.hidden_city_signals:
            raise AgentExecutionError("agent_plan_snapshot_invalid")
        stage = await self._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=now,
        )
        for ordinal, signal in enumerate(workflow.hidden_city_signals):
            await self._materialize_exact_start(
                run,
                stage.id,
                workflow,
                origin=signal.origin,
                destination=signal.destination,
                departure_date=signal.departure_date,
                return_date=None,
                ordinal=ordinal,
                now=now,
                source_signal_id=signal.id,
                leg_ordinal=hidden_city_rule.plan_leg_index,
                search_role="hidden_city",
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
                freshness=(
                    Freshness.API_CACHED
                    if signal.source_kind is DiscoverySource.HOT_OFFER
                    else Freshness.LIVE
                ),
                observed_at=signal.observed_at,
                signal_evidence=(
                    {
                        "route_key": f"{signal.origin}-{signal.destination}",
                        "source_id": _text(operation.immutable_input["source_id"], "source_id"),
                        "source_version": "aviasales_hot_offers-v1",
                        "search_role": (
                            "hidden_city"
                            if operation.kind is AgentOperationKind.HIDDEN_CITY_DISCOVERY
                            else "anywhere"
                        ),
                    }
                    if signal.source_kind is DiscoverySource.HOT_OFFER
                    else {
                        "calendar_bucket": signal.departure_date.strftime("%Y-%m"),
                        "leg_ordinal": _non_negative_int(
                            operation.immutable_input.get("leg_ordinal", 0),
                            "leg_ordinal",
                        ),
                    }
                ),
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
        *,
        hidden_city_candidate: HiddenCityCandidate | None = None,
    ) -> AgentConfirmedOfferEvidenceRecord:
        search_role = _text(
            operation.immutable_input.get("search_role", "base"),
            "search_role",
        )
        if (search_role == "hidden_city") != (hidden_city_candidate is not None):
            raise AgentExecutionError("agent_hidden_city_evidence_invalid")
        checked_baggage = evidence.checked_baggage
        if checked_baggage is None:
            raise AgentExecutionError("agent_confirmed_evidence_invalid")
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
                passenger_basis=evidence.price_basis,
                amount_minor=evidence.total_amount.minor_units,
                currency=evidence.total_amount.currency,
                itinerary_evidence=_confirmed_itinerary_evidence(
                    evidence,
                    leg_ordinal=_non_negative_int(
                        operation.immutable_input.get("leg_ordinal", 0),
                        "leg_ordinal",
                    ),
                    search_role=search_role,
                    split_source_evidence_id=(
                        UUID(
                            _text(
                                operation.immutable_input["split_source_evidence_id"],
                                "split_source_evidence_id",
                            )
                        )
                        if operation.immutable_input.get("split_source_evidence_id") is not None
                        else None
                    ),
                    split_component_ordinal=(
                        _non_negative_int(
                            operation.immutable_input["split_component_ordinal"],
                            "split_component_ordinal",
                        )
                        if operation.immutable_input.get("split_component_ordinal") is not None
                        else None
                    ),
                    passenger_mix=PassengerMix(
                        adults=_positive_int(operation.immutable_input["adults"], "adults"),
                        children=_non_negative_int(
                            operation.immutable_input["children"],
                            "children",
                        ),
                        infants=_non_negative_int(
                            operation.immutable_input["infants"],
                            "infants",
                        ),
                    ),
                    hidden_city_candidate=hidden_city_candidate,
                ),
                protection_status=evidence.protection_status,
                baggage_status={
                    CheckedBaggageState.INCLUDED: BaggageEvidenceStatus.INCLUDED,
                    CheckedBaggageState.NOT_INCLUDED: BaggageEvidenceStatus.NOT_INCLUDED,
                    CheckedBaggageState.UNKNOWN: BaggageEvidenceStatus.UNKNOWN,
                }[checked_baggage],
                transfer_status=None,
                visa_status=None,
                fingerprint=_evidence_fingerprint(evidence.id),
                created_at=max(now, evidence.observed_at),
                history_series_hash=_confirmed_history_series_hash(
                    evidence,
                    operation.immutable_input,
                ),
            )
        )

    async def _append_booking_descriptor(
        self,
        run: AgentPlanRunRecord,
        evidence: AgentConfirmedOfferEvidenceRecord,
        descriptor: PrivateBookingActionDescriptor,
        now: datetime,
    ) -> None:
        if descriptor.evidence_id != evidence.id or descriptor.provider_id != evidence.provider_id:
            raise AgentExecutionError("agent_booking_descriptor_invalid")
        private_json = json.dumps(
            dict(descriptor.value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            await self._evidence.append_booking_action_descriptor(
                NewAgentBookingActionDescriptor(
                    id=_stable_uuid(
                        run.id,
                        0xE2,
                        f"booking-descriptor:{evidence.id}",
                    ),
                    household_id=run.household_id,
                    run_id=run.id,
                    confirmed_evidence_id=evidence.id,
                    provider_id=descriptor.provider_id,
                    private_descriptor=descriptor.value,
                    fingerprint=_fingerprint(f"booking-descriptor|{evidence.id}|{private_json}"),
                    created_at=now,
                    expires_at=now + _BOOKING_DESCRIPTOR_TTL,
                )
            )
        except (AgentEvidenceError, TypeError, ValueError) as error:
            raise AgentExecutionError("agent_booking_descriptor_invalid") from error

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
        seen_bindings: set[tuple[int, str, str, date, date | None]] = set()
        for signal in ordered:
            if not _discovery_matches_workflow(signal, workflow):
                continue
            leg_ordinal = _non_negative_int(
                signal.signal_evidence.get("leg_ordinal", 0),
                "leg_ordinal",
            )
            binding = (
                leg_ordinal,
                signal.origin,
                signal.destination,
                signal.departure_date,
                signal.return_date,
            )
            if binding in seen_bindings:
                continue
            seen_bindings.add(binding)
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
                origin=signal.origin,
                destination=signal.destination,
                departure_date=signal.departure_date,
                return_date=signal.return_date,
                ordinal=ordinal,
                leg_ordinal=_non_negative_int(
                    signal.signal_evidence.get("leg_ordinal", 0),
                    "leg_ordinal",
                ),
                now=now,
            )

    async def _materialize_exact_start(
        self,
        run: AgentPlanRunRecord,
        stage_id: UUID,
        workflow: _Workflow,
        *,
        origin: str | None = None,
        destination: str | None = None,
        departure_date: date,
        return_date: date | None,
        ordinal: int,
        now: datetime,
        source_signal_id: UUID | None = None,
        leg_ordinal: int = 0,
        search_role: str = "base",
        split_source_evidence_id: UUID | None = None,
        split_component_ordinal: int | None = None,
    ) -> AgentRunOperationRecord:
        if origin is None:
            origin = workflow.origin
        if destination is None:
            destination = workflow.destination
        logical_input = _exact_logical_input(
            workflow,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            leg_ordinal=leg_ordinal,
        )
        if search_role not in {"base", "hidden_city"}:
            raise AgentExecutionError("agent_operation_input_invalid")
        if split_source_evidence_id is not None:
            if search_role != "base":
                raise AgentExecutionError("agent_operation_input_invalid")
            if split_component_ordinal not in {0, 1}:
                raise AgentExecutionError("agent_operation_input_invalid")
            logical_input.update(
                {
                    "search_role": "split_component",
                    "split_source_evidence_id": str(split_source_evidence_id),
                    "split_component_ordinal": split_component_ordinal,
                }
            )
        elif split_component_ordinal is not None:
            raise AgentExecutionError("agent_operation_input_invalid")
        elif search_role == "hidden_city":
            if source_signal_id is None:
                raise AgentExecutionError("agent_operation_input_invalid")
            logical_input["search_role"] = "hidden_city"
        operation_identity = (
            f"exact-start:{leg_ordinal}:{origin}:{destination}:{departure_date}:{return_date}"
        )
        if split_source_evidence_id is not None:
            operation_identity += f":split:{split_source_evidence_id}:{split_component_ordinal}"
        elif search_role == "hidden_city":
            operation_identity += f":hidden-city:{source_signal_id}"
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(
                    run.id,
                    0x20 + min(ordinal, 0x1F),
                    operation_identity,
                ),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage_id,
                provider_id=_PROVIDER_ID,
                kind=AgentOperationKind.EXACT_START,
                immutable_input={
                    **logical_input,
                    "phase": "start",
                    "round": ordinal,
                    **(
                        {"source_signal_id": str(source_signal_id)}
                        if source_signal_id is not None
                        else {}
                    ),
                },
                logical_workflow_input=logical_input,
                consumes_logical_unit=True,
                private_continuation=None,
                max_attempts=workflow.start_attempts,
                created_at=now,
            )
        )

    async def _materialize_split_exact(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        operations: Sequence[AgentRunOperationRecord],
        now: datetime,
    ) -> bool:
        planned = workflow.split_bindings
        if not planned:
            return False

        exact_starts = tuple(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.EXACT_START
        )
        existing: set[tuple[_ExactBinding, UUID, int]] = set()
        for operation in exact_starts:
            if operation.immutable_input.get("search_role", "base") != "split_component":
                continue
            try:
                binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
                source_evidence_id = UUID(
                    _text(
                        operation.immutable_input["split_source_evidence_id"],
                        "split_source_evidence_id",
                    )
                )
                component_ordinal = _non_negative_int(
                    operation.immutable_input["split_component_ordinal"],
                    "split_component_ordinal",
                )
            except (KeyError, TypeError, ValueError) as error:
                raise AgentExecutionError("agent_operation_input_invalid") from error
            key = (binding, source_evidence_id, component_ordinal)
            if key in existing:
                raise AgentExecutionError("agent_operation_input_invalid")
            existing.add(key)

        missing = tuple(
            split
            for split in planned
            if (
                split.binding,
                split.source_evidence_id,
                split.component_ordinal,
            )
            not in existing
        )
        if not missing:
            return False
        if len(exact_starts) + len(missing) > workflow.exact_limit:
            raise AgentExecutionError("agent_operation_budget_exhausted")

        stage = await self._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=now,
        )
        base_count = len(exact_starts) - len(existing)
        planned_ordinals = {
            (
                split.binding,
                split.source_evidence_id,
                split.component_ordinal,
            ): base_count + ordinal
            for ordinal, split in enumerate(planned)
        }
        for split in missing:
            binding = split.binding
            key = (binding, split.source_evidence_id, split.component_ordinal)
            await self._materialize_exact_start(
                run,
                stage.id,
                workflow,
                origin=binding.origin,
                destination=binding.destination,
                departure_date=binding.departure_date,
                return_date=binding.return_date,
                ordinal=planned_ordinals[key],
                leg_ordinal=binding.leg_ordinal,
                split_source_evidence_id=split.source_evidence_id,
                split_component_ordinal=split.component_ordinal,
                now=now,
            )
        return True

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
            origin=continuation.expected_origin,
            destination=continuation.expected_destination,
            departure_date=continuation.expected_departure_date,
            return_date=continuation.expected_return_date,
            leg_ordinal=_non_negative_int(
                root.immutable_input.get("leg_ordinal", 0),
                "leg_ordinal",
            ),
        )
        if root.immutable_input.get("search_role") == "split_component":
            logical_input.update(
                {
                    "search_role": "split_component",
                    "split_source_evidence_id": _text(
                        root.immutable_input["split_source_evidence_id"],
                        "split_source_evidence_id",
                    ),
                    "split_component_ordinal": _non_negative_int(
                        root.immutable_input["split_component_ordinal"],
                        "split_component_ordinal",
                    ),
                }
            )
        elif root.immutable_input.get("search_role") == "hidden_city":
            logical_input["search_role"] = "hidden_city"
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
                    **(
                        {
                            "source_signal_id": _text(
                                root.immutable_input["source_signal_id"],
                                "source_signal_id",
                            )
                        }
                        if root.immutable_input.get("search_role") == "hidden_city"
                        else {}
                    ),
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

    def _confirmed_domain_evidence(
        self,
        workflow: _Workflow,
        records: Sequence[AgentConfirmedOfferEvidenceRecord],
    ) -> tuple[ConfirmedOfferEvidence, ...]:
        passenger_mix = PassengerMix(
            adults=workflow.adults,
            children=workflow.children,
            infants=workflow.infants,
        )
        converted: list[ConfirmedOfferEvidence] = []
        try:
            for record in records:
                search_role = record.itinerary_evidence.get("search_role", "base")
                leg_ordinal = _non_negative_int(
                    record.itinerary_evidence.get("leg_ordinal", 0),
                    "leg_ordinal",
                )
                approved_legs = (
                    _composition_search_legs(workflow)
                    if search_role == "split_component"
                    else workflow.search_legs
                )
                search_leg = next(
                    (leg for leg in approved_legs if leg.ordinal == leg_ordinal),
                    None,
                )
                if search_leg is None:
                    raise StoredAgentEvidenceError("confirmed evidence leg is not approved")
                converted.append(
                    confirmed_record_to_evidence(
                        record,
                        fallback_passenger_mix=passenger_mix,
                        fallback_departure_date=search_leg.departure_date,
                        fallback_return_date=search_leg.return_date,
                    )
                )
        except (StoredAgentEvidenceError, TypeError, ValueError) as error:
            raise AgentExecutionError("agent_confirmed_evidence_invalid") from error
        return tuple(converted)

    async def _composition_candidates(
        self,
        run: AgentPlanRunRecord,
        workflow: _Workflow,
        records: Sequence[AgentConfirmedOfferEvidenceRecord],
    ) -> tuple[ComposedRouteCandidate, ...]:
        evidence = self._confirmed_domain_evidence(workflow, records)
        by_id = {record.id: item for record, item in zip(records, evidence, strict=True)}
        composition_legs = _composition_search_legs(workflow)
        groups_by_base_id: dict[
            UUID,
            frozenset[tuple[int, str, str, date]],
        ] = {}
        grouped: dict[
            tuple[int, str, str, date],
            list[ConfirmedOfferEvidence],
        ] = {}
        for record, item in zip(records, evidence, strict=True):
            role = record.itinerary_evidence.get("search_role", "base")
            if role != "base":
                continue
            if workflow.trip_shape is TripShape.ROUND_TRIP:
                directions = _confirmed_directions(item)
                if directions is None or len(directions) != 2:
                    raise AgentExecutionError("agent_confirmed_evidence_invalid")
                base_groups = frozenset(
                    (
                        ordinal,
                        direction[0].origin,
                        direction[-1].destination,
                        _segment_local_date(direction[0]),
                    )
                    for ordinal, direction in enumerate(directions)
                )
            else:
                leg_ordinal = _non_negative_int(
                    record.itinerary_evidence.get("leg_ordinal", 0),
                    "leg_ordinal",
                )
                base_groups = frozenset(
                    {
                        (
                            leg_ordinal,
                            item.origin,
                            item.destination,
                            item.departure_date,
                        )
                    }
                )
                grouped.setdefault(next(iter(base_groups)), []).append(item)
            if any(
                not _composition_group_is_approved(group, composition_legs) for group in base_groups
            ):
                raise AgentExecutionError("agent_confirmed_evidence_invalid")
            groups_by_base_id[record.id] = base_groups
        for record, item in zip(records, evidence, strict=True):
            role = record.itinerary_evidence.get("search_role", "base")
            if role == "base":
                continue
            if role != "split_component":
                raise AgentExecutionError("agent_confirmed_evidence_invalid")
            try:
                source_id = UUID(
                    _text(
                        record.itinerary_evidence["split_source_evidence_id"],
                        "split_source_evidence_id",
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise AgentExecutionError("agent_confirmed_evidence_invalid") from error
            leg_ordinal = _non_negative_int(
                record.itinerary_evidence.get("leg_ordinal", 0),
                "leg_ordinal",
            )
            source_groups = groups_by_base_id.get(source_id)
            matching_groups = (
                ()
                if source_groups is None
                else tuple(group for group in source_groups if group[0] == leg_ordinal)
            )
            if len(matching_groups) != 1 or source_id not in by_id:
                raise AgentExecutionError("agent_confirmed_evidence_invalid")
            grouped.setdefault(matching_groups[0], []).append(item)

        pools_by_leg: dict[int, list[LegEvidencePool]] = {
            leg.ordinal: [] for leg in composition_legs
        }
        for (leg_ordinal, origin, destination, departure_date), items in sorted(
            grouped.items(),
            key=lambda value: value[0],
        ):
            search_leg = next(
                (leg for leg in composition_legs if leg.ordinal == leg_ordinal),
                None,
            )
            if (
                search_leg is None
                or _RoutePair(origin, destination) not in search_leg.route_pairs
                or not (
                    search_leg.departure_date <= departure_date <= search_leg.departure_end_date
                )
            ):
                raise AgentExecutionError("agent_confirmed_evidence_invalid")
            unique = {item.id: item for item in items}
            pools_by_leg[leg_ordinal].append(
                LegEvidencePool(
                    leg=FrozenCompositionLeg(
                        leg_ordinal,
                        origin,
                        destination,
                        departure_date,
                    ),
                    evidence=tuple(unique[key] for key in sorted(unique, key=str)),
                )
            )
        if any(not pools_by_leg[leg.ordinal] for leg in composition_legs):
            return ()

        policy = CompositionPolicy()
        combinations = _bounded_composition_pool_combinations(
            tuple(tuple(pools_by_leg[leg.ordinal]) for leg in composition_legs),
            beam_width=policy.beam_width,
        )
        composer = RouteComposer(policy=policy)
        candidates: dict[UUID, ComposedRouteCandidate] = {}
        passenger_mix = PassengerMix(
            adults=workflow.adults,
            children=workflow.children,
            infants=workflow.infants,
        )
        for pools in combinations:
            result = composer.compose(
                CompositionRequest(
                    namespace=run.id,
                    trip_shape=workflow.trip_shape,
                    legs=pools,
                    passenger_mix=passenger_mix,
                    target_currency=workflow.currency,
                )
            )
            for candidate in result.composed:
                candidates[candidate.id] = candidate
        return tuple(
            candidates[key]
            for key in sorted(
                candidates,
                key=lambda candidate_id: _composed_candidate_order(candidates[candidate_id]),
            )
        )

    async def _materialize_composition(
        self,
        run: AgentPlanRunRecord,
        confirmed: Sequence[AgentConfirmedOfferEvidenceRecord],
        now: datetime,
    ) -> AgentRunOperationRecord:
        stage = await self._stage(
            run,
            AgentPlanStageKind.COMPOSITION,
            prefix=0x04,
            now=now,
        )
        evidence_ids = sorted((record.id for record in confirmed), key=str)
        immutable_input = {
            "component_evidence_ids": [str(value) for value in evidence_ids],
            "workflow_version": "route-composer-v1",
            "version": "task11-v1",
        }
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0xE1, "composition"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=None,
                kind=AgentOperationKind.COMPOSITION,
                immutable_input=immutable_input,
                logical_workflow_input=immutable_input,
                consumes_logical_unit=False,
                private_continuation=None,
                max_attempts=1,
                created_at=now,
            )
        )

    async def _persist_composed_candidates(
        self,
        run: AgentPlanRunRecord,
        operation: AgentRunOperationRecord,
        now: datetime,
    ) -> tuple[AgentComposedRouteCandidateRecord, ...]:
        workflow = await self._workflow(run)
        confirmed = await self._evidence.list_confirmed_evidence(
            run.household_id,
            run.id,
        )
        confirmed = tuple(
            record
            for record in confirmed
            if record.itinerary_evidence.get("search_role", "base") != "hidden_city"
        )
        try:
            bound_ids = tuple(
                UUID(_text(value, "component evidence id"))
                for value in _sequence(
                    operation.immutable_input["component_evidence_ids"],
                    "component_evidence_ids",
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AgentExecutionError("agent_operation_input_invalid") from error
        if (
            operation.immutable_input.get("workflow_version") != "route-composer-v1"
            or operation.immutable_input.get("version") != "task11-v1"
            or bound_ids != tuple(sorted((record.id for record in confirmed), key=str))
        ):
            raise AgentExecutionError("agent_operation_input_invalid")
        candidates = await self._composition_candidates(run, workflow, confirmed)
        stored: list[AgentComposedRouteCandidateRecord] = []
        for candidate in candidates:
            stored.append(
                await self._evidence.append_composed_candidate(
                    new_composed_candidate(
                        candidate,
                        household_id=run.household_id,
                        run_id=run.id,
                        stage_id=operation.stage_id,
                        created_at=max(now, candidate.observed_at),
                    )
                )
            )
        return tuple(stored)

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
                    "ranking_profile": "typed_candidate_views",
                    "version": "candidate-ranker-v1",
                },
                logical_workflow_input={
                    "ranking_profile": "typed_candidate_views",
                    "version": "candidate-ranker-v1",
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
        workflow = await self._workflow(run)
        immutable_input = {
            "analysis_modes": [mode.value for mode in workflow.analysis_modes],
            "version": "fare-analysis-v1",
        }
        stage = await self._stage(
            run,
            AgentPlanStageKind.ANALYSIS,
            prefix=0x06,
            now=now,
        )
        return await self._scheduler.materialize(
            OperationSpec(
                id=_stable_uuid(run.id, 0xF1, "fare-analysis"),
                household_id=run.household_id,
                run_id=run.id,
                stage_id=stage.id,
                provider_id=None,
                kind=AgentOperationKind.ANALYSIS,
                immutable_input=immutable_input,
                logical_workflow_input=immutable_input,
                consumes_logical_unit=False,
                private_continuation=None,
                max_attempts=1,
                created_at=now,
            )
        )

    async def _create_ranking(
        self,
        run: AgentPlanRunRecord,
        now: datetime,
    ) -> AgentRankingSnapshotRecord:
        workflow = await self._workflow(run)
        confirmed_records = await self._evidence.list_confirmed_evidence(
            run.household_id,
            run.id,
        )
        confirmed = self._confirmed_domain_evidence(workflow, confirmed_records)
        confirmed_by_id = {candidate.id: candidate for candidate in confirmed}
        composed_records = await self._evidence.list_composed_candidates(
            run.household_id,
            run.id,
        )
        try:
            composed = tuple(
                composed_record_to_candidate(record, confirmed_by_id) for record in composed_records
            )
        except StoredAgentEvidenceError as error:
            raise AgentExecutionError("agent_composed_evidence_invalid") from error
        rankable_confirmed = (
            ()
            if workflow.trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}
            else tuple(
                evidence
                for record, evidence in zip(
                    confirmed_records,
                    confirmed,
                    strict=True,
                )
                if record.itinerary_evidence.get("search_role", "base") == "base"
            )
        )
        candidates: tuple[
            ConfirmedOfferEvidence | ComposedRouteCandidate,
            ...,
        ] = (*rankable_confirmed, *composed)
        if not candidates:
            raise AgentExecutionError("agent_ranking_requires_confirmed_evidence")
        snapshot = CandidateRanker().rank(
            candidates,
            comparison_currency=workflow.currency,
        )
        return await self._evidence.create_ranking_snapshot(
            NewAgentRankingSnapshot(
                id=_stable_uuid(run.id, 0xE0, "ranking-snapshot"),
                household_id=run.household_id,
                run_id=run.id,
                confirmed_evidence_ids=snapshot.confirmed_evidence_ids,
                composed_candidate_ids=snapshot.composed_candidate_ids,
                ranking=ranking_snapshot_to_payload(snapshot),
                fingerprint=f"sha256:{snapshot.fingerprint}",
                created_at=now,
            )
        )

    async def _create_analysis_snapshot(
        self,
        run: AgentPlanRunRecord,
        operation: AgentRunOperationRecord,
        now: datetime,
    ) -> AgentAnalysisSnapshotRecord:
        workflow = await self._workflow(run)
        bound_modes = _bound_analysis_modes(operation.immutable_input, workflow)
        confirmed = await self._evidence.list_confirmed_evidence(
            run.household_id,
            run.id,
        )
        existing = await self._evidence.get_analysis_snapshot_for_run(
            run.household_id,
            run.id,
        )
        if existing is not None:
            _validate_existing_analysis_snapshot(
                existing,
                workflow=workflow,
                bound_modes=bound_modes,
                confirmed=confirmed,
            )
            return existing

        if not _analysis_scope_supported(workflow):
            reference_candidates = tuple(
                record
                for record in confirmed
                if record.source == "exact_search"
                and record.itinerary_evidence.get("search_role", "base") != "hidden_city"
            )
            if not reference_candidates:
                raise AgentExecutionError("agent_analysis_requires_confirmed_evidence")
            source_records = _bounded_analysis_source_records(
                reference_candidates,
                limit=100,
            )
            return await self._evidence.create_analysis_snapshot(
                NewAgentAnalysisSnapshot(
                    id=_stable_uuid(run.id, 0xE1, "fare-analysis-snapshot"),
                    household_id=run.household_id,
                    run_id=run.id,
                    source_evidence_ids=tuple(record.id for record in source_records),
                    analysis={
                        "version": "fare-analysis-snapshot-v1",
                        "source": "confirmed_exact_history",
                        "aggregation_mode": "market_minimum",
                        "scope_status": "unsupported_trip_structure",
                        "scope_reason": "full_itinerary_history_unavailable",
                        "trip_shape": workflow.trip_shape.value,
                        "requested_modes": [mode.value for mode in bound_modes],
                        "source_evidence_truncated": (
                            len(source_records) < len(reference_candidates)
                        ),
                    },
                    created_at=now,
                )
            )

        eligible = tuple(
            record
            for record in confirmed
            if record.source == "exact_search"
            and record.itinerary_evidence.get("search_role", "base") == "base"
            and record.amount_minor is not None
            and record.currency is not None
            and record.history_series_hash is not None
        )
        if not eligible:
            raise AgentExecutionError("agent_analysis_requires_confirmed_evidence")
        primary = min(
            eligible,
            key=lambda record: (
                cast(int, record.amount_minor),
                record.observed_at,
                str(record.id),
            ),
        )
        current = _history_observation_from_record(primary)
        history_records: tuple[AgentConfirmedOfferEvidenceRecord, ...] = ()
        history: tuple[HistoryObservation, ...] = ()
        if {
            AnalysisMode.BUY_TIMING,
            AnalysisMode.ERROR_FARE,
        }.intersection(bound_modes):
            candidates = await self._evidence.list_confirmed_history(
                run.household_id,
                current.series_hash,
                observed_before=current.observed_at,
            )
            history_records, history = _valid_analysis_history_records(candidates)

        try:
            primary_payload = _analysis_primary_payload(primary, workflow)
        except (KeyError, TypeError, ValueError) as error:
            raise AgentExecutionError("agent_confirmed_evidence_invalid") from error
        origin = cast(str, primary_payload["origin"])
        destination = cast(str, primary_payload["destination"])
        departure_date = date.fromisoformat(cast(str, primary_payload["departure_date"]))
        return_text = primary_payload["return_date"]
        return_date = None if return_text is None else date.fromisoformat(cast(str, return_text))
        referenced_history = _bounded_analysis_source_records(
            history_records,
            limit=99,
        )

        payload: dict[str, object] = {
            "version": "fare-analysis-snapshot-v1",
            "source": "confirmed_exact_history",
            "aggregation_mode": "market_minimum",
            "scope_status": "supported",
            "trip_shape": workflow.trip_shape.value,
            "requested_modes": [mode.value for mode in bound_modes],
            "primary_evidence_id": str(primary.id),
            "history_series_hash": current.series_hash,
            "history_observation_count": len(history_records),
            "history_evidence_fingerprint": _history_evidence_fingerprint(history_records),
            "source_evidence_truncated": len(referenced_history) < len(history_records),
            **primary_payload,
        }
        if AnalysisMode.BUY_TIMING in bound_modes:
            assessment = assess_buy_timing(history, current)
            payload["buy_timing"] = _buy_timing_payload(assessment)
            payload["watch_action"] = {
                "available": assessment.watch_action_available,
                "origin": origin,
                "destination": destination,
                "departure_date": departure_date.isoformat(),
                "return_date": return_date.isoformat() if return_date is not None else None,
                "passengers": primary.passengers,
                "currency": cast(str, primary.currency),
            }
        if AnalysisMode.ERROR_FARE in bound_modes:
            payload["anomaly"] = _anomaly_payload(assess_anomaly(history, current))
        if AnalysisMode.CURRENCY_COMPARE in bound_modes:
            payload["currency_comparison"] = {
                "status": "fx_provider_unavailable",
                "reason_code": "fx_provider_unavailable",
                "reference_evidence_id": str(primary.id),
                "reference_amount": {
                    "minor_units": cast(int, primary.amount_minor),
                    "currency": cast(str, primary.currency),
                },
                "candidate_evidence_id": None,
                "candidate_amount": None,
                "comparison_currency": workflow.currency,
                "savings_minor_units": None,
                "savings_percent": None,
                "calculation_version": CURRENCY_COMPARISON_VERSION,
            }
        source_ids = (*tuple(record.id for record in referenced_history), primary.id)
        return await self._evidence.create_analysis_snapshot(
            NewAgentAnalysisSnapshot(
                id=_stable_uuid(run.id, 0xE1, "fare-analysis-snapshot"),
                household_id=run.household_id,
                run_id=run.id,
                source_evidence_ids=source_ids,
                analysis=payload,
                created_at=now,
            )
        )

    async def _saved_ranking_result_id(
        self,
        run: AgentPlanRunRecord,
        operations: Sequence[AgentRunOperationRecord],
    ) -> UUID | None:
        result_ids: list[UUID] = []
        for operation in operations:
            if (
                operation.kind is AgentOperationKind.RANKING
                and operation.status is AgentOperationStatus.SUCCEEDED
                and operation.result_type is AgentOperationResultType.RANKING_SNAPSHOT
                and operation.result_id is not None
            ):
                result_ids.append(operation.result_id)
        if len(result_ids) != 1:
            return None
        snapshot = await self._evidence.get_ranking_snapshot(
            run.household_id,
            result_ids[0],
        )
        if snapshot is None or snapshot.run_id != run.id:
            return None
        return snapshot.id

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
                RouteStrategy.SPLIT_TICKET,
                RouteStrategy.SELF_TRANSFER,
                RouteStrategy.HIDDEN_CITY,
            }
            if not set(requested_strategies) <= supported_strategies:
                raise AgentExecutionError("agent_strategy_unsupported")
            split_requested = bool(
                {
                    RouteStrategy.SPLIT_TICKET,
                    RouteStrategy.SELF_TRANSFER,
                }.intersection(requested_strategies)
            )
            composition_rule_version: str | None = None
            max_split_hubs_per_leg = 0
            raw_composition = plan.get("composition")
            if split_requested:
                composition = _mapping(raw_composition, "composition rule")
                composition_rule_version = _text(
                    composition["version"],
                    "composition rule version",
                )
                max_split_hubs_per_leg = _positive_int(
                    composition["max_hubs_per_leg"],
                    "max_hubs_per_leg",
                )
                if (
                    composition_rule_version != "confirmed-hubs-v1"
                    or _text(composition["source"], "composition hub source")
                    != "confirmed_connection_airports"
                    or max_split_hubs_per_leg > 16
                ):
                    raise AgentExecutionError("agent_composition_rule_invalid")
            elif raw_composition is not None:
                raise AgentExecutionError("agent_composition_rule_invalid")
            analysis_modes = intent.get("analysis_modes", ())
            if isinstance(analysis_modes, (str, bytes, bytearray)) or not isinstance(
                analysis_modes,
                Sequence,
            ):
                raise TypeError("analysis modes must be an ordered collection")
            try:
                approved_analysis_modes = tuple(
                    AnalysisMode(_text(value, "analysis mode")) for value in analysis_modes
                )
            except ValueError as error:
                raise AgentExecutionError("agent_analysis_unsupported") from error
            if len(approved_analysis_modes) != len(set(approved_analysis_modes)):
                raise AgentExecutionError("agent_analysis_unsupported")

            trip_shape = TripShape(_text(intent.get("trip_shape", "one_way"), "trip_shape"))
            expected_leg_count = {
                TripShape.ONE_WAY: 1,
                TripShape.ROUND_TRIP: 2,
                TripShape.OPEN_JAW: 2,
            }.get(trip_shape)
            if (
                expected_leg_count is not None
                and (len(plan_legs) != expected_leg_count or len(scope_legs) != expected_leg_count)
            ) or (
                trip_shape is TripShape.MULTI_CITY
                and (len(plan_legs) < 2 or len(plan_legs) != len(scope_legs))
            ):
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
            if trip_shape is TripShape.ROUND_TRIP:
                if _text(capability["round_trip"], "round_trip") != "supported":
                    raise ValueError("trip shape capability is unsupported")
            else:
                if _text(capability["one_way"], "one_way") != "supported":
                    raise ValueError("per-leg one-way capability is unsupported")
                if trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}:
                    native_key = (
                        "native_open_jaw"
                        if trip_shape is TripShape.OPEN_JAW
                        else "native_multi_city"
                    )
                    native_state = CapabilityState(_text(capability[native_key], native_key))
                    if native_state is CapabilityState.SUPPORTED:
                        raise AgentExecutionError("agent_native_multi_leg_gateway_unsupported")
            first_scope_leg = _mapping(scope_legs[0], "scope leg")
            first_plan_leg = _mapping(plan_legs[0], "intent leg")
            origin_codes = _finite_frozen_airport_codes(
                first_scope_leg,
                first_plan_leg,
                "origin",
            )
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
            coverage = _text(scope["coverage"], "scope coverage")
            adults = _positive_int(intent.get("adults", 1), "adults")
            children = _non_negative_int(intent.get("children", 0), "children")
            infants = _non_negative_int(intent.get("infants", 0), "infants")
            currency = _currency(intent.get("currency", "RUB"))
            anywhere_rule: _AnywhereRule | None = None
            anywhere_signals: tuple[AgentDiscoverySignalRecord, ...] = ()
            raw_anywhere = first_scope_leg.get("anywhere")
            if raw_anywhere is not None:
                if (
                    first_scope_leg.get("destination") is not None
                    or first_scope_leg.get("reciprocal_anywhere_return", False) is not False
                ):
                    raise ValueError("outbound anywhere scope is invalid")
                anywhere_rule = _anywhere_rule_from_snapshot(
                    _mapping(raw_anywhere, "anywhere rule"),
                    first_plan_leg=first_plan_leg,
                    origin_codes=origin_codes,
                    date_start=departure,
                    date_end=departure_end,
                    coverage=coverage,
                )
                snapshot = await self._operations.get_scope_snapshot_for_run(household_id, run_id)
                if snapshot is not None:
                    anywhere_signals = await self._validated_anywhere_scope_snapshot(
                        snapshot,
                        run=run,
                        rule=anywhere_rule,
                        currency=currency,
                    )
                route_pairs = tuple(
                    dict.fromkeys(
                        _RoutePair(signal.origin, signal.destination) for signal in anywhere_signals
                    )
                )
                origin = origin_codes[0]
                destination = (
                    anywhere_signals[0].destination
                    if anywhere_signals
                    else anywhere_rule.eligible_destination_countries[0][0]
                )
                destination_codes: tuple[str, ...] = ()
            else:
                destination_codes = _finite_frozen_airport_codes(
                    first_scope_leg,
                    first_plan_leg,
                    "destination",
                )
                route_pairs = tuple(
                    _RoutePair(origin_code, destination_code)
                    for origin_code, destination_code in finite_route_pairs(
                        origin_codes,
                        destination_codes,
                    )
                )
                origin, destination = route_pairs[0].origin, route_pairs[0].destination
            return_date: date | None = None
            search_legs: tuple[_SearchLeg, ...]
            if trip_shape is TripShape.ROUND_TRIP:
                second_plan_leg = _mapping(plan_legs[1], "return intent leg")
                second_scope_leg = _mapping(scope_legs[1], "return scope leg")
                if _intent_scope_identity(first_plan_leg, "origin") != _intent_scope_identity(
                    second_plan_leg, "destination"
                ) or _intent_scope_identity(
                    first_plan_leg, "destination"
                ) != _intent_scope_identity(second_plan_leg, "origin"):
                    raise ValueError("round-trip intent legs must be reciprocal")
                if anywhere_rule is not None:
                    if (
                        second_scope_leg.get("reciprocal_anywhere_return") is not True
                        or second_scope_leg.get("origin") is not None
                        or second_scope_leg.get("anywhere") is not None
                    ):
                        raise ValueError("anywhere return placeholder is invalid")
                    return_destination_codes = _finite_frozen_airport_codes(
                        second_scope_leg,
                        second_plan_leg,
                        "destination",
                    )
                    if set(return_destination_codes) != set(origin_codes):
                        raise ValueError("anywhere return destination is not reciprocal")
                else:
                    if second_scope_leg.get("reciprocal_anywhere_return", False) is not False:
                        raise ValueError("finite return leg cannot be an anywhere placeholder")
                    return_origin_codes = _finite_frozen_airport_codes(
                        second_scope_leg,
                        second_plan_leg,
                        "origin",
                    )
                    return_destination_codes = _finite_frozen_airport_codes(
                        second_scope_leg,
                        second_plan_leg,
                        "destination",
                    )
                    if set(return_origin_codes) != set(destination_codes) or set(
                        return_destination_codes
                    ) != set(origin_codes):
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
                search_legs = (
                    _SearchLeg(
                        ordinal=0,
                        route_pairs=route_pairs,
                        date_mode=scope_constraint.mode.value,
                        departure_date=departure,
                        departure_end_date=departure_end,
                        return_date=return_date,
                    ),
                )
            elif trip_shape in {TripShape.OPEN_JAW, TripShape.MULTI_CITY}:
                if anywhere_rule is not None:
                    raise AgentExecutionError("agent_multi_leg_anywhere_unsupported")
                ordered_legs = [
                    _SearchLeg(
                        ordinal=0,
                        route_pairs=route_pairs,
                        date_mode=scope_constraint.mode.value,
                        departure_date=departure,
                        departure_end_date=departure_end,
                    )
                ]
                for leg_ordinal in range(1, len(plan_legs)):
                    ordered_legs.append(
                        _finite_search_leg_from_snapshots(
                            ordinal=leg_ordinal,
                            scope_leg=_mapping(scope_legs[leg_ordinal], "scope leg"),
                            intent_leg=_mapping(plan_legs[leg_ordinal], "intent leg"),
                        )
                    )
                if any(
                    current.departure_date < previous.departure_date
                    for previous, current in pairwise(ordered_legs)
                ):
                    raise ValueError("multi-leg dates must preserve requested order")
                search_legs = tuple(ordered_legs)
                route_pairs = tuple(
                    route_pair
                    for search_leg in search_legs
                    for route_pair in search_leg.route_pairs
                )
            else:
                search_legs = (
                    _SearchLeg(
                        ordinal=0,
                        route_pairs=route_pairs,
                        date_mode=scope_constraint.mode.value,
                        departure_date=departure,
                        departure_end_date=departure_end,
                    ),
                )
            hidden_city_rule: _HiddenCityRule | None = None
            raw_hidden_city = plan.get("hidden_city")
            if RouteStrategy.HIDDEN_CITY in requested_strategies:
                if trip_shape is not TripShape.ONE_WAY or anywhere_rule is not None:
                    raise AgentExecutionError("agent_hidden_city_plan_invalid")
                hidden_city_rule = _hidden_city_rule_from_plan(
                    _mapping(raw_hidden_city, "hidden-city rule"),
                    plan_leg_index=len(search_legs) - 1,
                    origin_codes=tuple(
                        route_pair.origin for route_pair in search_legs[-1].route_pairs
                    ),
                    desired_airports=tuple(
                        route_pair.destination for route_pair in search_legs[-1].route_pairs
                    ),
                    date_start=search_legs[-1].departure_date,
                    date_end=search_legs[-1].departure_end_date,
                    coverage=coverage,
                    origin_catalog_checksum=_text(
                        _mapping(
                            _mapping(scope_legs[-1], "hidden-city scope leg")["origin"],
                            "hidden-city origin scope",
                        )["catalog_checksum"],
                        "hidden-city origin catalog checksum",
                    ),
                )
            elif raw_hidden_city is not None:
                raise AgentExecutionError("agent_hidden_city_plan_invalid")
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
            if anywhere_rule is not None:
                if split_requested or hidden_city_rule is not None:
                    raise AgentExecutionError("agent_split_anywhere_unsupported")
                discovery_query_work = len(anywhere_rule.origins) * len(
                    anywhere_rule.discovery_source_ids
                )
                if (
                    calendar_estimate
                    != max(anywhere_rule.max_destination_seeds, discovery_query_work)
                    or exact_estimate != anywhere_rule.exact_verification_limit
                ):
                    raise ValueError("anywhere workflow estimates are inconsistent")
            else:
                expected_calendar = sum(
                    0
                    if search_leg.date_mode == DateMode.EXACT.value
                    else ((search_leg.departure_end_date - search_leg.departure_date).days + 1)
                    * len(search_leg.route_pairs)
                    for search_leg in search_legs
                )
                expected_exact = sum(
                    (
                        1
                        if search_leg.date_mode == DateMode.EXACT.value
                        else (search_leg.departure_end_date - search_leg.departure_date).days + 1
                    )
                    * len(search_leg.route_pairs)
                    for search_leg in search_legs
                )
                if split_requested:
                    split_surface = 0
                    for leg_ordinal in range(len(plan_legs)):
                        split_leg = _finite_search_leg_from_snapshots(
                            ordinal=leg_ordinal,
                            scope_leg=_mapping(scope_legs[leg_ordinal], "scope leg"),
                            intent_leg=_mapping(plan_legs[leg_ordinal], "intent leg"),
                        )
                        split_surface += len(split_leg.route_pairs) * (
                            (split_leg.departure_end_date - split_leg.departure_date).days + 1
                        )
                    expected_exact += split_surface * max_split_hubs_per_leg * 2
                if hidden_city_rule is not None:
                    hidden_discovery_rule = hidden_city_rule.discovery_rule
                    expected_calendar += max(
                        hidden_discovery_rule.max_destination_seeds,
                        len(hidden_discovery_rule.origins)
                        * len(hidden_discovery_rule.discovery_source_ids),
                    )
                    expected_exact += hidden_discovery_rule.exact_verification_limit
                if calendar_estimate != expected_calendar or exact_estimate != expected_exact:
                    raise ValueError("per-leg workflow estimates are inconsistent")
            hidden_calendar_limit = (
                0
                if hidden_city_rule is None
                else max(
                    hidden_city_rule.discovery_rule.max_destination_seeds,
                    len(hidden_city_rule.discovery_rule.origins)
                    * len(hidden_city_rule.discovery_rule.discovery_source_ids),
                )
            )
            hidden_exact_limit = (
                0
                if hidden_city_rule is None
                else hidden_city_rule.discovery_rule.exact_verification_limit
            )
            effective_strategies = requested_strategies or (RouteStrategy.THROUGH_TICKET,)
            split_bindings = (
                _split_bindings_from_confirmed_records(
                    await self._evidence.list_confirmed_evidence(household_id, run_id),
                    trip_shape=trip_shape,
                    search_legs=_composition_search_legs_from_parts(
                        trip_shape,
                        search_legs,
                        return_date,
                    ),
                    max_hubs_per_leg=max_split_hubs_per_leg,
                    adults=adults,
                    children=children,
                    infants=infants,
                    currency=currency,
                )
                if split_requested
                else ()
            )
            workflow = _Workflow(
                trip_shape=trip_shape,
                search_legs=search_legs,
                origin=origin,
                destination=destination,
                route_pairs=route_pairs,
                date_mode=scope_constraint.mode.value,
                departure_date=departure,
                departure_end_date=departure_end,
                return_date=return_date,
                adults=adults,
                children=children,
                infants=infants,
                currency=currency,
                one_way=trip_shape is TripShape.ONE_WAY,
                strategies=effective_strategies,
                analysis_modes=approved_analysis_modes,
                exact_limit=exact_estimate - hidden_exact_limit,
                calendar_limit=calendar_estimate - hidden_calendar_limit,
                start_attempts=start_attempts,
                poll_rounds=poll_rounds,
                attempts_per_poll=attempts_per_poll,
                approved_provider_rpm=_positive_int(
                    cost.get("requests_per_minute"),
                    "requests_per_minute",
                ),
                composition_rule_version=composition_rule_version,
                max_split_hubs_per_leg=max_split_hubs_per_leg,
                split_bindings=split_bindings,
                anywhere_rule=anywhere_rule,
                anywhere_signals=anywhere_signals,
                hidden_city_rule=hidden_city_rule,
            )
            if hidden_city_rule is not None:
                hidden_records = await self._validated_durable_hidden_city_records(
                    run,
                    workflow,
                )
                workflow = replace(
                    workflow,
                    hidden_city_signals=hidden_records[
                        : hidden_city_rule.discovery_rule.exact_verification_limit
                    ],
                )
        except (KeyError, IndexError, TypeError, ValueError):
            workflow = None
        if workflow is None:
            raise AgentExecutionError("agent_plan_snapshot_invalid")
        return workflow

    async def _validated_anywhere_scope_snapshot(
        self,
        snapshot: AgentRunScopeSnapshotRecord,
        *,
        run: AgentPlanRunRecord,
        rule: _AnywhereRule,
        currency: str,
    ) -> tuple[AgentDiscoverySignalRecord, ...]:
        payload = snapshot.snapshot
        origins = tuple(
            _iata(value, "snapshot origin")
            for value in _sequence(payload["origins"], "snapshot origins")
        )
        destinations = tuple(
            _iata(value, "snapshot destination")
            for value in _sequence(payload["destinations"], "snapshot destinations")
        )
        source_ids = tuple(
            UUID(_text(value, "snapshot source signal id"))
            for value in _sequence(payload["source_signal_ids"], "snapshot source signal ids")
        )
        if (
            snapshot.household_id != run.household_id
            or snapshot.run_id != run.id
            or not _durable_scope_snapshot(snapshot, run)
            or origins != rule.origins
            or not destinations
            or len(destinations) != len(set(destinations))
            or len(destinations) > rule.exact_verification_limit
            or len(source_ids) != len(destinations)
            or len(source_ids) != len(set(source_ids))
            or _text(payload["catalog_checksum"], "snapshot catalog checksum")
            != rule.catalog_checksum
            or _text(payload["taxonomy_version"], "snapshot taxonomy version")
            != rule.taxonomy_version
            or _text(payload["coverage"], "snapshot coverage") != rule.coverage
            or snapshot.fingerprint != _scope_snapshot_fingerprint(payload)
        ):
            raise ValueError("anywhere scope snapshot is not rule-bound")
        eligible = dict(rule.eligible_destination_countries)
        stored = await self._evidence.list_discovery_signals(snapshot.household_id, snapshot.run_id)
        stored_by_id = {signal.id: signal for signal in stored}
        selected: list[AgentDiscoverySignalRecord] = []
        for source_id, destination in zip(source_ids, destinations, strict=True):
            signal = stored_by_id.get(source_id)
            if (
                signal is None
                or signal.household_id != snapshot.household_id
                or signal.run_id != snapshot.run_id
                or signal.provider_id != _PROVIDER_ID
                or signal.origin not in origins
                or signal.destination != destination
                or signal.destination not in eligible
                or not rule.date_start <= signal.departure_date <= rule.date_end
                or signal.return_date is not None
                or signal.amount_minor is None
                or signal.currency != currency
                or signal.passengers != 1
                or signal.passenger_basis is not PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
                or signal.source_kind is not DiscoverySource.HOT_OFFER
                or signal.freshness is not Freshness.API_CACHED
                or _text(signal.signal_evidence.get("source_id"), "source_id")
                not in rule.discovery_source_ids
                or signal.fingerprint != _evidence_fingerprint(signal.id)
                or not _durable_provider_observation(signal, run)
            ):
                raise ValueError("anywhere scope source signal is not rule-bound")
            selected.append(signal)
        return tuple(selected)

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


def _anywhere_rule_from_snapshot(
    value: Mapping[str, object],
    *,
    first_plan_leg: Mapping[str, object],
    origin_codes: tuple[str, ...],
    date_start: date,
    date_end: date,
    coverage: str,
    require_anywhere_intent: bool = True,
) -> _AnywhereRule:
    if require_anywhere_intent and _intent_scope_identity(
        first_plan_leg,
        "destination",
    ) != (LocationScopeKind.ANYWHERE.value, None):
        raise ValueError("anywhere rule differs from intent")
    origins = tuple(
        _iata(item, "anywhere origin")
        for item in _sequence(value["origin_airports"], "anywhere origins")
    )
    rule_date_start = date.fromisoformat(_text(value["date_start"], "anywhere date_start"))
    rule_date_end = date.fromisoformat(_text(value["date_end"], "anywhere date_end"))
    allowed = _country_codes(value.get("allowed_country_codes", ()), "allowed countries")
    excluded = _country_codes(value.get("excluded_country_codes", ()), "excluded countries")
    sources = tuple(
        _text(item, "anywhere discovery source")
        for item in _sequence(value["discovery_source_ids"], "anywhere discovery sources")
    )
    max_destination_seeds = _positive_int(
        value["max_destination_seeds"],
        "max_destination_seeds",
    )
    exact_verification_limit = _positive_int(
        value["exact_verification_limit"],
        "exact_verification_limit",
    )
    raw_eligible = value["eligible_destination_countries"]
    if isinstance(raw_eligible, Mapping):
        eligible_items = tuple(raw_eligible.items())
    else:
        eligible_items = tuple(
            (
                _mapping(item, "eligible destination")["code"],
                _mapping(item, "eligible destination")["country_code"],
            )
            for item in _sequence(raw_eligible, "eligible destinations")
        )
    eligible = tuple(
        (
            _iata(code, "eligible destination code"),
            _country_code(country_code, "eligible destination country"),
        )
        for code, country_code in eligible_items
    )
    eligible_codes = tuple(code for code, _country in eligible)
    if (
        origins != origin_codes
        or len(set(origins)) != len(origins)
        or rule_date_start != date_start
        or rule_date_end != date_end
        or inclusive_month_count(rule_date_start, rule_date_end) > MAX_ANYWHERE_DISCOVERY_MONTHS
        or set(allowed) & set(excluded)
        or sources != ("aviasales_hot_offers",)
        or exact_verification_limit > max_destination_seeds
        or max_destination_seeds < len(origins) * len(sources)
        or coverage not in {"quick", "full"}
        or not eligible
        or len(set(eligible_codes)) != len(eligible_codes)
        or any(code in origins for code in eligible_codes)
        or any(allowed and country not in allowed for _code, country in eligible)
        or any(country in excluded for _code, country in eligible)
    ):
        raise ValueError("anywhere rule is not a bounded immutable rule")
    return _AnywhereRule(
        origins=origins,
        date_start=rule_date_start,
        date_end=rule_date_end,
        discovery_source_ids=sources,
        max_destination_seeds=max_destination_seeds,
        exact_verification_limit=exact_verification_limit,
        catalog_checksum=_text(value["catalog_checksum"], "anywhere catalog checksum"),
        taxonomy_version=_text(value["taxonomy_version"], "anywhere taxonomy version"),
        coverage=coverage,
        eligible_destination_countries=eligible,
    )


def _hidden_city_rule_from_plan(
    value: Mapping[str, object],
    *,
    plan_leg_index: int,
    origin_codes: tuple[str, ...],
    desired_airports: tuple[str, ...],
    date_start: date,
    date_end: date,
    coverage: str,
    origin_catalog_checksum: str,
) -> _HiddenCityRule:
    version = _text(value["version"], "hidden-city rule version")
    stored_leg_index = _non_negative_int(
        value["plan_leg_index"],
        "hidden-city plan leg index",
    )
    stored_desired_airports = tuple(
        _iata(item, "hidden-city desired airport")
        for item in _sequence(
            value["desired_airports"],
            "hidden-city desired airports",
        )
    )
    normalized_origins = tuple(dict.fromkeys(origin_codes))
    normalized_desired = tuple(dict.fromkeys(desired_airports))
    discovery = _anywhere_rule_from_snapshot(
        _mapping(value["discovery"], "hidden-city discovery rule"),
        first_plan_leg={},
        origin_codes=normalized_origins,
        date_start=date_start,
        date_end=date_end,
        coverage=coverage,
        require_anywhere_intent=False,
    )
    eligible = {code for code, _country in discovery.eligible_destination_countries}
    if (
        version != "hidden-city-search-v1"
        or stored_leg_index != plan_leg_index
        or stored_desired_airports != normalized_desired
        or not stored_desired_airports
        or len(set(stored_desired_airports)) != len(stored_desired_airports)
        or eligible.intersection(stored_desired_airports)
        or discovery.catalog_checksum != origin_catalog_checksum
    ):
        raise ValueError("hidden-city rule is not bound to the final finite leg")
    return _HiddenCityRule(
        version=version,
        plan_leg_index=stored_leg_index,
        desired_airports=stored_desired_airports,
        discovery_rule=discovery,
    )


def _country_codes(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an ordered collection")
    codes = tuple(_country_code(item, field_name) for item in value)
    if len(codes) != len(set(codes)):
        raise ValueError(f"{field_name} must be unique")
    return codes


def _country_code(value: object, field_name: str) -> str:
    code = _text(value, field_name).upper()
    if len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ValueError(f"{field_name} must be an ISO alpha-2 code")
    return code


def _scope_snapshot_fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _mutable_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return _fingerprint(encoded)


def _mutable_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _mutable_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_json(item) for item in value]
    return value


def _validated_provider_outcome(
    *,
    run: AgentPlanRunRecord,
    operation: AgentRunOperationRecord,
    private_continuation: Mapping[str, object] | None,
    workflow: _Workflow,
    outcome: object,
    observed_by: datetime,
    anywhere_remaining_capacity: int | None = None,
    anywhere_existing_candidate_bindings: frozenset[tuple[str, str, str]] = frozenset(),
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

        if operation.kind in {
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.HIDDEN_CITY_DISCOVERY,
        }:
            if type(outcome) is not tuple or not all(
                isinstance(signal, DiscoverySignal) for signal in outcome
            ):
                raise TypeError("anywhere discovery returned an invalid outcome")
            return _validated_anywhere_signals(
                cast(tuple[DiscoverySignal, ...], outcome),
                run=run,
                operation=operation,
                workflow=workflow,
                observed_by=observed_by,
                remaining_capacity=anywhere_remaining_capacity,
                existing_candidate_bindings=anywhere_existing_candidate_bindings,
            )

        if operation.kind is AgentOperationKind.EXACT_POLL:
            if not isinstance(outcome, ExactPollOutcome):
                raise TypeError("exact poll returned an invalid outcome")
            continuation = _continuation_from_private(private_continuation)
            if outcome.next_cursor < continuation.last_update_timestamp:
                raise ValueError("exact poll cursor did not advance")
            if outcome.not_modified and outcome.next_cursor != continuation.last_update_timestamp:
                raise ValueError("not-modified exact poll changed cursor")
            if len(outcome.evidence) > _EXACT_POLL_EVIDENCE_LIMIT:
                raise ValueError("exact poll exceeded its provider result limit")
            validated_evidence = _validated_exact_evidence(
                outcome.evidence,
                run=run,
                continuation=continuation,
                observed_by=observed_by,
            )
            validated_ids = {item.id for item in validated_evidence}
            return ExactPollOutcome(
                evidence=validated_evidence,
                next_cursor=outcome.next_cursor,
                complete=outcome.complete,
                not_modified=outcome.not_modified,
                booking_descriptors=tuple(
                    descriptor
                    for descriptor in outcome.booking_descriptors
                    if descriptor.evidence_id in validated_ids
                ),
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
    params = _calendar_params(operation.immutable_input, workflow)
    requested_date = params.depart_from
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
            signal.origin != params.origin.code
            or signal.destination != params.destination.code
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


def _validated_anywhere_signals(
    signals: tuple[DiscoverySignal, ...],
    *,
    run: AgentPlanRunRecord,
    operation: AgentRunOperationRecord,
    workflow: _Workflow,
    observed_by: datetime,
    remaining_capacity: int | None,
    existing_candidate_bindings: frozenset[tuple[str, str, str]],
) -> tuple[DiscoverySignal, ...]:
    rule = _operation_discovery_rule(workflow, operation.kind)
    params = _anywhere_params(
        operation.immutable_input,
        workflow,
        rule=rule,
    )
    eligible = dict(rule.eligible_destination_countries)
    if type(remaining_capacity) is not int or remaining_capacity < 1:
        raise ValueError("anywhere discovery requires positive remaining capacity")
    source_id = _text(operation.immutable_input["source_id"], "source_id")
    best_by_destination: dict[str, DiscoverySignal] = {}
    id_bindings: dict[UUID, tuple[str, str, date, date | None]] = {}
    for signal in signals:
        binding = (
            signal.origin,
            signal.destination,
            signal.departure_date,
            signal.return_date,
        )
        if (
            signal.id != _hot_offer_discovery_signal_id(operation.id, signal)
            or signal.provider_id != _PROVIDER_ID
            or signal.origin != params.origin.code
            or signal.observed_amount.currency != workflow.currency
            or signal.passengers != 1
            or signal.source_kind is not DiscoverySource.HOT_OFFER
            or not _provider_response_observation(signal.observed_at, run, observed_by)
        ):
            raise ValueError("anywhere discovery signal is not request-bound")
        previous_binding = id_bindings.setdefault(signal.id, binding)
        if previous_binding != binding:
            raise ValueError("anywhere discovery identity is ambiguous")
        if (
            signal.destination not in eligible
            or not (params.date_from <= signal.departure_date <= params.date_to)
            or signal.return_date is not None
            or (signal.origin, source_id, signal.destination) in existing_candidate_bindings
        ):
            continue
        existing = best_by_destination.get(signal.destination)
        if existing is None or _calendar_signal_order(signal) < _calendar_signal_order(existing):
            best_by_destination[signal.destination] = signal
    return tuple(
        sorted(
            best_by_destination.values(),
            key=lambda signal: (
                signal.observed_amount.minor_units,
                -signal.observed_at.timestamp(),
                signal.destination,
                str(signal.id),
            ),
        )[:remaining_capacity]
    )


def _calendar_signal_order(signal: DiscoverySignal) -> tuple[int, float, str]:
    return (
        signal.observed_amount.minor_units,
        -signal.observed_at.timestamp(),
        str(signal.id),
    )


def _stored_discovery_order(
    signal: AgentDiscoverySignalRecord,
) -> tuple[int, float, str, str, str, str]:
    return (
        signal.amount_minor if signal.amount_minor is not None else 2**63 - 1,
        -signal.observed_at.timestamp(),
        signal.destination,
        signal.origin,
        _text(signal.signal_evidence.get("source_id"), "source_id"),
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


def _hot_offer_discovery_signal_id(
    evidence_namespace: UUID,
    signal: DiscoverySignal,
) -> UUID:
    identity = "|".join(
        (
            _PROVIDER_ID,
            "hot_offer",
            signal.origin,
            signal.destination,
            signal.departure_date.isoformat(),
            signal.return_date.isoformat() if signal.return_date is not None else "",
            str(signal.observed_amount.minor_units),
            signal.observed_amount.currency,
            str(signal.passengers),
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


def _provider_response_observation(
    observed_at: datetime,
    run: AgentPlanRunRecord,
    observed_by: datetime,
) -> bool:
    """Bind cached provider evidence to this response without claiming price liveness."""

    normalized = observed_at.astimezone(UTC)
    response_time = observed_by.astimezone(UTC)
    lower_bound = max(
        run.created_at.astimezone(UTC),
        response_time - _PROVIDER_CLOCK_SKEW,
    )
    return lower_bound <= normalized <= response_time + _PROVIDER_CLOCK_SKEW


def _durable_provider_observation(
    record: AgentDiscoverySignalRecord,
    run: AgentPlanRunRecord,
) -> bool:
    """Revalidate stored evidence against its durable ingest time, not wall clock time."""

    observed_at = record.observed_at.astimezone(UTC)
    created_at = record.created_at.astimezone(UTC)
    run_start = run.created_at.astimezone(UTC)
    run_deadline = run.deadline_at.astimezone(UTC)
    lower_bound = max(run_start, created_at - _PROVIDER_CLOCK_SKEW)
    return (
        run_start <= created_at <= run_deadline + _PROVIDER_CLOCK_SKEW
        and lower_bound <= observed_at <= created_at + _PROVIDER_CLOCK_SKEW
    )


def _durable_scope_snapshot(
    snapshot: AgentRunScopeSnapshotRecord,
    run: AgentPlanRunRecord,
) -> bool:
    if snapshot.created_at.tzinfo is None or snapshot.created_at.utcoffset() is None:
        return False
    created_at = snapshot.created_at.astimezone(UTC)
    return run.created_at.astimezone(UTC) <= created_at <= run.deadline_at.astimezone(UTC)


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
    try:
        leg_ordinal = _non_negative_int(
            signal.signal_evidence.get("leg_ordinal", 0),
            "leg_ordinal",
        )
    except (TypeError, ValueError):
        return False
    search_leg = next(
        (leg for leg in workflow.search_legs if leg.ordinal == leg_ordinal),
        None,
    )
    return (
        search_leg is not None
        and _RoutePair(signal.origin, signal.destination) in search_leg.route_pairs
        and search_leg.departure_date <= signal.departure_date <= search_leg.departure_end_date
        and signal.return_date == search_leg.return_date
        and (signal.return_date is None or signal.departure_date <= signal.return_date)
        and signal.currency == workflow.currency
        and signal.passengers == 1
        and signal.passenger_basis is PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
    )


def _expected_coverage_is_confirmed(
    workflow: _Workflow,
    operations: Sequence[AgentRunOperationRecord],
) -> bool:
    if workflow.anywhere_rule is not None:
        expected = {
            _ExactBinding(
                leg_ordinal=0,
                origin=signal.origin,
                destination=signal.destination,
                departure_date=signal.departure_date,
                return_date=workflow.return_date,
                adults=workflow.adults,
                children=workflow.children,
                infants=workflow.infants,
                passengers=workflow.passengers,
                currency=workflow.currency,
            )
            for signal in workflow.anywhere_signals
        }
    else:
        expected = {
            _ExactBinding(
                leg_ordinal=search_leg.ordinal,
                origin=route_pair.origin,
                destination=route_pair.destination,
                departure_date=search_leg.departure_date + timedelta(days=offset),
                return_date=search_leg.return_date,
                adults=workflow.adults,
                children=workflow.children,
                infants=workflow.infants,
                passengers=workflow.passengers,
                currency=workflow.currency,
            )
            for search_leg in workflow.search_legs
            for route_pair in search_leg.route_pairs
            for offset in range(
                (search_leg.departure_end_date - search_leg.departure_date).days + 1
            )
        }
    confirmed_root_ids = {
        operation.logical_root_operation_id
        for operation in operations
        if operation.kind is AgentOperationKind.EXACT_POLL
        and operation.status is AgentOperationStatus.SUCCEEDED
        and operation.result_type is AgentOperationResultType.CONFIRMED_OFFER
        and operation.logical_root_operation_id is not None
    }
    confirmed: set[_ExactBinding] = set()
    for operation in operations:
        if operation.kind is not AgentOperationKind.EXACT_START:
            continue
        if operation.id not in confirmed_root_ids:
            continue
        try:
            confirmed.add(_exact_binding_from_immutable(operation.immutable_input, workflow))
        except (AgentExecutionError, KeyError, TypeError, ValueError):
            return False
    return bool(expected) and expected <= confirmed


def _evidence_allowed_by_strategy(
    workflow: _Workflow,
    evidence: ConfirmedOfferEvidence,
) -> bool:
    direct_only = (
        RouteStrategy.DIRECT in workflow.strategies
        and RouteStrategy.THROUGH_TICKET not in workflow.strategies
    )
    return not direct_only or _confirmed_stop_count(evidence) == 0


def _confirmed_itinerary_evidence(
    evidence: ConfirmedOfferEvidence,
    *,
    leg_ordinal: int = 0,
    search_role: str = "base",
    split_source_evidence_id: UUID | None = None,
    split_component_ordinal: int | None = None,
    passenger_mix: PassengerMix | None = None,
    hidden_city_candidate: HiddenCityCandidate | None = None,
) -> dict[str, object]:
    if search_role not in {"base", "split_component", "hidden_city"}:
        raise ValueError("unsupported evidence search role")
    if search_role == "base" and (
        split_source_evidence_id is not None or split_component_ordinal is not None
    ):
        raise ValueError("base evidence cannot reference a split source")
    if search_role == "split_component" and (
        split_source_evidence_id is None or split_component_ordinal not in {0, 1}
    ):
        raise ValueError("split component evidence requires source and ordinal")
    if (search_role == "hidden_city") != (hidden_city_candidate is not None):
        raise ValueError("hidden-city evidence requires its typed candidate")
    normalized_passenger_mix = passenger_mix or evidence.passenger_mix
    if normalized_passenger_mix is None:
        raise ValueError("confirmed evidence passenger mix is missing")
    if evidence.ticket_shape is None or evidence.checked_baggage is None:
        raise ValueError("confirmed evidence ticket facts are missing")
    itinerary: dict[str, object] = {
        "leg_ordinal": leg_ordinal,
        "search_role": search_role,
        "origin": evidence.origin,
        "destination": evidence.destination,
        "departure_date": evidence.departure_date.isoformat(),
        "return_date": (
            evidence.return_date.isoformat() if evidence.return_date is not None else None
        ),
        "passenger_mix": {
            "adults": normalized_passenger_mix.adults,
            "children": normalized_passenger_mix.children,
            "infants": normalized_passenger_mix.infants,
        },
        "price_basis": evidence.price_basis.value,
        "ticket_shape": evidence.ticket_shape.value,
        "checked_baggage": evidence.checked_baggage.value,
        "baggage_summary": evidence.baggage_summary,
        "segments": [
            {
                "segment_ref": evidence.segment_ids[index],
                "origin": segment.origin,
                "destination": segment.destination,
                "depart_at": segment.depart_at,
                "arrive_at": segment.arrive_at,
                "depart_at_utc": (
                    segment.depart_at_utc.isoformat() if segment.depart_at_utc is not None else None
                ),
                "arrive_at_utc": (
                    segment.arrive_at_utc.isoformat() if segment.arrive_at_utc is not None else None
                ),
                "carrier": segment.airline_code,
                "flight_number": segment.flight_number,
            }
            for index, segment in enumerate(evidence.segments)
        ],
        "seller": evidence.seller_name,
        "ticket_structure": "provider_ticket",
    }
    if evidence.provider_airport_changes:
        itinerary["provider_airport_changes"] = [
            [from_airport, to_airport]
            for from_airport, to_airport in evidence.provider_airport_changes
        ]
    if hidden_city_candidate is not None:
        itinerary.update(
            {
                "hidden_city_desired_airport": hidden_city_candidate.desired_airport,
                "hidden_city_ticketed_destination": (hidden_city_candidate.ticketed_destination),
                "hidden_city_actionability": hidden_city_candidate.actionability.value,
                "hidden_city_warning_version": HIDDEN_CITY_WARNING_VERSION,
                "booking_action_available": False,
                "watch_available": False,
            }
        )
    if split_source_evidence_id is not None:
        itinerary["split_source_evidence_id"] = str(split_source_evidence_id)
    if split_component_ordinal is not None:
        itinerary["split_component_ordinal"] = split_component_ordinal
    stops = _confirmed_stop_count(evidence)
    if stops is not None:
        itinerary["stops"] = stops
    return itinerary


def _confirmed_history_series_hash(
    evidence: ConfirmedOfferEvidence,
    immutable_input: Mapping[str, object],
) -> str:
    departure_date = date.fromisoformat(_text(immutable_input["departure_date"], "departure_date"))
    return_raw = immutable_input.get("return_date")
    return_date = (
        None if return_raw is None else date.fromisoformat(_text(return_raw, "return_date"))
    )
    origin = _iata(immutable_input["origin"], "origin")
    destination = _iata(immutable_input["destination"], "destination")
    search_role = _text(immutable_input.get("search_role", "base"), "search_role")
    if search_role == "hidden_city":
        ticket_structure = TicketStructure.HIDDEN_CITY
        risk_class = RiskClass.HIGH
    elif search_role == "split_component":
        ticket_structure = TicketStructure.SPLIT_TICKET
        risk_class = RiskClass.HIGH
    else:
        ticket_structure = TicketStructure.SINGLE_TICKET
        risk_class = (
            RiskClass.LOW
            if evidence.protection_status is ProtectionStatus.EXPLICITLY_PROTECTED
            else RiskClass.HIGH
            if evidence.protection_status is ProtectionStatus.SELF_TRANSFER
            else RiskClass.MEDIUM
        )
    checked_baggage = evidence.checked_baggage
    if checked_baggage is None:
        raise AgentExecutionError("agent_confirmed_evidence_invalid")
    baggage_key = BaggageKey(
        state=checked_baggage,
        pieces=0 if checked_baggage is CheckedBaggageState.NOT_INCLUDED else None,
        weight_kg=(Decimal("0") if checked_baggage is CheckedBaggageState.NOT_INCLUDED else None),
    )
    ordered_legs = [
        HistoryLegKey(
            origin=origin,
            destination=destination,
            date_start=departure_date,
            date_end=departure_date,
        )
    ]
    stay = None
    trip_shape = TripShape.ONE_WAY
    if return_date is not None:
        ordered_legs.append(
            HistoryLegKey(
                origin=destination,
                destination=origin,
                date_start=return_date,
                date_end=return_date,
            )
        )
        nights = (return_date - departure_date).days
        stay = StayWindow(minimum_nights=nights, maximum_nights=nights)
        trip_shape = TripShape.ROUND_TRIP
    return history_series_hash(
        HistorySeriesKey(
            ordered_leg_keys=tuple(ordered_legs),
            trip_shape=trip_shape,
            stay=stay,
            cabin=_text(immutable_input["cabin"], "cabin"),
            passenger_mix=PassengerMix(
                adults=_positive_int(immutable_input["adults"], "adults"),
                children=_non_negative_int(immutable_input["children"], "children"),
                infants=_non_negative_int(immutable_input["infants"], "infants"),
            ),
            ticket_structure=ticket_structure,
            risk_class=risk_class,
            baggage_key=baggage_key,
            currency_basis=CurrencyBasis(
                provider_currency=evidence.total_amount.currency,
                comparison_currency=evidence.total_amount.currency,
                fx_source=None,
            ),
            aggregation_mode=HistoryAggregationMode.MARKET_MINIMUM,
            product_key=None,
        )
    )


def _history_observation_from_record(
    record: AgentConfirmedOfferEvidenceRecord,
) -> HistoryObservation:
    if record.history_series_hash is None or record.amount_minor is None or record.currency is None:
        raise ValueError("confirmed evidence lacks comparable history facts")
    departure_date = date.fromisoformat(
        _text(record.itinerary_evidence["departure_date"], "departure_date")
    )
    return HistoryObservation(
        series_hash=record.history_series_hash,
        amount=Money(record.amount_minor, record.currency),
        observed_at=record.observed_at,
        departure_date=departure_date,
        timezone="UTC",
    )


def _bound_analysis_modes(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> tuple[AnalysisMode, ...]:
    version = immutable_input.get("version")
    if version == "task9-v1":
        if (
            set(immutable_input) != {"analysis_mode", "version"}
            or immutable_input.get("analysis_mode") != "minimal_report"
            or workflow.analysis_modes
        ):
            raise AgentExecutionError("agent_operation_input_invalid")
        return ()
    raw_modes = immutable_input.get("analysis_modes")
    if (
        version != "fare-analysis-v1"
        or set(immutable_input) != {"analysis_modes", "version"}
        or isinstance(raw_modes, (str, bytes, bytearray))
        or not isinstance(raw_modes, Sequence)
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    try:
        bound_modes = tuple(AnalysisMode(_text(value, "analysis mode")) for value in raw_modes)
    except (TypeError, ValueError) as error:
        raise AgentExecutionError("agent_operation_input_invalid") from error
    if bound_modes != workflow.analysis_modes:
        raise AgentExecutionError("agent_operation_input_invalid")
    return bound_modes


def _analysis_scope_supported(workflow: _Workflow) -> bool:
    return (
        workflow.trip_shape in {TripShape.ONE_WAY, TripShape.ROUND_TRIP}
        and workflow.composition_rule_version is None
    )


def _validate_existing_analysis_snapshot(
    snapshot: AgentAnalysisSnapshotRecord,
    *,
    workflow: _Workflow,
    bound_modes: tuple[AnalysisMode, ...],
    confirmed: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> None:
    payload = snapshot.analysis
    expected_modes = tuple(mode.value for mode in bound_modes)
    raw_modes = payload.get("requested_modes")
    if (
        payload.get("version") != "fare-analysis-snapshot-v1"
        or payload.get("source") != "confirmed_exact_history"
        or payload.get("aggregation_mode") != "market_minimum"
        or isinstance(raw_modes, (str, bytes, bytearray))
        or not isinstance(raw_modes, Sequence)
        or tuple(raw_modes) != expected_modes
        or type(payload.get("source_evidence_truncated")) is not bool
    ):
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")

    supported = _analysis_scope_supported(workflow)
    if not supported:
        allowed_ids = {
            record.id
            for record in confirmed
            if record.source == "exact_search"
            and record.itinerary_evidence.get("search_role", "base") != "hidden_city"
        }
        if (
            payload.get("scope_status") != "unsupported_trip_structure"
            or payload.get("scope_reason") != "full_itinerary_history_unavailable"
            or payload.get("trip_shape") != workflow.trip_shape.value
            or not snapshot.source_evidence_ids
            or not set(snapshot.source_evidence_ids) <= allowed_ids
            or any(
                payload.get(key) is not None
                for key in (
                    "primary_evidence_id",
                    "history_series_hash",
                    "buy_timing",
                    "anomaly",
                    "currency_comparison",
                    "watch_action",
                )
            )
        ):
            raise AgentEvidenceError("agent_analysis_snapshot_conflict")
        return

    if (
        payload.get("scope_status") != "supported"
        or payload.get("scope_reason") is not None
        or payload.get("trip_shape") != workflow.trip_shape.value
    ):
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")
    try:
        primary_id = UUID(_text(payload["primary_evidence_id"], "primary_evidence_id"))
    except (KeyError, TypeError, ValueError) as error:
        raise AgentEvidenceError("agent_analysis_snapshot_conflict") from error
    primary = next((record for record in confirmed if record.id == primary_id), None)
    if (
        primary is None
        or primary.id not in snapshot.source_evidence_ids
        or primary.source != "exact_search"
        or primary.itinerary_evidence.get("search_role", "base") != "base"
        or primary.amount_minor is None
        or primary.currency is None
        or primary.history_series_hash is None
    ):
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")
    try:
        expected = _analysis_primary_payload(primary, workflow)
    except (KeyError, TypeError, ValueError) as error:
        raise AgentEvidenceError("agent_analysis_snapshot_conflict") from error
    if any(payload.get(key) != value for key, value in expected.items()):
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")
    history_count = payload.get("history_observation_count")
    history_fingerprint = payload.get("history_evidence_fingerprint")
    if (
        type(history_count) is not int
        or history_count < 0
        or not _is_sha256_fingerprint(history_fingerprint)
    ):
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")

    result_fields = {
        AnalysisMode.BUY_TIMING: "buy_timing",
        AnalysisMode.ERROR_FARE: "anomaly",
        AnalysisMode.CURRENCY_COMPARE: "currency_comparison",
    }
    for mode, field_name in result_fields.items():
        value = payload.get(field_name)
        if (mode in bound_modes) != isinstance(value, Mapping):
            raise AgentEvidenceError("agent_analysis_snapshot_conflict")
    if AnalysisMode.BUY_TIMING in bound_modes:
        buy_timing = cast(Mapping[str, object], payload["buy_timing"])
        watch_action = payload.get("watch_action")
        if not isinstance(watch_action, Mapping):
            raise AgentEvidenceError("agent_analysis_snapshot_conflict")
        expected_watch = {
            "available": buy_timing.get("watch_action_available"),
            "origin": expected["origin"],
            "destination": expected["destination"],
            "departure_date": expected["departure_date"],
            "return_date": expected["return_date"],
            "passengers": expected["passengers"],
            "currency": cast(Mapping[str, object], expected["primary_amount"])["currency"],
        }
        if dict(watch_action) != expected_watch:
            raise AgentEvidenceError("agent_analysis_snapshot_conflict")
    elif payload.get("watch_action") is not None:
        raise AgentEvidenceError("agent_analysis_snapshot_conflict")


def _analysis_primary_payload(
    primary: AgentConfirmedOfferEvidenceRecord,
    workflow: _Workflow,
) -> dict[str, object]:
    if primary.amount_minor is None or primary.currency is None:
        raise ValueError("analysis primary evidence has no amount")
    origin = _iata(primary.itinerary_evidence["origin"], "analysis origin")
    destination = _iata(
        primary.itinerary_evidence["destination"],
        "analysis destination",
    )
    departure_date = date.fromisoformat(
        _text(
            primary.itinerary_evidence["departure_date"],
            "analysis departure_date",
        )
    )
    return_raw = primary.itinerary_evidence.get("return_date")
    return_date = (
        None
        if return_raw is None
        else date.fromisoformat(_text(return_raw, "analysis return_date"))
    )
    return {
        "primary_evidence_id": str(primary.id),
        "history_series_hash": primary.history_series_hash,
        "provider_id": primary.provider_id,
        "freshness": primary.freshness.value,
        "passengers": primary.passengers,
        "passenger_basis": primary.passenger_basis.value,
        "primary_amount": {
            "minor_units": primary.amount_minor,
            "currency": primary.currency,
        },
        "origin": origin,
        "destination": destination,
        "departure_date": departure_date.isoformat(),
        "return_date": return_date.isoformat() if return_date is not None else None,
        "observed_at": primary.observed_at.isoformat(),
        "trip_shape": workflow.trip_shape.value,
    }


def _valid_analysis_history_records(
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> tuple[tuple[AgentConfirmedOfferEvidenceRecord, ...], tuple[HistoryObservation, ...]]:
    valid_records: list[AgentConfirmedOfferEvidenceRecord] = []
    valid_history: list[HistoryObservation] = []
    for record in _market_minimum_history_records(records):
        try:
            observation = _history_observation_from_record(record)
        except (KeyError, TypeError, ValueError):
            continue
        valid_records.append(record)
        valid_history.append(observation)
    return tuple(valid_records), tuple(valid_history)


def _market_minimum_history_records(
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> tuple[AgentConfirmedOfferEvidenceRecord, ...]:
    best_by_run: dict[UUID, AgentConfirmedOfferEvidenceRecord] = {}
    for record in records:
        if record.amount_minor is None:
            continue
        existing = best_by_run.get(record.run_id)
        if existing is None or (
            record.amount_minor,
            record.observed_at,
            str(record.id),
        ) < (
            cast(int, existing.amount_minor),
            existing.observed_at,
            str(existing.id),
        ):
            best_by_run[record.run_id] = record
    return tuple(
        sorted(
            best_by_run.values(),
            key=lambda record: (record.observed_at, str(record.id)),
        )
    )


def _bounded_analysis_source_records(
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
    *,
    limit: int,
) -> tuple[AgentConfirmedOfferEvidenceRecord, ...]:
    if type(limit) is not int or limit <= 0:
        raise ValueError("analysis source limit must be positive")
    ordered = tuple(records)
    if len(ordered) <= limit:
        return ordered
    if limit == 1:
        return (ordered[-1],)
    indices = tuple(index * (len(ordered) - 1) // (limit - 1) for index in range(limit))
    return tuple(ordered[index] for index in indices)


def _history_evidence_fingerprint(
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> str:
    canonical = json.dumps(
        [
            {
                "amount_minor": record.amount_minor,
                "currency": record.currency,
                "evidence_id": str(record.id),
                "observed_at": record.observed_at.isoformat(),
                "run_id": str(record.run_id),
            }
            for record in records
        ],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_sha256_fingerprint(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        return False
    return all(character in "0123456789abcdef" for character in value[7:])


def _buy_timing_payload(assessment: BuyTimingAssessment) -> dict[str, object]:
    thresholds = assessment.thresholds
    return {
        "status": assessment.status.value,
        "watch_action_available": assessment.watch_action_available,
        "sample_count": assessment.sample_count,
        "distinct_dates": assessment.distinct_dates,
        "distinct_weeks": assessment.distinct_weeks,
        "history_span_days": assessment.history_span_days,
        "current_percentile": _optional_decimal_text(assessment.current_percentile),
        "twentieth_percentile_minor_units": (assessment.twentieth_percentile_minor_units),
        "median_minor_units": _optional_decimal_text(assessment.median_minor_units),
        "timezone": assessment.timezone,
        "days_to_departure_band": assessment.days_to_departure_band,
        "recommended_weekday": assessment.recommended_weekday,
        "weekday_savings_percent": _optional_decimal_text(assessment.weekday_savings_percent),
        "recommended_four_hour_bucket": assessment.recommended_four_hour_bucket,
        "four_hour_savings_percent": _optional_decimal_text(assessment.four_hour_savings_percent),
        "calculation_version": assessment.calculation_version,
        "thresholds": {
            "minimum_observations": thresholds.minimum_observations,
            "minimum_history_span_days": thresholds.minimum_history_span_days,
            "minimum_distinct_dates": thresholds.minimum_distinct_dates,
            "minimum_bucket_observations": thresholds.minimum_bucket_observations,
            "minimum_bucket_weeks": thresholds.minimum_bucket_weeks,
            "minimum_recommendation_difference_percent": _decimal_text(
                thresholds.minimum_recommendation_difference_percent
            ),
            "buy_now_percentile": _decimal_text(thresholds.buy_now_percentile),
        },
    }


def _anomaly_payload(assessment: AnomalyAssessment) -> dict[str, object]:
    thresholds = assessment.thresholds
    return {
        "status": assessment.status.value,
        "sample_count": assessment.sample_count,
        "distinct_dates": assessment.distinct_dates,
        "median_minor_units": _optional_decimal_text(assessment.median_minor_units),
        "ratio_to_median": _optional_decimal_text(assessment.ratio_to_median),
        "mad_minor_units": _optional_decimal_text(assessment.mad_minor_units),
        "robust_mad_z": _optional_decimal_text(assessment.robust_mad_z),
        "observed_range_minor_units": assessment.observed_range_minor_units,
        "detector_version": assessment.detector_version,
        "thresholds": {
            "minimum_observations": thresholds.minimum_observations,
            "minimum_distinct_dates": thresholds.minimum_distinct_dates,
            "maximum_median_ratio": _decimal_text(thresholds.maximum_median_ratio),
            "maximum_robust_mad_z": _decimal_text(thresholds.maximum_robust_mad_z),
        },
    }


def _optional_decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else _decimal_text(value)


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _confirmed_stop_count(evidence: ConfirmedOfferEvidence) -> int | None:
    directions = _confirmed_directions(evidence)
    if directions is None:
        return None
    return sum(max(0, len(direction) - 1) for direction in directions)


def _confirmed_directions(
    evidence: ConfirmedOfferEvidence,
) -> tuple[tuple[FlightSegmentSummary, ...], ...] | None:
    segments = evidence.segments
    if (
        not segments
        or segments[0].origin != evidence.origin
        or not _provider_airport_changes_are_bound(evidence)
    ):
        return None
    if evidence.return_date is None:
        if segments[-1].destination != evidence.destination:
            return None
        return (segments,)

    for boundary in range(1, len(segments)):
        outbound = segments[:boundary]
        inbound = segments[boundary:]
        if (
            outbound[-1].destination == evidence.destination
            and inbound[0].origin == evidence.destination
            and inbound[-1].destination == evidence.origin
        ):
            return (outbound, inbound)
    return None


def _provider_airport_changes_are_bound(evidence: ConfirmedOfferEvidence) -> bool:
    actual = tuple(
        (previous.destination, current.origin)
        for previous, current in pairwise(evidence.segments)
        if previous.destination != current.origin
    )
    return actual == evidence.provider_airport_changes


def _intent_scope_identity(leg: Mapping[str, object], key: str) -> tuple[str, str | None]:
    location = _mapping(leg[key], f"intent {key}")
    kind = LocationScopeKind(_text(location["kind"], f"intent {key} kind"))
    raw_value = location.get("value")
    value = _text(raw_value, f"intent {key} value") if raw_value is not None else None
    if kind is LocationScopeKind.ANYWHERE:
        if value is not None:
            raise ValueError(f"intent {key} anywhere value must be null")
    elif value is None:
        raise ValueError(f"intent {key} value is required")
    return kind.value, value


def _finite_frozen_airport_codes(
    leg: Mapping[str, object],
    intent_leg: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    if leg.get("anywhere") is not None and key == "destination":
        raise AgentExecutionError("agent_scope_unsupported")
    location = _mapping(leg[key], f"frozen {key}")
    requested = _mapping(location["requested_scope"], f"frozen {key} requested scope")
    kind = LocationScopeKind(_text(requested["kind"], f"frozen {key} requested kind"))
    raw_value = requested.get("value")
    requested_value = (
        _text(raw_value, f"frozen {key} requested value") if raw_value is not None else None
    )
    if kind is LocationScopeKind.ANYWHERE:
        raise AgentExecutionError("agent_scope_unsupported")
    if (kind.value, requested_value) != _intent_scope_identity(intent_leg, key):
        raise ValueError(f"frozen {key} requested scope differs from intent")
    codes = tuple(
        _iata(value, f"frozen {key} airport code")
        for value in _sequence(location["airport_codes"], f"frozen {key} airport codes")
    )
    if not codes or len(set(codes)) != len(codes):
        raise ValueError(f"frozen {key} airport codes must be non-empty and unique")
    _non_negative_int(
        location.get("nearby_radius_km", 0),
        f"frozen {key} nearby radius",
    )
    _text(location["catalog_checksum"], f"frozen {key} catalog checksum")
    _text(location["taxonomy_version"], f"frozen {key} taxonomy version")
    _text(location["commercial_provenance"], f"frozen {key} commercial provenance")
    if kind is LocationScopeKind.AIRPORT and requested_value not in codes:
        raise ValueError(f"frozen {key} requested scope differs from airport codes")
    return codes


def _finite_search_leg_from_snapshots(
    *,
    ordinal: int,
    scope_leg: Mapping[str, object],
    intent_leg: Mapping[str, object],
) -> _SearchLeg:
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("search leg ordinal must be a non-negative integer")
    if scope_leg.get("anywhere") is not None or scope_leg.get(
        "reciprocal_anywhere_return",
        False,
    ):
        raise AgentExecutionError("agent_multi_leg_anywhere_unsupported")
    origin_codes = _finite_frozen_airport_codes(scope_leg, intent_leg, "origin")
    destination_codes = _finite_frozen_airport_codes(scope_leg, intent_leg, "destination")
    scope_constraint = _constraint_from_snapshot(
        _mapping(scope_leg["date_constraint"], "date constraint")
    )
    intent_constraint = _constraint_from_snapshot(
        _mapping(intent_leg["date_constraint"], "intent date constraint")
    )
    if scope_constraint != intent_constraint:
        raise ValueError("intent and frozen date constraints differ")
    departure_date, departure_end_date = _constraint_bounds(scope_constraint)
    route_pairs = tuple(
        _RoutePair(origin, destination)
        for origin, destination in finite_route_pairs(origin_codes, destination_codes)
    )
    if not route_pairs:
        raise ValueError("search leg must contain a valid route pair")
    return _SearchLeg(
        ordinal=ordinal,
        route_pairs=route_pairs,
        date_mode=scope_constraint.mode.value,
        departure_date=departure_date,
        departure_end_date=departure_end_date,
    )


def _composition_search_legs(workflow: _Workflow) -> tuple[_SearchLeg, ...]:
    return _composition_search_legs_from_parts(
        workflow.trip_shape,
        workflow.search_legs,
        workflow.return_date,
    )


def _composition_search_legs_from_parts(
    trip_shape: TripShape,
    search_legs: tuple[_SearchLeg, ...],
    return_date: date | None,
) -> tuple[_SearchLeg, ...]:
    if trip_shape is not TripShape.ROUND_TRIP:
        return search_legs
    if len(search_legs) != 1 or return_date is None:
        raise AgentExecutionError("agent_plan_snapshot_invalid")
    native = search_legs[0]
    outbound = _SearchLeg(
        ordinal=0,
        route_pairs=native.route_pairs,
        date_mode=native.date_mode,
        departure_date=native.departure_date,
        departure_end_date=native.departure_end_date,
        return_date=None,
    )
    inbound = _SearchLeg(
        ordinal=1,
        route_pairs=tuple(
            dict.fromkeys(_RoutePair(pair.destination, pair.origin) for pair in native.route_pairs)
        ),
        date_mode=DateMode.EXACT.value,
        departure_date=return_date,
        departure_end_date=return_date,
        return_date=None,
    )
    return outbound, inbound


def _composition_group_is_approved(
    group: tuple[int, str, str, date],
    search_legs: Sequence[_SearchLeg],
) -> bool:
    leg_ordinal, origin, destination, departure_date = group
    search_leg = next(
        (leg for leg in search_legs if leg.ordinal == leg_ordinal),
        None,
    )
    return (
        search_leg is not None
        and origin != destination
        and _RoutePair(origin, destination) in search_leg.route_pairs
        and search_leg.departure_date <= departure_date <= search_leg.departure_end_date
    )


def _split_bindings_from_confirmed_records(
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
    *,
    trip_shape: TripShape,
    search_legs: tuple[_SearchLeg, ...],
    max_hubs_per_leg: int,
    adults: int,
    children: int,
    infants: int,
    currency: str,
) -> tuple[_SplitBinding, ...]:
    if max_hubs_per_leg <= 0:
        return ()
    passengers = adults + children + infants
    passenger_mix = PassengerMix(
        adults=adults,
        children=children,
        infants=infants,
    )
    candidates: list[tuple[tuple[int, str, str, date], str, UUID, _ExactBinding, int]] = []
    for record in records:
        itinerary = record.itinerary_evidence
        if itinerary.get("search_role", "base") != "base":
            continue
        try:
            evidence = confirmed_record_to_evidence(
                record,
                fallback_passenger_mix=passenger_mix,
            )
            directions = _confirmed_directions(evidence)
            if directions is None:
                continue
            if trip_shape is TripShape.ROUND_TRIP:
                if len(directions) != 2:
                    continue
                directional = tuple(enumerate(directions))
            else:
                if len(directions) != 1:
                    continue
                directional = (
                    (
                        _non_negative_int(
                            itinerary.get("leg_ordinal", 0),
                            "leg_ordinal",
                        ),
                        directions[0],
                    ),
                )
        except (StoredAgentEvidenceError, TypeError, ValueError):
            continue
        if (
            record.passengers != passengers
            or record.passenger_basis is not PriceBasis.TOTAL_FOR_PASSENGERS
            or record.currency != currency
        ):
            continue
        for leg_ordinal, direction in directional:
            search_leg = next(
                (leg for leg in search_legs if leg.ordinal == leg_ordinal),
                None,
            )
            if search_leg is None or len(direction) < 2:
                continue
            origin = direction[0].origin
            destination = direction[-1].destination
            first_departure = _segment_local_date(direction[0])
            if (
                origin == destination
                or _RoutePair(origin, destination) not in search_leg.route_pairs
                or not (
                    search_leg.departure_date <= first_departure <= search_leg.departure_end_date
                )
            ):
                continue
            for boundary in range(1, len(direction)):
                inbound = direction[boundary - 1]
                outbound = direction[boundary]
                hub = inbound.destination
                if hub != outbound.origin or hub in {origin, destination}:
                    continue
                second_departure = _segment_local_date(outbound)
                first = _ExactBinding(
                    leg_ordinal=leg_ordinal,
                    origin=origin,
                    destination=hub,
                    departure_date=first_departure,
                    return_date=None,
                    adults=adults,
                    children=children,
                    infants=infants,
                    passengers=passengers,
                    currency=currency,
                )
                second = _ExactBinding(
                    leg_ordinal=leg_ordinal,
                    origin=hub,
                    destination=destination,
                    departure_date=second_departure,
                    return_date=None,
                    adults=adults,
                    children=children,
                    infants=infants,
                    passengers=passengers,
                    currency=currency,
                )
                group = (leg_ordinal, origin, destination, first_departure)
                candidates.extend(
                    (
                        (group, hub, record.id, first, 0),
                        (group, hub, record.id, second, 1),
                    )
                )

    selected: list[_SplitBinding] = []
    seen_hubs: dict[tuple[int, str, str, date], list[str]] = {}
    selected_components: set[tuple[tuple[int, str, str, date], str, int]] = set()
    seen_bindings: set[tuple[_ExactBinding, UUID, int]] = set()
    for group, hub, source_id, binding, component_ordinal in sorted(
        candidates,
        key=lambda value: (
            value[0][0],
            value[0][1],
            value[0][2],
            value[0][3],
            value[1],
            str(value[2]),
            value[4],
            value[3].origin,
            value[3].destination,
            value[3].departure_date,
        ),
    ):
        hubs = seen_hubs.setdefault(group, [])
        if hub not in hubs:
            if len(hubs) >= max_hubs_per_leg:
                continue
            hubs.append(hub)
        component_key = (group, hub, component_ordinal)
        if component_key in selected_components:
            continue
        selected_components.add(component_key)
        identity = (binding, source_id, component_ordinal)
        if identity in seen_bindings:
            continue
        seen_bindings.add(identity)
        selected.append(
            _SplitBinding(
                binding=binding,
                source_evidence_id=source_id,
                component_ordinal=component_ordinal,
            )
        )
    return tuple(selected)


def _segment_local_date(segment: FlightSegmentSummary) -> date:
    if not isinstance(segment, FlightSegmentSummary):
        raise TypeError("segment must be FlightSegmentSummary")
    raw = segment.depart_at
    if len(raw) < 10:
        raise ValueError("segment local departure is missing a date")
    return date.fromisoformat(raw[:10])


def _bounded_composition_pool_combinations(
    pools_by_leg: tuple[tuple[LegEvidencePool, ...], ...],
    *,
    beam_width: int,
) -> tuple[tuple[LegEvidencePool, ...], ...]:
    if type(beam_width) is not int or beam_width < 1:
        raise ValueError("composition beam width must be positive")
    if not pools_by_leg or any(not pools for pools in pools_by_leg):
        return ()
    partials: list[tuple[LegEvidencePool, ...]] = []
    for pool in sorted(pools_by_leg[0], key=_composition_pool_order)[:beam_width]:
        partials.append((pool,))
    for pools in pools_by_leg[1:]:
        expanded = [
            (*partial, pool)
            for partial in partials
            for pool in sorted(pools, key=_composition_pool_order)
        ]
        expanded.sort(key=_composition_pool_combination_order)
        partials = expanded[:beam_width]
    return tuple(partials)


def _composition_pool_order(pool: LegEvidencePool) -> tuple[object, ...]:
    cheapest = min(item.total_amount.minor_units for item in pool.evidence)
    return (
        cheapest,
        pool.leg.ordinal,
        pool.leg.origin,
        pool.leg.destination,
        pool.leg.departure_date,
        tuple(sorted(str(item.id) for item in pool.evidence)),
    )


def _composition_pool_combination_order(
    pools: tuple[LegEvidencePool, ...],
) -> tuple[object, ...]:
    return (
        sum(min(item.total_amount.minor_units for item in pool.evidence) for pool in pools),
        tuple(_composition_pool_order(pool) for pool in pools),
    )


def _composed_candidate_order(
    candidate: ComposedRouteCandidate,
) -> tuple[object, ...]:
    amount = candidate.total_amount.minor_units if candidate.total_amount is not None else 2**63 - 1
    return (
        candidate.total_amount is None,
        amount,
        len(candidate.ticket_boundaries),
        candidate.fingerprint,
        str(candidate.id),
    )


def _start_params(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> SearchStartParams:
    binding = _exact_binding_from_immutable(immutable_input, workflow)
    return SearchStartParams(
        origin=ProviderLocation(LocationScopeKind.AIRPORT, binding.origin),
        destination=ProviderLocation(LocationScopeKind.AIRPORT, binding.destination),
        departure_date=binding.departure_date.isoformat(),
        return_date=binding.return_date.isoformat() if binding.return_date is not None else None,
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
    origin = _iata(immutable_input["origin"], "origin")
    destination = _iata(immutable_input["destination"], "destination")
    leg_ordinal = _non_negative_int(immutable_input.get("leg_ordinal", 0), "leg_ordinal")
    search_leg = next(
        (leg for leg in workflow.search_legs if leg.ordinal == leg_ordinal),
        None,
    )
    if (
        immutable_input.get("phase") != "calendar"
        or search_leg is None
        or _RoutePair(origin, destination) not in search_leg.route_pairs
        or not search_leg.departure_date <= departure_date <= search_leg.departure_end_date
        or return_date != search_leg.return_date
        or _positive_int(immutable_input["passengers"], "passengers") != workflow.passengers
        or _currency(immutable_input["currency"]) != workflow.currency
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    return CalendarSearchParams(
        origin=ProviderLocation(LocationScopeKind.AIRPORT, origin),
        destination=ProviderLocation(LocationScopeKind.AIRPORT, destination),
        depart_from=departure_date,
        depart_to=departure_date,
        one_way=return_date is None,
        currency=workflow.currency,
        adults=1,
        children=0,
        infants=0,
    )


def _operation_discovery_rule(
    workflow: _Workflow,
    operation_kind: AgentOperationKind,
) -> _AnywhereRule:
    if operation_kind is AgentOperationKind.SUGGEST_DISCOVERY:
        rule = workflow.anywhere_rule
    elif operation_kind is AgentOperationKind.HIDDEN_CITY_DISCOVERY:
        hidden_city_rule = workflow.hidden_city_rule
        rule = hidden_city_rule.discovery_rule if hidden_city_rule is not None else None
    else:
        rule = None
    if rule is None:
        raise AgentExecutionError("agent_operation_input_invalid")
    return rule


def _discovery_search_role(operation_kind: AgentOperationKind) -> str:
    if operation_kind is AgentOperationKind.SUGGEST_DISCOVERY:
        return "anywhere"
    if operation_kind is AgentOperationKind.HIDDEN_CITY_DISCOVERY:
        return "hidden_city"
    raise AgentExecutionError("agent_operation_input_invalid")


def _anywhere_bindings(rule: _AnywhereRule) -> tuple[tuple[str, str], ...]:
    bindings = tuple(
        (origin, source_id) for origin in rule.origins for source_id in rule.discovery_source_ids
    )
    if not bindings or rule.max_destination_seeds < len(bindings):
        raise AgentExecutionError("agent_plan_snapshot_invalid")
    return bindings


def _anywhere_binding_seed_limit(
    rule: _AnywhereRule,
    origin: str,
    source_id: str,
) -> int:
    bindings = _anywhere_bindings(rule)
    try:
        ordinal = bindings.index((origin, source_id))
    except ValueError as error:
        raise AgentExecutionError("agent_operation_input_invalid") from error
    base, remainder = divmod(rule.max_destination_seeds, len(bindings))
    limit = base + (1 if ordinal < remainder else 0)
    if limit <= 0:
        raise AgentExecutionError("agent_plan_snapshot_invalid")
    return limit


def _anywhere_params(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
    *,
    rule: _AnywhereRule | None = None,
    max_results: int | None = None,
    excluded_destination_airports: frozenset[str] = frozenset(),
) -> AnywhereDiscoveryParams:
    effective_rule = rule or workflow.anywhere_rule
    if effective_rule is None:
        raise AgentExecutionError("agent_operation_input_invalid")
    try:
        origin = _iata(immutable_input["origin"], "origin")
        date_from = date.fromisoformat(_text(immutable_input["date_from"], "date_from"))
        date_to = date.fromisoformat(_text(immutable_input["date_to"], "date_to"))
        source_id = _text(immutable_input["source_id"], "source_id")
        max_destination_seeds = _positive_int(
            immutable_input["max_destination_seeds"],
            "max_destination_seeds",
        )
        seed_limit = _positive_int(immutable_input["seed_limit"], "seed_limit")
        adults = _positive_int(immutable_input.get("adults", 1), "adults")
        children = _non_negative_int(immutable_input.get("children", 0), "children")
        infants = _non_negative_int(immutable_input.get("infants", 0), "infants")
        currency = _currency(immutable_input["currency"])
    except (KeyError, TypeError, ValueError):
        raise AgentExecutionError("agent_operation_input_invalid") from None
    if (
        origin not in effective_rule.origins
        or date_from != effective_rule.date_start
        or date_to != effective_rule.date_end
        or source_id not in effective_rule.discovery_source_ids
        or max_destination_seeds != effective_rule.max_destination_seeds
        or seed_limit != _anywhere_binding_seed_limit(effective_rule, origin, source_id)
        or (adults, children, infants) != (1, 0, 0)
        or currency != workflow.currency
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    effective_max_results = seed_limit if max_results is None else max_results
    allowed_destinations = frozenset(
        code for code, _country in effective_rule.eligible_destination_countries
    )
    if (
        type(effective_max_results) is not int
        or effective_max_results <= 0
        or effective_max_results > seed_limit
        or not isinstance(excluded_destination_airports, frozenset)
        or not excluded_destination_airports <= allowed_destinations
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    return AnywhereDiscoveryParams(
        origin=ProviderLocation(LocationScopeKind.AIRPORT, origin),
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        max_results=effective_max_results,
        allowed_destination_airports=allowed_destinations,
        excluded_destination_airports=excluded_destination_airports,
        one_way=True,
        adults=adults,
        children=children,
        infants=infants,
    )


def _exact_binding_from_immutable(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
) -> _ExactBinding:
    binding: _ExactBinding | None = None
    try:
        return_raw = immutable_input.get("return_date")
        candidate = _ExactBinding(
            leg_ordinal=_non_negative_int(immutable_input.get("leg_ordinal", 0), "leg_ordinal"),
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
        search_leg = next(
            (leg for leg in workflow.search_legs if leg.ordinal == candidate.leg_ordinal),
            None,
        )
        search_role = immutable_input.get("search_role", "base")
        split_match = None
        if search_role == "split_component":
            source_evidence_id = UUID(
                _text(
                    immutable_input["split_source_evidence_id"],
                    "split_source_evidence_id",
                )
            )
            component_ordinal = _non_negative_int(
                immutable_input["split_component_ordinal"],
                "split_component_ordinal",
            )
            split_match = next(
                (
                    value
                    for value in workflow.split_bindings
                    if value.binding == candidate
                    and value.source_evidence_id == source_evidence_id
                    and value.component_ordinal == component_ordinal
                ),
                None,
            )
        hidden_city_match = None
        if search_role == "hidden_city":
            hidden_city_rule = workflow.hidden_city_rule
            if hidden_city_rule is not None:
                eligible_destinations = {
                    code
                    for code, _country in (
                        hidden_city_rule.discovery_rule.eligible_destination_countries
                    )
                }
                hidden_city_match = (
                    candidate.leg_ordinal == hidden_city_rule.plan_leg_index
                    and candidate.origin in hidden_city_rule.discovery_rule.origins
                    and candidate.destination in eligible_destinations
                    and hidden_city_rule.discovery_rule.date_start
                    <= candidate.departure_date
                    <= hidden_city_rule.discovery_rule.date_end
                    and candidate.return_date is None
                    and immutable_input.get("split_source_evidence_id") is None
                    and immutable_input.get("split_component_ordinal") is None
                )
        base_binding = (
            search_leg is not None
            and _RoutePair(candidate.origin, candidate.destination) in search_leg.route_pairs
            and search_leg.departure_date
            <= candidate.departure_date
            <= search_leg.departure_end_date
            and candidate.return_date == search_leg.return_date
            and search_role == "base"
            and immutable_input.get("split_source_evidence_id") is None
            and immutable_input.get("split_component_ordinal") is None
        )
        valid = (
            (base_binding or split_match is not None or hidden_city_match is True)
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


def _source_signal_id_for_binding(
    immutable_input: Mapping[str, object],
    workflow: _Workflow,
    binding: _ExactBinding,
) -> UUID:
    raw_source_signal_id = immutable_input.get("source_signal_id")
    if not isinstance(raw_source_signal_id, str):
        raise AgentExecutionError("agent_operation_input_invalid")
    try:
        source_signal_id = UUID(raw_source_signal_id)
    except ValueError as error:
        raise AgentExecutionError("agent_operation_input_invalid") from error
    if str(source_signal_id) != raw_source_signal_id:
        raise AgentExecutionError("agent_operation_input_invalid")
    search_role = immutable_input.get("search_role", "base")
    source_signals = (
        workflow.hidden_city_signals if search_role == "hidden_city" else workflow.anywhere_signals
    )
    matching_signals = tuple(signal for signal in source_signals if signal.id == source_signal_id)
    if len(matching_signals) != 1:
        raise AgentExecutionError("agent_operation_input_invalid")
    signal = matching_signals[0]
    if (
        signal.origin != binding.origin
        or signal.destination != binding.destination
        or signal.departure_date != binding.departure_date
        or signal.return_date is not None
        or binding.return_date != (None if search_role == "hidden_city" else workflow.return_date)
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    return source_signal_id


def _validated_anywhere_exact_source_ids(
    operations: Sequence[AgentRunOperationRecord],
    workflow: _Workflow,
) -> frozenset[UUID]:
    expected_source_ids = frozenset(signal.id for signal in workflow.anywhere_signals)
    if (
        workflow.anywhere_rule is None
        or not expected_source_ids
        or len(expected_source_ids) != len(workflow.anywhere_signals)
        or len(operations) != len(expected_source_ids)
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    actual_source_ids: set[UUID] = set()
    for operation in operations:
        if operation.kind is not AgentOperationKind.EXACT_START:
            raise AgentExecutionError("agent_operation_input_invalid")
        binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
        source_signal_id = _source_signal_id_for_binding(
            operation.immutable_input,
            workflow,
            binding,
        )
        if source_signal_id in actual_source_ids:
            raise AgentExecutionError("agent_operation_input_invalid")
        actual_source_ids.add(source_signal_id)
    if frozenset(actual_source_ids) != expected_source_ids:
        raise AgentExecutionError("agent_operation_input_invalid")
    return frozenset(actual_source_ids)


def _validated_hidden_city_exact_source_ids(
    operations: Sequence[AgentRunOperationRecord],
    workflow: _Workflow,
) -> frozenset[UUID]:
    expected_source_ids = frozenset(signal.id for signal in workflow.hidden_city_signals)
    if (
        workflow.hidden_city_rule is None
        or not expected_source_ids
        or len(expected_source_ids) != len(workflow.hidden_city_signals)
        or len(operations) != len(expected_source_ids)
    ):
        raise AgentExecutionError("agent_operation_input_invalid")
    actual_source_ids: set[UUID] = set()
    for operation in operations:
        if (
            operation.kind is not AgentOperationKind.EXACT_START
            or operation.immutable_input.get("search_role") != "hidden_city"
        ):
            raise AgentExecutionError("agent_operation_input_invalid")
        binding = _exact_binding_from_immutable(operation.immutable_input, workflow)
        source_signal_id = _source_signal_id_for_binding(
            operation.immutable_input,
            workflow,
            binding,
        )
        if source_signal_id in actual_source_ids:
            raise AgentExecutionError("agent_operation_input_invalid")
        actual_source_ids.add(source_signal_id)
    if frozenset(actual_source_ids) != expected_source_ids:
        raise AgentExecutionError("agent_operation_input_invalid")
    return frozenset(actual_source_ids)


def _exact_logical_input(
    workflow: _Workflow,
    *,
    origin: str,
    destination: str,
    departure_date: date,
    return_date: date | None,
    leg_ordinal: int = 0,
) -> dict[str, object]:
    return {
        "leg_ordinal": leg_ordinal,
        "origin": origin,
        "destination": destination,
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
