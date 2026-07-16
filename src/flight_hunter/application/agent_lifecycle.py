from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.agent.presets import PRESET_EDITS, AgentPresetId
from flight_hunter.application.agent_hidden_city import (
    HIDDEN_CITY_WARNING_VERSION,
    HIDDEN_CITY_WARNINGS,
    HiddenCityCandidate,
    HiddenCityContext,
    HiddenCityWarning,
    classify_hidden_city,
)
from flight_hunter.application.agent_intent import (
    ClarificationAction,
    IntentClarification,
    IntentInputError,
    IntentParser,
    ParsedDateConstraint,
    ParsedIntent,
    ParsedLeg,
)
from flight_hunter.application.agent_operations import (
    CoveragePair,
    CoveragePairOutcome,
    CoverageReport,
    FrozenCoverageInput,
    build_coverage_report,
)
from flight_hunter.application.agent_planning import (
    AgentPlanBuilder,
    PlanBudgetExceededError,
    ProposedPlanRevision,
)
from flight_hunter.application.agent_reporting import (
    CandidateKind,
    CandidateReference,
    FactReport,
    FactReportBuilder,
    ranking_snapshot_from_payload,
)
from flight_hunter.application.agent_result_records import (
    StoredAgentEvidenceError,
    composed_record_to_candidate,
    confirmed_record_to_evidence,
)
from flight_hunter.application.agent_scope import (
    AnywhereDiscoveryRule,
    CoverageMode,
    FrozenAirportScope,
    finite_route_pairs,
)
from flight_hunter.application.booking_actions import (
    sign_agent_booking_action_token,
)
from flight_hunter.domain.agent_evidence import (
    ComposedRouteCandidate,
    ConfirmedOfferEvidence,
    DiscoverySource,
)
from flight_hunter.domain.agent_search import (
    DateConstraint,
    DateMode,
    LocationScope,
    LocationScopeKind,
    RouteStrategy,
    TripShape,
)
from flight_hunter.domain.offers import Freshness, PassengerMix, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentConfirmedOfferEvidenceRecord,
    AgentDiscoverySignalRecord,
    AgentEvidenceRepository,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentOperationStatus,
    AgentPlanApprovalSnapshot,
    AgentPlanConflict,
    AgentPlanError,
    AgentPlanNotFound,
    AgentPlanRecord,
    AgentPlanRepository,
    AgentPlanRevisionRecord,
    AgentPlanRunRecord,
    AgentRunLedgerProgress,
    AgentRunOperationRecord,
    AgentRunRepository,
    AgentRunScopeSnapshotRecord,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
)

PARSER_VERSION = "intent-parser-v2"
_PROVIDER_ID = "aviasales_search"
_PROVIDER_CLOCK_SKEW = timedelta(minutes=5)
_PUBLIC_RUN_ERRORS: dict[str, str] = {
    "deadline_exceeded": "Search deadline exceeded.",
    "provider_unavailable": "Flight provider is temporarily unavailable.",
    "agent_run_deadline_exceeded": "Search deadline exceeded.",
    "agent_run_partial": "Search completed with partial results.",
    "agent_http_budget_exhausted": "Search request budget exhausted.",
    "agent_circuit_open": "Flight provider is temporarily unavailable.",
    "agent_no_discovery_results": "No matching flight results were found.",
    "agent_no_confirmed_offer": "No confirmed flight offer was found.",
    "agent_plan_snapshot_invalid": "Approved search plan is invalid.",
    "agent_operation_input_invalid": "Approved search operation is invalid.",
    "agent_private_continuation_invalid": "Saved search continuation is invalid.",
    "agent_private_continuation_missing": "Saved search continuation is unavailable.",
    "agent_trip_shape_unsupported": "The approved trip shape is not supported.",
    "agent_scope_unsupported": "The approved search scope is not supported.",
    "agent_strategy_unsupported": "The approved route strategy is not supported.",
    "agent_analysis_unsupported": "The approved analysis mode is not supported.",
    "agent_provider_rate_wait": "Flight provider rate limit reached.",
    "agent_discovery_binding_not_materialized": "An approved discovery query was not run.",
    "agent_discovery_not_completed": "Destination discovery did not complete.",
    "agent_pair_incomplete": "The approved route search did not complete.",
    "agent_pair_not_materialized": "The approved route search was not started.",
    "agent_lease_expired_attempts_exhausted": "Search operation attempts were exhausted.",
    "provider_auth": "Flight provider authentication failed.",
    "provider_forbidden": "Flight provider denied the request.",
    "provider_schema": "Flight provider returned an unsupported response.",
    "provider_rate_limited": "Flight provider rate limit reached.",
    "provider_network": "Flight provider is temporarily unavailable.",
    "provider_server": "Flight provider is temporarily unavailable.",
    "provider_policy_denied": "Flight provider is unavailable for this search.",
    "provider_client_error": "Flight provider rejected the search request.",
    "provider_capability": "Flight provider cannot execute this search.",
}


class AgentLifecycleError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CreateAgentPlan:
    household_id: UUID
    user_id: UUID
    text: str
    selections: Mapping[str, object] = field(default_factory=dict)
    coverage: CoverageMode | str = CoverageMode.QUICK
    preset_id: AgentPresetId | str | None = None


@dataclass(frozen=True, slots=True)
class EditAgentPlan:
    household_id: UUID
    user_id: UUID
    plan_id: UUID
    source_revision_id: UUID
    expected_revision: int
    text: str | None = None
    selections: Mapping[str, object] = field(default_factory=dict)
    coverage: CoverageMode | str | None = None
    preset_id: AgentPresetId | str | None = None


@dataclass(frozen=True, slots=True)
class CloneAgentPlan:
    household_id: UUID
    user_id: UUID
    plan_id: UUID
    source_revision_id: UUID
    expected_revision: int
    idempotency_key: str
    selections: Mapping[str, object] = field(default_factory=dict)
    coverage: CoverageMode | str | None = None


@dataclass(frozen=True, slots=True)
class ExecuteAgentPlan:
    household_id: UUID
    user_id: UUID
    approved_by_session_id: UUID
    plan_id: UUID
    revision_id: UUID | None
    expected_revision: int | None
    content_hash: str | None
    idempotency_key: str
    hidden_city_warning_version: str | None = None


@dataclass(frozen=True, slots=True)
class CancelAgentRun:
    household_id: UUID
    user_id: UUID
    plan_id: UUID
    run_id: UUID


@dataclass(frozen=True, slots=True)
class EstimateView:
    calendar_searches: int
    exact_searches: int
    logical_operations: int
    http_attempts: int
    deadline_seconds: int


@dataclass(frozen=True, slots=True)
class PlanPassengerView:
    adults: int
    children: int
    infants: int
    total: int
    currency: str


@dataclass(frozen=True, slots=True)
class PlanScopeLegView:
    origin_kind: str | None
    origin_value: str | None
    origin_airports: tuple[str, ...]
    destination_kind: str | None
    destination_value: str | None
    destination_airports: tuple[str, ...]
    anywhere: bool
    frozen: bool
    reciprocal_anywhere_return: bool
    nearby_radius_km: int
    date_mode: str
    date_start: str | None
    date_end: str | None
    flex_days: int


@dataclass(frozen=True, slots=True)
class PlanProviderView:
    source_id: str
    capability_version: str
    cost_model_version: str
    requests_per_minute: int | None


@dataclass(frozen=True, slots=True)
class PlanSummaryView:
    trip_shape: str
    date_mode: str
    preset_id: str | None
    analysis_modes: tuple[str, ...]
    passengers: PlanPassengerView
    scope: tuple[PlanScopeLegView, ...]
    provider: PlanProviderView
    hidden_city_enabled: bool
    hidden_city_warning_version: str | None = None
    hidden_city_warnings: tuple[HiddenCityWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class PlanView:
    plan_id: UUID
    revision_id: UUID
    revision: int
    state: str
    content_hash: str
    coverage: str
    executable: bool
    enabled_strategies: tuple[str, ...]
    estimate: EstimateView | None
    summary: PlanSummaryView
    clarifications: tuple[Mapping[str, object], ...]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StageCountsView:
    total: int
    pending: int
    running: int
    completed: int
    partial: int
    failed: int
    skipped: int
    cancelled: int


@dataclass(frozen=True, slots=True)
class OperationCountsView:
    total: int
    attempted: int
    pending: int
    leased: int
    retry_wait: int
    succeeded: int
    failed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class CoverageFrozenInputView:
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    date_start: date
    date_end: date
    return_date: date | None
    catalog_checksums: tuple[str, ...]
    taxonomy_versions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CoveragePairView:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    status: str
    reason: str | None


@dataclass(frozen=True, slots=True)
class CoverageDiscoveryPhaseView:
    status: Literal["pending", "complete", "partial", "failed"]
    terminal_reason: str | None
    source_ids: tuple[str, ...]
    max_destination_seeds: int
    exact_verification_limit: int


@dataclass(frozen=True, slots=True)
class CoverageReportView:
    coverage: str
    completion: str
    frozen_input: CoverageFrozenInputView
    planned: int
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    pairs: tuple[CoveragePairView, ...]
    reason_counts: Mapping[str, int]
    discovery_phase: CoverageDiscoveryPhaseView | None


@dataclass(frozen=True, slots=True)
class RunView:
    run_id: UUID
    plan_id: UUID
    revision_id: UUID
    status: str
    created_at: datetime
    deadline_at: datetime
    started_at: datetime | None
    cancel_requested_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    public_message: str | None
    stage_counts: StageCountsView
    operation_counts: OperationCountsView
    logical_operation_budget: int
    logical_operations_consumed: int
    http_attempt_budget: int
    http_attempts_consumed: int
    cancellation_requested: bool
    coverage_report: CoverageReportView | None
    coverage_error_code: str | None


@dataclass(frozen=True, slots=True)
class RunResultsView:
    run_id: UUID
    state: Literal["not_ready", "ready", "unavailable"] = "not_ready"
    evidence_available: bool = False
    report: FactReport | None = None
    hidden_city_candidates: tuple[HiddenCityCandidate, ...] = ()
    error_code: Literal["agent_results_unavailable"] | None = None

    def __post_init__(self) -> None:
        hidden_city_candidates = tuple(self.hidden_city_candidates)
        if not all(
            isinstance(candidate, HiddenCityCandidate) for candidate in hidden_city_candidates
        ):
            raise TypeError("hidden_city_candidates must contain typed candidates")
        if self.state == "ready":
            if (self.report is None and not hidden_city_candidates) or self.error_code is not None:
                raise ValueError("ready results require publishable facts and no error")
        elif self.report is not None or hidden_city_candidates:
            raise ValueError("non-ready results cannot contain publishable facts")
        elif self.state == "unavailable" and self.error_code is None:
            raise ValueError("unavailable results require an error code")
        elif self.state == "not_ready" and self.error_code is not None:
            raise ValueError("not-ready results cannot contain an error code")
        if hidden_city_candidates and not self.evidence_available:
            raise ValueError("hidden-city facts require evidence_available")
        object.__setattr__(self, "hidden_city_candidates", hidden_city_candidates)


class AgentLifecycleService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        parser: IntentParser,
        builder: AgentPlanBuilder,
        clock: Callable[[], datetime] | None = None,
        provider_gateway: object | None = None,
        booking_action_secret: str | None = None,
    ) -> None:
        self._session = session
        self._parser = parser
        self._builder = builder
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_gateway = provider_gateway
        self._booking_action_secret = booking_action_secret
        self._plans = AgentPlanRepository(session)
        self._runs = AgentRunRepository(session)
        self._operations = AgentOperationRepository(session)
        self._evidence = AgentEvidenceRepository(session)

    async def create_plan(self, command: CreateAgentPlan) -> PlanView:
        async with self._owned_transaction():
            now = self._now()
            try:
                proposed = await self._build(
                    text=command.text,
                    preset_id=command.preset_id,
                    selections=command.selections,
                    coverage=CoverageMode(command.coverage),
                )
                stored = await self._plans.create_plan(
                    NewAgentPlan(
                        id=uuid4(),
                        household_id=command.household_id,
                        created_by_user_id=command.user_id,
                        created_at=now,
                    ),
                    _new_revision(proposed, approval_generation=1),
                )
            except PlanBudgetExceededError as error:
                raise AgentLifecycleError("agent_plan_budget_too_large") from error
            except IntentInputError as error:
                raise AgentLifecycleError("agent_plan_invalid_input") from error
            except AgentPlanError as error:
                raise _lifecycle_error(error) from error
        return _plan_view(stored)

    async def edit_plan(self, command: EditAgentPlan) -> PlanView:
        async with self._owned_transaction():
            source = await self._require_revision(
                command.household_id,
                command.plan_id,
                command.source_revision_id,
            )
            source = await self._expire_if_due(source)
            if source.state == "expired":
                raise AgentLifecycleError("agent_plan_expired")
            if source.revision_number != command.expected_revision or source.state not in {
                "draft",
                "awaiting_approval",
            }:
                raise AgentLifecycleError("agent_plan_stale")
            parsed = _parsed_intent(source)
            try:
                proposed = await self._build_from_existing(
                    parsed,
                    text=command.text,
                    preset_id=command.preset_id,
                    edits=command.selections,
                    coverage=CoverageMode(command.coverage or _stored_coverage(source)),
                )
                stored = await self._plans.create_successor(
                    household_id=command.household_id,
                    source_revision_id=source.id,
                    revision=_new_revision(
                        proposed,
                        approval_generation=source.revision_number + 1,
                    ),
                )
            except PlanBudgetExceededError as error:
                raise AgentLifecycleError("agent_plan_budget_too_large") from error
            except IntentInputError as error:
                raise AgentLifecycleError("agent_plan_invalid_input") from error
            except AgentPlanError as error:
                raise _lifecycle_error(error) from error
        return _plan_view(stored)

    async def clone_revision(self, command: CloneAgentPlan) -> PlanView:
        if not command.idempotency_key.strip():
            raise AgentLifecycleError("agent_plan_approval_required")
        async with self._owned_transaction():
            source = await self._require_revision(
                command.household_id,
                command.plan_id,
                command.source_revision_id,
            )
            source = await self._expire_if_due(source)
            if source.revision_number != command.expected_revision:
                raise AgentLifecycleError("agent_plan_stale")
            if source.state not in {"consumed", "expired", "superseded"}:
                raise AgentLifecycleError("agent_plan_stale")
            parsed = _parsed_intent(source)
            try:
                proposed = await self._build_from_existing(
                    parsed,
                    text=None,
                    preset_id=None,
                    edits=command.selections,
                    coverage=CoverageMode(command.coverage or _stored_coverage(source)),
                )
                stored = await self._plans.create_clone(
                    household_id=command.household_id,
                    plan_id=command.plan_id,
                    source_revision_id=source.id,
                    revision=_new_revision(
                        proposed,
                        approval_generation=source.revision_number + 1,
                        clone_idempotency_key=command.idempotency_key,
                    ),
                )
            except PlanBudgetExceededError as error:
                raise AgentLifecycleError("agent_plan_budget_too_large") from error
            except IntentInputError as error:
                raise AgentLifecycleError("agent_plan_invalid_input") from error
            except AgentPlanError as error:
                raise _lifecycle_error(error) from error
        return _plan_view(stored)

    async def execute_plan(self, command: ExecuteAgentPlan) -> RunView:
        if not command.idempotency_key.strip():
            raise AgentLifecycleError("agent_plan_approval_required")
        async with self._owned_transaction():
            existing = await self._runs.get_by_execute_idempotency(
                command.household_id,
                command.idempotency_key,
            )
            if existing is not None:
                return await self._project_run(_bound_idempotent_run(existing, command))
            if (
                command.revision_id is None
                or command.expected_revision is None
                or command.content_hash is None
            ):
                raise AgentLifecycleError("agent_plan_approval_required")
            revision = await self._require_revision(
                command.household_id,
                command.plan_id,
                command.revision_id,
            )
            existing = await self._runs.get_by_execute_idempotency(
                command.household_id,
                command.idempotency_key,
            )
            if existing is not None:
                return await self._project_run(_bound_idempotent_run(existing, command))
            revision = await self._expire_if_due(revision)
            if revision.state == "expired":
                raise AgentLifecycleError("agent_plan_expired")
            if revision.state == "draft":
                raise AgentLifecycleError("agent_plan_incomplete")
            if revision.state == "consumed":
                raise AgentLifecycleError("agent_plan_consumed")
            if revision.state != "awaiting_approval":
                raise AgentLifecycleError("agent_plan_stale")
            if (
                revision.revision_number != command.expected_revision
                or revision.content_hash != command.content_hash
            ):
                raise AgentLifecycleError("agent_plan_stale")

            budget = _approved_budget(revision)
            strategies = _stored_strategies(revision)
            warning_versions: dict[str, str] = {}
            if RouteStrategy.HIDDEN_CITY.value in strategies:
                if command.hidden_city_warning_version != HIDDEN_CITY_WARNING_VERSION:
                    raise AgentLifecycleError("agent_hidden_city_ack_required")
                warning_versions[RouteStrategy.HIDDEN_CITY.value] = HIDDEN_CITY_WARNING_VERSION

            approved_at = self._now()
            deadline_seconds = revision.estimated_deadline_seconds
            assert deadline_seconds is not None
            approval = NewAgentPlanApproval(
                id=uuid4(),
                household_id=command.household_id,
                revision_id=revision.id,
                approved_by_user_id=command.user_id,
                approved_at=approved_at,
                expires_at=revision.expires_at,
                snapshot=AgentPlanApprovalSnapshot(
                    revision_content_hash=revision.content_hash,
                    approved_by_session_id=command.approved_by_session_id,
                    approved_budget=budget,
                    approved_strategies=strategies,
                    risk_warning_versions=warning_versions,
                ),
            )
            run = NewAgentPlanRun(
                id=uuid4(),
                execute_idempotency_key=command.idempotency_key,
                created_at=approved_at,
                deadline_at=approved_at + timedelta(seconds=deadline_seconds),
            )
            try:
                stored = await self._runs.approve_and_execute(approval=approval, run=run)
            except AgentPlanConflict as error:
                raise _execution_error(error, revision.state) from error
            except AgentPlanNotFound as error:
                raise AgentLifecycleError("agent_plan_not_found") from error
            return await self._project_run(_bound_idempotent_run(stored, command))

    async def get_plan(self, household_id: UUID, plan_id: UUID) -> PlanView:
        async with self._owned_transaction():
            plan = await self._plans.get_plan(household_id, plan_id)
            if plan is None:
                raise AgentLifecycleError("agent_plan_not_found")
            revisions = await self._plans.list_revisions(household_id, plan_id)
            if not revisions:
                raise AgentLifecycleError("agent_plan_not_found")
            latest = await self._expire_if_due(revisions[-1])
        return _plan_view(latest)

    async def list_runs(
        self,
        household_id: UUID,
        plan_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[RunView, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        async with self._owned_transaction():
            await self._require_plan(household_id, plan_id)
            runs = await self._runs.list_runs(household_id, plan_id, limit=limit)
            return await self._project_runs(household_id, runs)

    async def get_run(self, household_id: UUID, plan_id: UUID, run_id: UUID) -> RunView:
        async with self._owned_transaction():
            await self._require_plan(household_id, plan_id)
            run = await self._runs.get_run(household_id, run_id)
            if run is None or run.plan_id != plan_id:
                raise AgentLifecycleError("agent_plan_not_found")
            return await self._project_run(run)

    async def get_latest_run(self, household_id: UUID, plan_id: UUID) -> RunView:
        async with self._owned_transaction():
            await self._require_plan(household_id, plan_id)
            run = await self._runs.get_latest_run(household_id, plan_id)
            if run is None:
                raise AgentLifecycleError("agent_run_not_found")
            return await self._project_run(run)

    async def cancel_run(self, command: CancelAgentRun) -> RunView:
        async with self._owned_transaction():
            run = await self._runs.get_run(command.household_id, command.run_id)
            if run is None or run.plan_id != command.plan_id:
                raise AgentLifecycleError("agent_plan_not_found")
            if run.status == "cancel_requested":
                return await self._project_run(run)
            if run.status not in {"queued", "running"}:
                raise AgentLifecycleError("agent_run_cancelled")
            try:
                stored = await self._runs.set_status(
                    household_id=command.household_id,
                    run_id=command.run_id,
                    status="cancel_requested",
                    changed_at=self._now(),
                )
            except AgentPlanError as error:
                raise _lifecycle_error(error) from error
            return await self._project_run(stored)

    async def get_run_results(
        self,
        household_id: UUID,
        plan_id: UUID,
        run_id: UUID,
    ) -> RunResultsView:
        async with self._owned_transaction():
            run = await self._runs.get_run(household_id, run_id)
            if run is None or run.plan_id != plan_id:
                raise AgentLifecycleError("agent_plan_not_found")
            confirmed_records = await self._evidence.list_confirmed_evidence(
                household_id,
                run_id,
            )
            composed_records = await self._evidence.list_composed_candidates(
                household_id,
                run_id,
            )
            evidence_available = bool(confirmed_records or composed_records)
            revision = await self._plans.get_revision(household_id, run.revision_id)
            try:
                hidden_city_candidates = (
                    ()
                    if revision is None
                    else _hidden_city_candidates_from_records(
                        revision,
                        confirmed_records,
                    )
                )
                if revision is None and any(
                    record.itinerary_evidence.get("search_role") == "hidden_city"
                    for record in confirmed_records
                ):
                    raise StoredAgentEvidenceError("hidden-city revision is missing")
            except (
                KeyError,
                RuntimeError,
                StoredAgentEvidenceError,
                TypeError,
                ValueError,
            ):
                return RunResultsView(
                    run_id=run.id,
                    state="unavailable",
                    evidence_available=evidence_available,
                    error_code="agent_results_unavailable",
                )
            operations = await self._operations.list_operations(household_id, run_id)
            ranking_operations = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.RANKING
                and operation.status is AgentOperationStatus.SUCCEEDED
                and operation.result_type is AgentOperationResultType.RANKING_SNAPSHOT
                and operation.result_id is not None
            )
            if not ranking_operations:
                if hidden_city_candidates and run.status in {
                    "completed",
                    "partial",
                    "failed",
                    "cancelled",
                }:
                    return RunResultsView(
                        run_id=run.id,
                        state="ready",
                        evidence_available=True,
                        hidden_city_candidates=hidden_city_candidates,
                    )
                return RunResultsView(
                    run_id=run.id,
                    state=(
                        "unavailable"
                        if run.status in {"completed", "partial", "failed", "cancelled"}
                        else "not_ready"
                    ),
                    evidence_available=evidence_available,
                    error_code=(
                        "agent_results_unavailable"
                        if run.status in {"completed", "partial", "failed", "cancelled"}
                        else None
                    ),
                )
            if len(ranking_operations) != 1:
                return RunResultsView(
                    run_id=run.id,
                    state="unavailable",
                    evidence_available=evidence_available,
                    error_code="agent_results_unavailable",
                )
            ranking_record = await self._evidence.get_ranking_snapshot(
                household_id,
                cast(UUID, ranking_operations[0].result_id),
            )
            try:
                if ranking_record is None or revision is None:
                    raise StoredAgentEvidenceError("ranking snapshot is missing")
                passenger_mix = _revision_passenger_mix(revision)
                confirmed = tuple(
                    confirmed_record_to_evidence(
                        record,
                        fallback_passenger_mix=passenger_mix,
                    )
                    for record in confirmed_records
                )
                confirmed_by_id = {value.id: value for value in confirmed}
                composed = tuple(
                    composed_record_to_candidate(record, confirmed_by_id)
                    for record in composed_records
                )
                ranking = ranking_snapshot_from_payload(ranking_record.ranking)
                if (
                    ranking_record.fingerprint != f"sha256:{ranking.fingerprint}"
                    or ranking_record.confirmed_evidence_ids != ranking.confirmed_evidence_ids
                    or ranking_record.composed_candidate_ids != ranking.composed_candidate_ids
                ):
                    raise StoredAgentEvidenceError("ranking snapshot references are invalid")
                candidates_by_reference: dict[
                    CandidateReference,
                    ConfirmedOfferEvidence | ComposedRouteCandidate,
                ] = {
                    CandidateReference(
                        CandidateKind.CONFIRMED_OFFER,
                        candidate.id,
                    ): candidate
                    for candidate in confirmed
                }
                candidates_by_reference.update(
                    {
                        CandidateReference(
                            CandidateKind.COMPOSED_ROUTE,
                            candidate.id,
                        ): candidate
                        for candidate in composed
                    }
                )
                report = FactReportBuilder().build(
                    ranking,
                    tuple(candidates_by_reference[reference] for reference in ranking.references),
                    booking_action_tokens=await self._booking_action_tokens(
                        household_id,
                        run_id,
                        ranking.references,
                    ),
                )
            except (
                KeyError,
                RuntimeError,
                StoredAgentEvidenceError,
                TypeError,
                ValueError,
            ):
                return RunResultsView(
                    run_id=run.id,
                    state="unavailable",
                    evidence_available=evidence_available,
                    error_code="agent_results_unavailable",
                )
            return RunResultsView(
                run_id=run.id,
                state="ready",
                evidence_available=True,
                report=report,
                hidden_city_candidates=hidden_city_candidates,
            )

    async def _booking_action_tokens(
        self,
        household_id: UUID,
        run_id: UUID,
        references: Sequence[CandidateReference],
    ) -> Mapping[CandidateReference, str]:
        if not self._booking_action_secret:
            return {}
        now = self._now()
        descriptors = await self._evidence.list_booking_action_descriptors(
            household_id,
            run_id,
            active_at=now,
        )
        descriptor_by_evidence = {
            descriptor.confirmed_evidence_id: descriptor for descriptor in descriptors
        }
        tokens: dict[CandidateReference, str] = {}
        for reference in references:
            if reference.kind is not CandidateKind.CONFIRMED_OFFER:
                continue
            descriptor = descriptor_by_evidence.get(reference.id)
            if descriptor is None:
                continue
            ttl_seconds = min(
                900,
                int((descriptor.expires_at - now).total_seconds()),
            )
            if ttl_seconds < 1:
                continue
            tokens[reference] = sign_agent_booking_action_token(
                secret_key=self._booking_action_secret,
                descriptor_id=descriptor.id,
                now=now,
                ttl_seconds=ttl_seconds,
            )
        return tokens

    async def _project_run(self, run: AgentPlanRunRecord) -> RunView:
        return (await self._project_runs(run.household_id, (run,)))[0]

    async def _project_runs(
        self,
        household_id: UUID,
        runs: Sequence[AgentPlanRunRecord],
    ) -> tuple[RunView, ...]:
        if not runs:
            return ()
        run_ids = tuple(run.id for run in runs)
        progress_by_run = await self._operations.get_run_ledger_progress(
            household_id,
            run_ids,
        )
        revisions_by_id = await self._plans.get_revisions_by_ids(
            household_id,
            tuple(run.revision_id for run in runs),
        )
        snapshots_by_run = await self._operations.get_scope_snapshots_for_runs(
            household_id,
            run_ids,
        )
        signals_by_run = await self._evidence.list_discovery_signals_for_runs(
            household_id,
            run_ids,
        )
        operations_by_run = await self._operations.list_operations_for_runs(
            household_id,
            run_ids,
        )
        projected: list[RunView] = []
        for run in runs:
            coverage_report, coverage_error_code = self._coverage_view(
                run,
                revisions_by_id.get(run.revision_id),
                snapshots_by_run.get(run.id),
                signals_by_run.get(run.id, ()),
                operations_by_run.get(run.id, ()),
            )
            projected.append(
                _run_view(
                    run,
                    progress_by_run[run.id],
                    coverage_report,
                    coverage_error_code,
                )
            )
        return tuple(projected)

    def _coverage_view(
        self,
        run: AgentPlanRunRecord,
        revision: AgentPlanRevisionRecord | None,
        snapshot: AgentRunScopeSnapshotRecord | None,
        discovery_signals: Sequence[AgentDiscoverySignalRecord],
        operations: Sequence[AgentRunOperationRecord],
    ) -> tuple[CoverageReportView | None, str | None]:
        try:
            return (
                self._coverage_view_unchecked(
                    run,
                    revision,
                    snapshot,
                    discovery_signals,
                    operations,
                ),
                None,
            )
        except (KeyError, OverflowError, RuntimeError, TypeError, ValueError):
            return None, "agent_coverage_projection_invalid"

    def _coverage_view_unchecked(
        self,
        run: AgentPlanRunRecord,
        revision: AgentPlanRevisionRecord | None,
        snapshot: AgentRunScopeSnapshotRecord | None,
        discovery_signals: Sequence[AgentDiscoverySignalRecord],
        operations: Sequence[AgentRunOperationRecord],
    ) -> CoverageReportView | None:
        if revision is None:
            raise RuntimeError("stored run revision is missing")
        scope = _json_mapping(revision.scope_snapshot_json)
        legs = _sequence(scope.get("legs", []))
        if not legs:
            raise RuntimeError("stored run scope has no legs")
        first_leg = _mapping(legs[0])
        origin = _mapping(first_leg["origin"])
        raw_constraint = _mapping(first_leg["date_constraint"])
        start_text, end_text = _plan_date_bounds(raw_constraint)
        if start_text is None:
            raise RuntimeError("stored run scope has no departure date")
        date_start = date.fromisoformat(start_text)
        date_end = date.fromisoformat(end_text or start_text)
        return_date: date | None = None
        if len(legs) == 2:
            return_constraint = _mapping(_mapping(legs[1])["date_constraint"])
            return_raw = return_constraint.get("start_date")
            if isinstance(return_raw, str):
                return_date = date.fromisoformat(return_raw)
        explicit_pairs: tuple[CoveragePair, ...] = ()
        finite_pairs: tuple[tuple[str, str], ...] = ()
        finite_pair_count = 0
        catalog_checksums: tuple[str, ...]
        taxonomy_versions: tuple[str, ...]
        if first_leg.get("anywhere") is not None:
            anywhere = _mapping(first_leg["anywhere"])
            if snapshot is None:
                return _anywhere_discovery_coverage_view(
                    scope=scope,
                    anywhere=anywhere,
                    date_start=date_start,
                    date_end=date_end,
                    return_date=return_date,
                    run=run,
                    operations=operations,
                )
            (
                rule_origins,
                rule_source_ids,
                max_destination_seeds,
                exact_verification_limit,
                rule_catalog_checksum,
                rule_taxonomy_version,
            ) = _anywhere_projection_values(anywhere)
            payload = _mapping(snapshot.snapshot)
            origins = _coverage_code_sequence(payload.get("origins"), "snapshot origins")
            destinations = _coverage_code_sequence(
                payload.get("destinations"),
                "snapshot destinations",
            )
            source_ids = tuple(
                UUID(_required_stored_str(value, "source signal id"))
                for value in _sequence(payload.get("source_signal_ids", ()))
            )
            if (
                snapshot.household_id != run.household_id
                or snapshot.run_id != run.id
                or not _durable_scope_snapshot_observation(snapshot, run)
                or snapshot.fingerprint != _scope_snapshot_fingerprint(payload)
                or origins != rule_origins
                or len(source_ids) != len(destinations)
                or len(source_ids) != len(set(source_ids))
                or len(destinations) > exact_verification_limit
                or len(destinations) > max_destination_seeds
                or _required_stored_str(payload.get("coverage"), "snapshot coverage")
                != _required_stored_str(scope.get("coverage"), "coverage")
                or _required_stored_str(payload.get("catalog_checksum"), "catalog checksum")
                != rule_catalog_checksum
                or _required_stored_str(payload.get("taxonomy_version"), "taxonomy version")
                != rule_taxonomy_version
            ):
                raise RuntimeError("stored anywhere coverage snapshot is invalid")
            approved_currency = _approved_intent_currency(revision)
            by_id = {record.id: record for record in discovery_signals}
            pairs: list[CoveragePair] = []
            for source_id, expected_destination in zip(source_ids, destinations, strict=True):
                record = by_id.get(source_id)
                if (
                    record is None
                    or record.household_id != run.household_id
                    or record.run_id != run.id
                    or record.provider_id != _PROVIDER_ID
                    or record.origin not in origins
                    or record.destination != expected_destination
                    or not date_start <= record.departure_date <= date_end
                    or record.return_date is not None
                    or record.source_kind is not DiscoverySource.HOT_OFFER
                    or record.freshness is not Freshness.API_CACHED
                    or record.passenger_basis is not PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
                    or record.amount_minor is None
                    or record.currency != approved_currency
                    or record.passengers != 1
                    or _required_stored_str(
                        record.signal_evidence.get("source_id"),
                        "source id",
                    )
                    not in rule_source_ids
                    or record.fingerprint != _evidence_fingerprint(record.id)
                    or not _durable_discovery_observation(record, run)
                ):
                    raise RuntimeError("stored anywhere source signal is invalid")
                pairs.append(
                    CoveragePair(
                        record.origin,
                        record.destination,
                        record.departure_date,
                        return_date,
                    )
                )
            explicit_pairs = tuple(pairs)
            catalog_checksums = (
                _required_stored_str(payload.get("catalog_checksum"), "catalog checksum"),
            )
            taxonomy_versions = (
                _required_stored_str(payload.get("taxonomy_version"), "taxonomy version"),
            )
        else:
            destination = _mapping(first_leg["destination"])
            origins = _coverage_scope_codes(origin)
            destinations = _coverage_scope_codes(destination)
            catalog_checksums = _stable_scope_values(
                origin,
                destination,
                field_name="catalog_checksum",
            )
            taxonomy_versions = _stable_scope_values(
                origin,
                destination,
                field_name="taxonomy_version",
            )
            finite_pair_count = len(origins) * len(destinations) - len(
                set(origins) & set(destinations)
            )
        date_count = (date_end - date_start).days + 1
        planned_count = len(explicit_pairs) or finite_pair_count * date_count
        if date_count <= 0 or planned_count <= 0 or planned_count > run.logical_operation_budget:
            raise RuntimeError("stored coverage surface exceeds the approved run budget")
        if not explicit_pairs:
            finite_pairs = finite_route_pairs(origins, destinations)
        frozen_input = FrozenCoverageInput(
            coverage=_required_stored_str(scope.get("coverage"), "coverage"),
            origins=origins,
            destinations=destinations,
            date_start=date_start,
            date_end=date_end,
            return_date=return_date,
            catalog_checksums=catalog_checksums,
            taxonomy_versions=taxonomy_versions,
            explicit_pairs=explicit_pairs,
        )
        planned_pairs = (
            explicit_pairs
            if explicit_pairs
            else tuple(
                CoveragePair(origin_code, destination_code, departure_date, return_date)
                for origin_code, destination_code in finite_pairs
                for departure_date in (
                    date_start + timedelta(days=offset)
                    for offset in range((date_end - date_start).days + 1)
                )
            )
        )
        report = build_coverage_report(
            frozen_input=frozen_input,
            planned_pairs=planned_pairs,
            outcomes=_coverage_operation_outcomes(
                planned_pairs,
                operations,
                terminal=run.status in {"completed", "partial", "failed", "cancelled"},
            ),
        )
        view = _coverage_report_view(report)
        if first_leg.get("anywhere") is None:
            return view
        discovery_phase, discovery_reasons = _snapshot_anywhere_discovery_phase(
            _mapping(first_leg["anywhere"]),
            operations,
            terminal=run.status in {"completed", "partial", "failed", "cancelled"},
        )
        completion = view.completion
        if discovery_phase.status in {"partial", "failed"}:
            completion = "partial" if view.planned else "failed"
        elif discovery_phase.status == "pending":
            completion = "pending"
        merged_reasons = dict(view.reason_counts)
        for reason, count in discovery_reasons.items():
            merged_reasons[reason] = merged_reasons.get(reason, 0) + count
        return replace(
            view,
            completion=completion,
            reason_counts=merged_reasons,
            discovery_phase=discovery_phase,
        )

    async def _build(
        self,
        *,
        text: str,
        preset_id: AgentPresetId | str | None,
        selections: Mapping[str, object],
        coverage: CoverageMode,
    ) -> ProposedPlanRevision:
        parsed = self._parser.parse(text, preset_id, selections)
        return await self._builder.build(parsed, coverage)

    async def _build_from_existing(
        self,
        parsed: ParsedIntent,
        *,
        text: str | None,
        preset_id: AgentPresetId | str | None,
        edits: Mapping[str, object],
        coverage: CoverageMode,
    ) -> ProposedPlanRevision:
        selections = (
            _parser_selections(parsed) if text is None else _independent_parser_selections(parsed)
        )
        selections.update(edits)
        rebuilt = self._parser.parse(
            text if text is not None else _route_text(parsed),
            preset_id if preset_id is not None else parsed.preset_id,
            selections,
        )
        return await self._builder.build(rebuilt, coverage)

    @asynccontextmanager
    async def _owned_transaction(self) -> AsyncIterator[None]:
        if self._session.in_transaction():
            raise AgentLifecycleError("agent_sqlite_nested_transaction_unsupported")
        async with self._session.begin():
            yield

    async def _require_plan(self, household_id: UUID, plan_id: UUID) -> AgentPlanRecord:
        plan = await self._plans.get_plan(household_id, plan_id)
        if plan is None:
            raise AgentLifecycleError("agent_plan_not_found")
        return plan

    async def _require_revision(
        self,
        household_id: UUID,
        plan_id: UUID,
        revision_id: UUID,
    ) -> AgentPlanRevisionRecord:
        revision = await self._plans.get_revision_for_update(
            household_id,
            plan_id,
            revision_id,
        )
        if revision is None:
            raise AgentLifecycleError("agent_plan_not_found")
        return revision

    async def _expire_if_due(
        self,
        revision: AgentPlanRevisionRecord,
    ) -> AgentPlanRevisionRecord:
        now = self._now()
        if revision.state == "awaiting_approval" and revision.expires_at <= now:
            return await self._plans.expire_revision(
                household_id=revision.household_id,
                plan_id=revision.plan_id,
                revision_id=revision.id,
                expired_at=now,
            )
        return revision

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("agent lifecycle clock must return a timezone-aware datetime")
        return value.astimezone(UTC)


def _new_revision(
    proposed: ProposedPlanRevision,
    *,
    approval_generation: int,
    clone_idempotency_key: str | None = None,
) -> NewAgentPlanRevision:
    estimate = proposed.estimate
    return NewAgentPlanRevision(
        id=uuid4(),
        state=proposed.status.value,
        plan=_plan_payload(proposed, approval_generation=approval_generation),
        scope_snapshot=_scope_payload(proposed),
        capability_snapshot=_capability_payload(proposed),
        cost_model_snapshot=_cost_model_payload(proposed),
        parser_version=PARSER_VERSION,
        planner_version=proposed.builder_version,
        estimated_calendar_searches=estimate.calendar_searches if estimate else None,
        estimated_exact_searches=estimate.exact_searches if estimate else None,
        estimated_logical_operations=estimate.logical_operations if estimate else None,
        estimated_http_attempts=estimate.http_attempts if estimate else None,
        estimated_deadline_seconds=estimate.deadline_seconds if estimate else None,
        expires_at=proposed.expires_at,
        created_at=proposed.created_at,
        clone_idempotency_key=clone_idempotency_key,
    )


def _plan_payload(
    proposed: ProposedPlanRevision,
    *,
    approval_generation: int,
) -> dict[str, object]:
    return {
        "coverage": proposed.coverage.value,
        "approval": {
            "generation": approval_generation,
            "expires_at": proposed.expires_at.isoformat(),
        },
        "intent": _intent_payload(proposed.parsed_intent),
        "composition": (
            {
                "version": proposed.composition_rule.version,
                "max_hubs_per_leg": proposed.composition_rule.max_hubs_per_leg,
                "source": proposed.composition_rule.source,
            }
            if proposed.composition_rule is not None
            else None
        ),
        "hidden_city": (
            {
                "version": proposed.hidden_city_rule.version,
                "plan_leg_index": proposed.hidden_city_rule.plan_leg_index,
                "desired_airports": list(proposed.hidden_city_rule.desired_airports),
                "discovery": _anywhere_rule_payload(proposed.hidden_city_rule.discovery_rule),
            }
            if proposed.hidden_city_rule is not None
            else None
        ),
        "clarifications": [
            _clarification_payload(clarification) for clarification in proposed.clarifications
        ],
    }


def _intent_payload(parsed: ParsedIntent) -> dict[str, object]:
    preset_edits = PRESET_EDITS.get(parsed.preset_id.value) if parsed.preset_id else None
    return {
        "origin_text": parsed.origin_text,
        "destination_text": parsed.destination_text,
        "trip_shape": parsed.trip_shape.value,
        "date_mode": parsed.date_mode.value,
        "adults": parsed.adults,
        "children": parsed.children,
        "infants": parsed.infants,
        "nearby_radius_km": parsed.nearby_radius_km,
        "currency": parsed.currency,
        "requested_strategies": [strategy.value for strategy in parsed.requested_strategies],
        "preset_id": parsed.preset_id.value if parsed.preset_id is not None else None,
        "analysis_modes": (
            [mode.value for mode in preset_edits.analysis_modes] if preset_edits is not None else []
        ),
        "legs": [
            {
                "origin": _location_payload(leg.origin),
                "destination": _location_payload(leg.destination),
                "date_constraint": {
                    "mode": leg.date_constraint.mode.value,
                    "start_date": (
                        leg.date_constraint.start_date.isoformat()
                        if leg.date_constraint.start_date is not None
                        else None
                    ),
                    "end_date": (
                        leg.date_constraint.end_date.isoformat()
                        if leg.date_constraint.end_date is not None
                        else None
                    ),
                    "flex_days": leg.date_constraint.flex_days,
                },
            }
            for leg in parsed.legs
        ],
    }


def _location_payload(scope: LocationScope | None) -> dict[str, object] | None:
    if scope is None:
        return None
    return {"kind": scope.kind.value, "value": scope.value}


def _clarification_payload(clarification: IntentClarification) -> dict[str, object]:
    return {
        "field": clarification.field,
        "code": clarification.code,
        "message_ru": clarification.message_ru,
        "actions": [
            {
                "action_id": action.action_id,
                "label_ru": action.label_ru,
                "selections": dict(action.selections),
                "date_mode": action.date_mode.value if action.date_mode is not None else None,
            }
            for action in clarification.actions
        ],
        "details": dict(clarification.details),
    }


def _scope_payload(proposed: ProposedPlanRevision) -> dict[str, object]:
    return {
        "coverage": proposed.coverage.value,
        "legs": [
            {
                "origin": (
                    _frozen_scope_payload(leg.origin_scope)
                    if leg.origin_scope is not None
                    else None
                ),
                "destination": (
                    _frozen_scope_payload(leg.destination_scope)
                    if leg.destination_scope is not None
                    else None
                ),
                "anywhere": (
                    _anywhere_rule_payload(leg.anywhere_rule)
                    if leg.anywhere_rule is not None
                    else None
                ),
                "date_constraint": _date_constraint_payload(leg.date_constraint),
                "reciprocal_anywhere_return": leg.reciprocal_anywhere_return,
            }
            for leg in proposed.frozen_legs
        ],
    }


def _anywhere_rule_payload(rule: AnywhereDiscoveryRule) -> dict[str, object]:
    return {
        "origin_airports": list(rule.origin_airports),
        "date_start": rule.date_start.isoformat(),
        "date_end": rule.date_end.isoformat(),
        "allowed_country_codes": list(rule.allowed_country_codes),
        "excluded_country_codes": list(rule.excluded_country_codes),
        "discovery_source_ids": list(rule.discovery_source_ids),
        "max_destination_seeds": rule.max_destination_seeds,
        "exact_verification_limit": rule.exact_verification_limit,
        "catalog_checksum": rule.catalog_checksum,
        "taxonomy_version": rule.taxonomy_version,
        "eligible_destination_countries": [
            {"code": code, "country_code": country_code}
            for code, country_code in rule.eligible_destination_countries
        ],
    }


def _frozen_scope_payload(frozen: FrozenAirportScope) -> dict[str, object]:
    return {
        "requested_scope": _location_payload(frozen.requested_scope),
        "airport_codes": list(frozen.airport_codes),
        "catalog_checksum": frozen.catalog_checksum,
        "taxonomy_version": frozen.taxonomy_version,
        "commercial_provenance": frozen.commercial_provenance,
        "coverage": frozen.coverage.value,
        "nearby_radius_km": frozen.nearby_radius_km,
        "airport_candidates": [
            {
                "code": candidate.airport.iata_code,
                "discovery_evidence_count": candidate.discovery_evidence_count,
                "commercial_relevance": candidate.commercial_relevance,
                "nearby_distance_km": candidate.nearby_distance_km,
                "ground_transfer_cost_minor": candidate.ground_transfer_cost_minor,
                "ground_transfer_currency": candidate.ground_transfer_currency,
                "ground_cost_uncertain": candidate.ground_cost_uncertain,
            }
            for candidate in frozen.airport_candidates
        ],
    }


def _date_constraint_payload(constraint: DateConstraint) -> dict[str, object]:
    return {
        "mode": constraint.mode.value,
        "start_date": constraint.start_date.isoformat(),
        "end_date": constraint.end_date.isoformat() if constraint.end_date else None,
        "flex_days": constraint.flex_days,
    }


def _capability_payload(proposed: ProposedPlanRevision) -> dict[str, object]:
    snapshot = proposed.capability_snapshot
    if snapshot is None:
        return {}
    return {
        "provider_id": snapshot.provider_id,
        "version": snapshot.version,
        "one_way": snapshot.one_way.value,
        "round_trip": snapshot.round_trip.value,
        "native_open_jaw": snapshot.native_open_jaw.value,
        "native_multi_city": snapshot.native_multi_city.value,
        "explicit_connection_protection": snapshot.explicit_connection_protection.value,
        "airport_location_semantics": snapshot.airport_location_semantics.value,
        "city_location_semantics": snapshot.city_location_semantics.value,
    }


def _cost_model_payload(proposed: ProposedPlanRevision) -> dict[str, object]:
    snapshot = proposed.capability_snapshot
    if snapshot is None:
        return {}
    model = snapshot.cost_model
    return {
        "version": model.version,
        "start_attempts": model.start_attempts,
        "poll_rounds": model.poll_rounds,
        "attempts_per_poll": model.attempts_per_poll,
        "requests_per_minute": model.requests_per_minute,
        "worst_case_exact_http_attempts": model.worst_case_exact_http_attempts,
    }


def _plan_view(revision: AgentPlanRevisionRecord) -> PlanView:
    plan = _json_mapping(revision.plan_json)
    clarification_values = _sequence(plan.get("clarifications", []))
    return PlanView(
        plan_id=revision.plan_id,
        revision_id=revision.id,
        revision=revision.revision_number,
        state=revision.state,
        content_hash=revision.content_hash,
        coverage=str(plan["coverage"]),
        executable=revision.state == "awaiting_approval",
        enabled_strategies=_stored_strategies(revision),
        estimate=_estimate_view(revision),
        summary=_plan_summary_view(revision),
        clarifications=tuple(_mapping(value) for value in clarification_values),
        created_at=revision.created_at,
        expires_at=revision.expires_at,
    )


def _plan_summary_view(revision: AgentPlanRevisionRecord) -> PlanSummaryView:
    plan = _json_mapping(revision.plan_json)
    intent = _mapping(plan["intent"])
    scope_snapshot = _json_mapping(revision.scope_snapshot_json)
    capability = _json_mapping(revision.capability_snapshot_json)
    cost_model = _json_mapping(revision.cost_model_snapshot_json)
    preset_id = _optional_stored_str(intent.get("preset_id"), "preset_id")
    if "nearby_radius_km" in intent:
        preset_radius = _stored_int(intent["nearby_radius_km"], "nearby_radius_km")
    elif preset_id is not None:
        preset_radius = PRESET_EDITS[AgentPresetId(preset_id).value].nearby_radius_km or 0
    else:
        preset_radius = 0
    intent_legs = _sequence(intent.get("legs", []))
    frozen_legs = _sequence(scope_snapshot.get("legs", []))
    scope = tuple(
        _plan_scope_leg_view(
            _mapping(intent_leg),
            _mapping(frozen_legs[index]) if index < len(frozen_legs) else None,
            preset_radius=preset_radius,
        )
        for index, intent_leg in enumerate(intent_legs)
    )
    adults = _stored_int(intent.get("adults"), "adults")
    children = _stored_int(intent.get("children"), "children")
    infants = _stored_int(intent.get("infants"), "infants")
    strategies = tuple(str(value) for value in _sequence(intent.get("requested_strategies", [])))
    hidden_city_enabled = RouteStrategy.HIDDEN_CITY.value in strategies
    return PlanSummaryView(
        trip_shape=_required_stored_str(intent.get("trip_shape"), "trip_shape"),
        date_mode=_required_stored_str(intent.get("date_mode"), "date_mode"),
        preset_id=preset_id,
        analysis_modes=tuple(str(value) for value in _sequence(intent.get("analysis_modes", []))),
        passengers=PlanPassengerView(
            adults=adults,
            children=children,
            infants=infants,
            total=adults + children + infants,
            currency=_required_stored_str(intent.get("currency"), "currency"),
        ),
        scope=scope,
        provider=PlanProviderView(
            source_id=_required_stored_str(capability.get("provider_id"), "provider_id"),
            capability_version=_required_stored_str(
                capability.get("version"),
                "capability_version",
            ),
            cost_model_version=_required_stored_str(
                cost_model.get("version"),
                "cost_model_version",
            ),
            requests_per_minute=_optional_stored_int(
                cost_model.get("requests_per_minute"),
                "requests_per_minute",
            ),
        ),
        hidden_city_enabled=hidden_city_enabled,
        hidden_city_warning_version=(HIDDEN_CITY_WARNING_VERSION if hidden_city_enabled else None),
        hidden_city_warnings=HIDDEN_CITY_WARNINGS if hidden_city_enabled else (),
    )


def _plan_scope_leg_view(
    intent_leg: Mapping[str, object],
    frozen_leg: Mapping[str, object] | None,
    *,
    preset_radius: int,
) -> PlanScopeLegView:
    intent_origin = _optional_mapping(intent_leg.get("origin"))
    intent_destination = _optional_mapping(intent_leg.get("destination"))
    date_constraint = _mapping(intent_leg["date_constraint"])
    origin_airports: tuple[str, ...] = ()
    destination_airports: tuple[str, ...] = ()
    nearby_radius_km = preset_radius
    frozen = frozen_leg is not None
    anywhere = _scope_kind(intent_destination) == LocationScopeKind.ANYWHERE.value
    if frozen_leg is not None:
        frozen_origin = _optional_mapping(frozen_leg.get("origin"))
        if frozen_origin is not None:
            origin_airports = tuple(
                str(value) for value in _sequence(frozen_origin.get("airport_codes", []))
            )
            nearby_radius_km = _stored_int(
                frozen_origin.get("nearby_radius_km"),
                "nearby_radius_km",
            )
        frozen_destination = _optional_mapping(frozen_leg.get("destination"))
        if frozen_destination is not None:
            destination_airports = tuple(
                str(value) for value in _sequence(frozen_destination.get("airport_codes", []))
            )
            nearby_radius_km = max(
                nearby_radius_km,
                _stored_int(
                    frozen_destination.get("nearby_radius_km"),
                    "nearby_radius_km",
                ),
            )
        anywhere = frozen_leg.get("anywhere") is not None
        date_constraint = _mapping(frozen_leg["date_constraint"])
    reciprocal_anywhere_return = (
        frozen_leg.get("reciprocal_anywhere_return", False) if frozen_leg is not None else False
    )
    if type(reciprocal_anywhere_return) is not bool:
        raise RuntimeError("stored reciprocal_anywhere_return must be a boolean")
    date_start, date_end = _plan_date_bounds(date_constraint)
    return PlanScopeLegView(
        origin_kind=_scope_kind(intent_origin),
        origin_value=_scope_value(intent_origin),
        origin_airports=origin_airports,
        destination_kind=_scope_kind(intent_destination),
        destination_value=_scope_value(intent_destination),
        destination_airports=destination_airports,
        anywhere=anywhere,
        frozen=frozen,
        reciprocal_anywhere_return=reciprocal_anywhere_return,
        nearby_radius_km=nearby_radius_km,
        date_mode=_required_stored_str(date_constraint.get("mode"), "date_mode"),
        date_start=date_start,
        date_end=date_end,
        flex_days=_stored_int(date_constraint.get("flex_days"), "flex_days"),
    )


def _plan_date_bounds(date_constraint: Mapping[str, object]) -> tuple[str | None, str | None]:
    raw_start = _optional_stored_str(date_constraint.get("start_date"), "date_start")
    raw_end = _optional_stored_str(date_constraint.get("end_date"), "date_end")
    if raw_start is None:
        return None, raw_end
    mode = _required_stored_str(date_constraint.get("mode"), "date_mode")
    if mode != DateMode.FLEXIBLE.value:
        return raw_start, raw_end
    flex_days = _stored_int(date_constraint.get("flex_days"), "flex_days")
    center = date.fromisoformat(raw_start)
    delta = timedelta(days=flex_days)
    return (center - delta).isoformat(), (center + delta).isoformat()


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _mapping(value)


def _scope_kind(scope: Mapping[str, object] | None) -> str | None:
    if scope is None:
        return None
    return _optional_stored_str(scope.get("kind"), "scope_kind")


def _scope_value(scope: Mapping[str, object] | None) -> str | None:
    if scope is None:
        return None
    return _optional_stored_str(scope.get("value"), "scope_value")


def _estimate_view(revision: AgentPlanRevisionRecord) -> EstimateView | None:
    values = (
        revision.estimated_calendar_searches,
        revision.estimated_exact_searches,
        revision.estimated_logical_operations,
        revision.estimated_http_attempts,
        revision.estimated_deadline_seconds,
    )
    if any(value is None for value in values):
        return None
    calendar, exact, logical, http, deadline = cast(tuple[int, int, int, int, int], values)
    return EstimateView(calendar, exact, logical, http, deadline)


def _run_view(
    run: AgentPlanRunRecord,
    progress: AgentRunLedgerProgress,
    coverage_report: CoverageReportView | None,
    coverage_error_code: str | None,
) -> RunView:
    public_error_code, public_message = _public_run_error(run.error_code)
    return RunView(
        run_id=run.id,
        plan_id=run.plan_id,
        revision_id=run.revision_id,
        status=run.status,
        created_at=run.created_at,
        deadline_at=run.deadline_at,
        started_at=run.started_at,
        cancel_requested_at=run.cancel_requested_at,
        finished_at=run.finished_at,
        error_code=public_error_code,
        public_message=public_message,
        stage_counts=StageCountsView(
            total=progress.stage_total,
            pending=progress.stage_pending,
            running=progress.stage_running,
            completed=progress.stage_completed,
            partial=progress.stage_partial,
            failed=progress.stage_failed,
            skipped=progress.stage_skipped,
            cancelled=progress.stage_cancelled,
        ),
        operation_counts=OperationCountsView(
            total=progress.operation_total,
            attempted=progress.operation_attempted,
            pending=progress.operation_pending,
            leased=progress.operation_leased,
            retry_wait=progress.operation_retry_wait,
            succeeded=progress.operation_succeeded,
            failed=progress.operation_failed,
            skipped=progress.operation_skipped,
        ),
        logical_operation_budget=run.logical_operation_budget,
        logical_operations_consumed=run.logical_operations_consumed,
        http_attempt_budget=run.http_attempt_budget,
        http_attempts_consumed=run.http_attempts_consumed,
        cancellation_requested=run.status in {"cancel_requested", "cancelled"},
        coverage_report=coverage_report,
        coverage_error_code=coverage_error_code,
    )


def _coverage_scope_codes(scope: Mapping[str, object]) -> tuple[str, ...]:
    codes = tuple(str(value).upper() for value in _sequence(scope.get("airport_codes", [])))
    if not codes or len(set(codes)) != len(codes):
        raise ValueError("frozen coverage airport codes must be non-empty and unique")
    raw_candidates = scope.get("airport_candidates")
    if raw_candidates is not None:
        candidates = tuple(_mapping(value) for value in _sequence(raw_candidates))
        candidate_codes = tuple(
            _required_stored_str(candidate.get("code"), "candidate code")
            for candidate in candidates
        )
        if candidate_codes != codes:
            raise ValueError("frozen coverage candidate codes differ from airport codes")
    return codes


def _coverage_code_sequence(value: object, field_name: str) -> tuple[str, ...]:
    codes = tuple(_required_stored_str(item, field_name).upper() for item in _sequence(value))
    if (
        not codes
        or len(codes) != len(set(codes))
        or any(len(code) != 3 or not code.isascii() or not code.isalpha() for code in codes)
    ):
        raise RuntimeError(f"stored {field_name} must contain unique IATA codes")
    return codes


def _stable_scope_values(
    *scopes: Mapping[str, object],
    field_name: str,
) -> tuple[str, ...]:
    values = tuple(
        dict.fromkeys(_required_stored_str(scope.get(field_name), field_name) for scope in scopes)
    )
    if not values:
        raise ValueError(f"{field_name} is required")
    return values


def _scope_snapshot_fingerprint(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _mutable_projection_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _mutable_projection_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _mutable_projection_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_mutable_projection_json(item) for item in value]
    return value


def _approved_intent_currency(revision: AgentPlanRevisionRecord) -> str:
    canonical = _json_mapping(revision.plan_json)
    intent = _mapping(canonical.get("intent"))
    currency = _required_stored_str(intent.get("currency"), "approved currency").upper()
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
        raise RuntimeError("stored approved currency is invalid")
    return currency


def _evidence_fingerprint(evidence_id: UUID) -> str:
    return "sha256:" + hashlib.sha256(str(evidence_id).encode("utf-8")).hexdigest()


def _durable_discovery_observation(
    record: AgentDiscoverySignalRecord,
    run: AgentPlanRunRecord,
) -> bool:
    times = (record.observed_at, record.created_at, run.created_at, run.deadline_at)
    if any(value.tzinfo is None or value.utcoffset() is None for value in times):
        return False
    observed_at = record.observed_at.astimezone(UTC)
    created_at = record.created_at.astimezone(UTC)
    run_start = run.created_at.astimezone(UTC)
    run_deadline = run.deadline_at.astimezone(UTC)
    lower_bound = max(run_start, created_at - _PROVIDER_CLOCK_SKEW)
    return (
        run_start <= created_at <= run_deadline + _PROVIDER_CLOCK_SKEW
        and lower_bound <= observed_at <= created_at + _PROVIDER_CLOCK_SKEW
    )


def _durable_scope_snapshot_observation(
    snapshot: AgentRunScopeSnapshotRecord,
    run: AgentPlanRunRecord,
) -> bool:
    if snapshot.created_at.tzinfo is None or snapshot.created_at.utcoffset() is None:
        return False
    created_at = snapshot.created_at.astimezone(UTC)
    return run.created_at.astimezone(UTC) <= created_at <= run.deadline_at.astimezone(UTC)


def _coverage_operation_outcomes(
    planned_pairs: tuple[CoveragePair, ...],
    operations: Sequence[AgentRunOperationRecord],
    *,
    terminal: bool = False,
) -> Mapping[CoveragePair, CoveragePairOutcome]:
    outcomes: dict[CoveragePair, CoveragePairOutcome] = {}
    for pair in planned_pairs:
        exact_roots = tuple(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.EXACT_START
            and _operation_matches_pair(operation, pair)
        )
        calendar = tuple(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.CALENDAR_SEARCH
            and _operation_matches_pair(operation, pair)
        )
        if exact_roots:
            root_ids = {operation.id for operation in exact_roots}
            related = exact_roots + tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.EXACT_POLL
                and operation.logical_root_operation_id in root_ids
            )
            outcome = _operation_group_outcome(related, require_confirmed=True)
        elif calendar:
            outcome = _operation_group_outcome(calendar, require_confirmed=False)
        else:
            outcome = None
        if terminal and outcome is not None and outcome.status == "attempted":
            outcome = CoveragePairOutcome("failed", "agent_pair_incomplete")
        if outcome is not None:
            outcomes[pair] = outcome
        elif terminal:
            outcomes[pair] = CoveragePairOutcome(
                "skipped",
                (
                    "agent_pair_incomplete"
                    if exact_roots or calendar
                    else "agent_pair_not_materialized"
                ),
            )
    return outcomes


def _operation_matches_pair(
    operation: AgentRunOperationRecord,
    pair: CoveragePair,
) -> bool:
    values = operation.immutable_input
    return (
        values.get("origin") == pair.origin
        and values.get("destination") == pair.destination
        and values.get("departure_date") == pair.departure_date.isoformat()
        and values.get("return_date")
        == (pair.return_date.isoformat() if pair.return_date is not None else None)
    )


def _operation_group_outcome(
    operations: Sequence[AgentRunOperationRecord],
    *,
    require_confirmed: bool,
) -> CoveragePairOutcome | None:
    if require_confirmed and any(
        operation.status is AgentOperationStatus.SUCCEEDED
        and operation.result_type is AgentOperationResultType.CONFIRMED_OFFER
        for operation in operations
    ):
        return CoveragePairOutcome("succeeded")
    failed = next(
        (operation for operation in operations if operation.status is AgentOperationStatus.FAILED),
        None,
    )
    if failed is not None:
        return CoveragePairOutcome("failed", _coverage_reason(failed.error_code, failed=True))
    skipped = next(
        (operation for operation in operations if operation.status is AgentOperationStatus.SKIPPED),
        None,
    )
    if skipped is not None:
        return CoveragePairOutcome("skipped", _coverage_reason(skipped.error_code, failed=False))
    if not require_confirmed and any(
        operation.status is AgentOperationStatus.SUCCEEDED for operation in operations
    ):
        return CoveragePairOutcome("attempted")
    if any(operation.attempt_count > 0 for operation in operations):
        return CoveragePairOutcome("attempted")
    return None


def _coverage_reason(value: str | None, *, failed: bool) -> str:
    if value is not None and value in _PUBLIC_RUN_ERRORS:
        return value
    return "agent_pair_failed" if failed else "agent_pair_skipped"


def _anywhere_projection_values(
    anywhere: Mapping[str, object],
) -> tuple[tuple[str, ...], tuple[str, ...], int, int, str, str]:
    origins = _coverage_code_sequence(anywhere.get("origin_airports"), "anywhere origins")
    source_ids = tuple(
        _required_stored_str(value, "discovery source id")
        for value in _sequence(anywhere.get("discovery_source_ids", ()))
    )
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise RuntimeError("stored discovery source ids must be non-empty and unique")
    max_destination_seeds = _stored_int(
        anywhere.get("max_destination_seeds"),
        "max_destination_seeds",
    )
    exact_verification_limit = _stored_int(
        anywhere.get("exact_verification_limit"),
        "exact_verification_limit",
    )
    if (
        max_destination_seeds <= 0
        or exact_verification_limit <= 0
        or exact_verification_limit > max_destination_seeds
    ):
        raise RuntimeError("stored anywhere limits are invalid")
    return (
        origins,
        source_ids,
        max_destination_seeds,
        exact_verification_limit,
        _required_stored_str(anywhere.get("catalog_checksum"), "catalog checksum"),
        _required_stored_str(anywhere.get("taxonomy_version"), "taxonomy version"),
    )


def _snapshot_anywhere_discovery_phase(
    anywhere: Mapping[str, object],
    operations: Sequence[AgentRunOperationRecord],
    *,
    terminal: bool,
) -> tuple[CoverageDiscoveryPhaseView, Mapping[str, int]]:
    origins, source_ids, max_seeds, exact_limit, _catalog, _taxonomy = _anywhere_projection_values(
        anywhere
    )
    expected_bindings = {(origin, source_id) for origin in origins for source_id in source_ids}
    discovery = tuple(
        operation
        for operation in operations
        if operation.kind is AgentOperationKind.SUGGEST_DISCOVERY
    )
    materialized_bindings: set[tuple[str, str]] = set()
    for operation in discovery:
        binding = (
            _required_stored_str(operation.immutable_input.get("origin"), "discovery origin"),
            _required_stored_str(
                operation.immutable_input.get("source_id"),
                "discovery source id",
            ),
        )
        if (
            operation.provider_id != _PROVIDER_ID
            or binding not in expected_bindings
            or binding in materialized_bindings
        ):
            raise RuntimeError("stored discovery operation binding is invalid")
        materialized_bindings.add(binding)
    missing_bindings = expected_bindings - materialized_bindings
    active = any(
        operation.status
        in {
            AgentOperationStatus.PENDING,
            AgentOperationStatus.LEASED,
            AgentOperationStatus.RETRY_WAIT,
        }
        for operation in discovery
    )
    succeeded = any(operation.status is AgentOperationStatus.SUCCEEDED for operation in discovery)
    failed = tuple(
        operation
        for operation in discovery
        if operation.status in {AgentOperationStatus.FAILED, AgentOperationStatus.SKIPPED}
    )
    reasons: dict[str, int] = {}
    for operation in failed:
        reason = (
            operation.error_code
            if operation.error_code in _PUBLIC_RUN_ERRORS
            else (
                "agent_discovery_failed"
                if operation.status is AgentOperationStatus.FAILED
                else "agent_discovery_skipped"
            )
        )
        reasons[reason] = reasons.get(reason, 0) + 1
    if missing_bindings and terminal:
        reasons["agent_discovery_binding_not_materialized"] = len(missing_bindings)
    if active and terminal:
        reasons["agent_discovery_not_completed"] = sum(
            operation.status
            in {
                AgentOperationStatus.PENDING,
                AgentOperationStatus.LEASED,
                AgentOperationStatus.RETRY_WAIT,
            }
            for operation in discovery
        )
    status: Literal["pending", "complete", "partial", "failed"]
    if not terminal and (active or missing_bindings):
        status = "pending"
    elif failed or missing_bindings or active:
        status = "partial" if succeeded else "failed"
    else:
        status = "complete"
    terminal_reason = next(iter(reasons), None) if status in {"partial", "failed"} else None
    return (
        CoverageDiscoveryPhaseView(
            status=status,
            terminal_reason=terminal_reason,
            source_ids=source_ids,
            max_destination_seeds=max_seeds,
            exact_verification_limit=exact_limit,
        ),
        reasons,
    )


def _anywhere_discovery_coverage_view(
    *,
    scope: Mapping[str, object],
    anywhere: Mapping[str, object],
    date_start: date,
    date_end: date,
    return_date: date | None,
    run: AgentPlanRunRecord,
    operations: Sequence[AgentRunOperationRecord],
) -> CoverageReportView:
    coverage = _required_stored_str(scope.get("coverage"), "coverage")
    if coverage not in {CoverageMode.QUICK.value, CoverageMode.FULL.value}:
        raise RuntimeError("stored coverage is invalid")
    origins, _source_ids, _max_seeds, _exact_limit, catalog, taxonomy = _anywhere_projection_values(
        anywhere
    )
    terminal = run.status in {"completed", "partial", "failed", "cancelled"}
    discovery_phase, discovery_reasons = _snapshot_anywhere_discovery_phase(
        anywhere,
        operations,
        terminal=terminal,
    )
    if terminal and not discovery_reasons:
        reason = _discovery_terminal_reason(run, operations)
        discovery_reasons = {reason: 1}
        discovery_phase = replace(
            discovery_phase,
            status="failed",
            terminal_reason=reason,
        )
    return CoverageReportView(
        coverage=coverage,
        completion="failed" if terminal else "pending",
        frozen_input=CoverageFrozenInputView(
            origins=origins,
            destinations=(),
            date_start=date_start,
            date_end=date_end,
            return_date=return_date,
            catalog_checksums=(catalog,),
            taxonomy_versions=(taxonomy,),
        ),
        planned=0,
        attempted=0,
        succeeded=0,
        failed=0,
        skipped=0,
        pairs=(),
        reason_counts=discovery_reasons,
        discovery_phase=discovery_phase,
    )


def _discovery_terminal_reason(
    run: AgentPlanRunRecord,
    operations: Sequence[AgentRunOperationRecord],
) -> str:
    for operation in operations:
        if operation.kind in {
            AgentOperationKind.SUGGEST_DISCOVERY,
            AgentOperationKind.SCOPE_FREEZE,
        } and operation.status in {AgentOperationStatus.FAILED, AgentOperationStatus.SKIPPED}:
            if operation.error_code in _PUBLIC_RUN_ERRORS:
                return operation.error_code
            return "agent_discovery_failed"
    if run.error_code in _PUBLIC_RUN_ERRORS:
        return run.error_code
    return "agent_discovery_not_completed"


def _coverage_report_view(report: CoverageReport) -> CoverageReportView:
    frozen = report.frozen_input
    return CoverageReportView(
        coverage=report.coverage,
        completion=report.completion,
        frozen_input=CoverageFrozenInputView(
            origins=frozen.origins,
            destinations=frozen.destinations,
            date_start=frozen.date_start,
            date_end=frozen.date_end,
            return_date=frozen.return_date,
            catalog_checksums=frozen.catalog_checksums,
            taxonomy_versions=frozen.taxonomy_versions,
        ),
        planned=report.planned,
        attempted=report.attempted,
        succeeded=report.succeeded,
        failed=report.failed,
        skipped=report.skipped,
        pairs=tuple(
            CoveragePairView(
                origin=item.pair.origin,
                destination=item.pair.destination,
                departure_date=item.pair.departure_date,
                return_date=item.pair.return_date,
                status=item.status.value,
                reason=item.reason,
            )
            for item in report.pairs
        ),
        reason_counts=report.reason_counts,
        discovery_phase=None,
    )


def _public_run_error(error_code: str | None) -> tuple[str | None, str | None]:
    if error_code is None:
        return None, None
    if error_code in _PUBLIC_RUN_ERRORS:
        return error_code, _PUBLIC_RUN_ERRORS[error_code]
    return "agent_run_failed", "Search failed."


def _bound_idempotent_run(
    run: AgentPlanRunRecord,
    command: ExecuteAgentPlan,
) -> AgentPlanRunRecord:
    if command.revision_id is None or (
        run.plan_id != command.plan_id or run.revision_id != command.revision_id
    ):
        raise AgentLifecycleError("agent_run_idempotency_conflict")
    return run


def _parsed_intent(revision: AgentPlanRevisionRecord) -> ParsedIntent:
    plan = _json_mapping(revision.plan_json)
    intent = _mapping(plan["intent"])
    legs: list[ParsedLeg] = []
    for raw_leg in _sequence(intent["legs"]):
        leg = _mapping(raw_leg)
        raw_constraint = _mapping(leg["date_constraint"])
        start_raw = raw_constraint.get("start_date")
        end_raw = raw_constraint.get("end_date")
        legs.append(
            ParsedLeg(
                _stored_location(leg.get("origin")),
                _stored_location(leg.get("destination")),
                ParsedDateConstraint(
                    mode=DateMode(str(raw_constraint["mode"])),
                    start_date=(
                        date.fromisoformat(start_raw) if isinstance(start_raw, str) else None
                    ),
                    end_date=date.fromisoformat(end_raw) if isinstance(end_raw, str) else None,
                    flex_days=_stored_int(raw_constraint.get("flex_days", 0), "flex_days"),
                ),
            )
        )
    clarifications = tuple(
        _stored_clarification(value) for value in _sequence(plan.get("clarifications", []))
    )
    preset_raw = intent.get("preset_id")
    return ParsedIntent(
        origin_text=cast(str | None, intent.get("origin_text")),
        destination_text=cast(str | None, intent.get("destination_text")),
        trip_shape=TripShape(str(intent["trip_shape"])),
        date_mode=DateMode(str(intent["date_mode"])),
        legs=tuple(legs),
        adults=_stored_int(intent["adults"], "adults"),
        children=_stored_int(intent["children"], "children"),
        infants=_stored_int(intent["infants"], "infants"),
        nearby_radius_km=_stored_int(intent.get("nearby_radius_km", 0), "nearby_radius_km"),
        currency=str(intent["currency"]),
        requested_strategies=tuple(
            RouteStrategy(str(value)) for value in _sequence(intent.get("requested_strategies", []))
        ),
        clarifications=clarifications,
        preset_id=AgentPresetId(str(preset_raw)) if preset_raw is not None else None,
    )


def _stored_location(value: object) -> LocationScope | None:
    if value is None:
        return None
    payload = _mapping(value)
    raw_value = payload.get("value")
    return LocationScope(
        LocationScopeKind(str(payload["kind"])),
        str(raw_value) if raw_value is not None else None,
    )


def _stored_clarification(value: object) -> IntentClarification:
    payload = _mapping(value)
    actions = tuple(
        ClarificationAction(
            action_id=str(action["action_id"]),
            label_ru=str(action["label_ru"]),
            selections={
                str(key): str(item) for key, item in _mapping(action["selections"]).items()
            },
            date_mode=(
                DateMode(str(action["date_mode"])) if action.get("date_mode") is not None else None
            ),
        )
        for action in (_mapping(item) for item in _sequence(payload.get("actions", [])))
    )
    details: dict[str, int | str] = {
        str(key): item
        for key, item in _mapping(payload.get("details", {})).items()
        if isinstance(item, (int, str)) and not isinstance(item, bool)
    }
    return IntentClarification(
        field=str(payload["field"]),
        code=str(payload["code"]),
        message_ru=str(payload["message_ru"]),
        actions=actions,
        details=details,
    )


def _parser_selections(parsed: ParsedIntent) -> dict[str, object]:
    values: dict[str, object] = {
        "adults": parsed.adults,
        "children": parsed.children,
        "infants": parsed.infants,
        "currency": parsed.currency,
        "trip_shape": parsed.trip_shape.value,
        "requested_strategies": [strategy.value for strategy in parsed.requested_strategies],
    }
    values["nearby_radius_km"] = parsed.nearby_radius_km
    if parsed.trip_shape.value in {"open_jaw", "multi_city"}:
        values["legs"] = [
            {
                "origin": leg.origin,
                "destination": leg.destination,
                "date": (
                    leg.date_constraint.start_date.isoformat()
                    if leg.date_constraint.start_date is not None
                    else None
                ),
            }
            for leg in parsed.legs
        ]
        return values
    if not parsed.legs:
        return values
    first = parsed.legs[0]
    values["origin"] = first.origin
    values["destination"] = first.destination
    constraint = first.date_constraint
    values["date_mode"] = parsed.date_mode.value
    if constraint.start_date is not None:
        if parsed.date_mode.value == "range":
            values["date_start"] = constraint.start_date.isoformat()
        else:
            values["departure_date"] = constraint.start_date.isoformat()
    if constraint.end_date is not None:
        values["date_end"] = constraint.end_date.isoformat()
    if constraint.flex_days:
        values["flex_days"] = constraint.flex_days
    if parsed.trip_shape.value == "round_trip" and len(parsed.legs) > 1:
        return_date = parsed.legs[1].date_constraint.start_date
        if return_date is not None:
            values["return_date"] = return_date.isoformat()
    return values


def _independent_parser_selections(parsed: ParsedIntent) -> dict[str, object]:
    return {
        "adults": parsed.adults,
        "children": parsed.children,
        "infants": parsed.infants,
        "currency": parsed.currency,
        "requested_strategies": [strategy.value for strategy in parsed.requested_strategies],
    }


def _route_text(parsed: ParsedIntent) -> str:
    if not parsed.legs:
        return ""
    first = parsed.legs[0]
    return f"{_scope_text(first.origin)} → {_scope_text(first.destination)}"


def _scope_text(scope: LocationScope | None) -> str:
    if scope is None:
        return ""
    if scope.kind is LocationScopeKind.ANYWHERE:
        return "anywhere"
    assert scope.value is not None
    return f"{scope.kind.value}:{scope.value}"


def _stored_coverage(revision: AgentPlanRevisionRecord) -> str:
    return str(_json_mapping(revision.plan_json)["coverage"])


def _stored_strategies(revision: AgentPlanRevisionRecord) -> tuple[str, ...]:
    intent = _mapping(_json_mapping(revision.plan_json)["intent"])
    return tuple(str(value) for value in _sequence(intent.get("requested_strategies", [])))


def _approved_budget(revision: AgentPlanRevisionRecord) -> dict[str, object]:
    estimate = _estimate_view(revision)
    if estimate is None:
        raise AgentLifecycleError("agent_plan_approval_required")
    return {
        "calendar_searches": estimate.calendar_searches,
        "exact_searches": estimate.exact_searches,
        "logical_operations": estimate.logical_operations,
        "http_attempts": estimate.http_attempts,
        "deadline_seconds": estimate.deadline_seconds,
    }


def _lifecycle_error(error: AgentPlanError) -> AgentLifecycleError:
    mapping = {
        "agent_plan_not_found": "agent_plan_not_found",
        "agent_plan_stale": "agent_plan_stale",
        "agent_plan_expired": "agent_plan_expired",
        "agent_plan_active_run": "agent_run_already_active",
        "agent_approval_consumed": "agent_plan_consumed",
    }
    return AgentLifecycleError(mapping.get(error.code, error.code))


def _execution_error(error: AgentPlanConflict, prior_state: str) -> AgentLifecycleError:
    if error.code == "agent_plan_active_run":
        return AgentLifecycleError("agent_run_already_active")
    if error.code == "agent_approval_consumed" or prior_state == "consumed":
        return AgentLifecycleError("agent_plan_consumed")
    if error.code in {"agent_approval_expired", "agent_plan_expired"}:
        return AgentLifecycleError("agent_plan_expired")
    if error.code in {"agent_approval_snapshot_mismatch", "agent_plan_stale"}:
        return AgentLifecycleError("agent_plan_stale")
    return AgentLifecycleError(error.code)


def _json_mapping(raw: str) -> Mapping[str, object]:
    return _mapping(json.loads(raw))


def _revision_passenger_mix(revision: AgentPlanRevisionRecord) -> PassengerMix:
    intent = _mapping(_json_mapping(revision.plan_json)["intent"])
    return PassengerMix(
        adults=_stored_int(intent["adults"], "adults"),
        children=_stored_int(intent["children"], "children"),
        infants=_stored_int(intent["infants"], "infants"),
    )


def _hidden_city_candidates_from_records(
    revision: AgentPlanRevisionRecord,
    records: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> tuple[HiddenCityCandidate, ...]:
    hidden_records = tuple(
        record
        for record in records
        if record.itinerary_evidence.get("search_role") == "hidden_city"
    )
    plan = _json_mapping(revision.plan_json)
    raw_rule = plan.get("hidden_city")
    if not hidden_records:
        if raw_rule is not None:
            _mapping(raw_rule)
        return ()
    rule = _mapping(raw_rule)
    if _required_stored_str(rule.get("version"), "hidden-city rule version") != (
        "hidden-city-search-v1"
    ):
        raise StoredAgentEvidenceError("hidden-city rule version is invalid")
    plan_leg_index = _stored_int(
        rule.get("plan_leg_index"),
        "hidden-city plan leg index",
    )
    desired_airports = tuple(
        _required_stored_str(value, "hidden-city desired airport")
        for value in _sequence(rule.get("desired_airports", ()))
    )
    intent = _mapping(plan["intent"])
    final_plan_leg_index = len(_sequence(intent.get("legs", ()))) - 1
    if (
        plan_leg_index != final_plan_leg_index
        or final_plan_leg_index < 0
        or not desired_airports
        or len(set(desired_airports)) != len(desired_airports)
    ):
        raise StoredAgentEvidenceError("hidden-city rule leg binding is invalid")
    passenger_mix = _revision_passenger_mix(revision)
    candidates: list[HiddenCityCandidate] = []
    for record in hidden_records:
        if (
            record.baggage_status is None
            or record.freshness is not Freshness.LIVE
            or record.itinerary_evidence.get("checked_baggage") != record.baggage_status.value
        ):
            raise StoredAgentEvidenceError(
                "hidden-city evidence requires explicit live baggage facts"
            )
        itinerary = record.itinerary_evidence
        desired_airport = _required_stored_str(
            itinerary.get("hidden_city_desired_airport"),
            "hidden-city desired airport",
        )
        if desired_airport not in desired_airports:
            raise StoredAgentEvidenceError("hidden-city desired airport is not approved")
        evidence = confirmed_record_to_evidence(
            record,
            fallback_passenger_mix=passenger_mix,
        )
        decision = classify_hidden_city(
            evidence,
            desired_airport,
            HiddenCityContext(
                plan_leg_index=plan_leg_index,
                final_plan_leg_index=final_plan_leg_index,
            ),
        )
        candidate = decision.candidate
        if (
            candidate is None
            or itinerary.get("hidden_city_ticketed_destination") != candidate.ticketed_destination
            or itinerary.get("hidden_city_actionability") != candidate.actionability.value
            or itinerary.get("hidden_city_warning_version") != HIDDEN_CITY_WARNING_VERSION
            or itinerary.get("booking_action_available") is not False
            or itinerary.get("watch_available") is not False
        ):
            raise StoredAgentEvidenceError("hidden-city evidence metadata is invalid")
        candidates.append(candidate)
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                candidate.source_evidence.total_amount.minor_units,
                -candidate.source_evidence.observed_at.timestamp(),
                str(candidate.source_evidence.id),
            ),
        )
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RuntimeError("stored agent plan JSON must contain objects")
    return {str(key): item for key, item in value.items()}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise RuntimeError("stored agent plan JSON must contain arrays")
    return value


def _stored_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError(f"stored agent plan {field_name} must be an integer")
    return value


def _optional_stored_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _stored_int(value, field_name)


def _required_stored_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"stored agent plan {field_name} must be a non-empty string")
    return value


def _optional_stored_str(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_stored_str(value, field_name)
