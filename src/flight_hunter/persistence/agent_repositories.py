from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from types import MappingProxyType
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import Table, and_, case, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.domain.agent_evidence import (
    DiscoverySource,
    PriceComparisonStatus,
    ProtectionStatus,
    UnknownCostKind,
)
from flight_hunter.domain.agent_search import TripShape
from flight_hunter.domain.money import MAX_MONEY_MINOR_UNITS
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.models import (
    agent_booking_action_descriptors_table,
    agent_composed_route_candidates_table,
    agent_confirmed_offer_evidence_table,
    agent_discovery_signals_table,
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
    agent_plan_stages_table,
    agent_provider_circuit_state_table,
    agent_provider_http_attempts_table,
    agent_provider_rate_locks_table,
    agent_ranking_snapshots_table,
    agent_run_operations_table,
    agent_run_scope_snapshots_table,
    agent_search_plan_revisions_table,
    agent_search_plans_table,
)

AgentPlanRevisionState = Literal[
    "draft",
    "awaiting_approval",
    "superseded",
    "consumed",
    "expired",
]
AgentRunStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "partial",
    "failed",
    "cancelled",
]

_NEW_REVISION_STATES = frozenset({"draft", "awaiting_approval"})
_ACTIVE_RUN_STATUSES = ("queued", "running", "cancel_requested")
_RUN_STATUSES = frozenset(
    {
        "queued",
        "running",
        "cancel_requested",
        "completed",
        "partial",
        "failed",
        "cancelled",
    }
)
_TERMINAL_RUN_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
_TRANSITION_SOURCES: dict[str, tuple[str, ...]] = {
    "running": ("queued",),
    "cancel_requested": ("queued", "running"),
    "completed": ("running",),
    "partial": ("running",),
    "failed": ("running",),
    "cancelled": ("cancel_requested",),
}


class AgentIntegrityConstraint(StrEnum):
    REVISION_NUMBER = "uq_agent_plan_revision_number"
    REVISION_HASH = "uq_agent_plan_revision_hash"
    CLONE_IDEMPOTENCY = "ix_agent_plan_revision_clone_idempotency"
    EXECUTE_IDEMPOTENCY = "uq_agent_run_execute_idempotency"
    ACTIVE_RUN = "ix_agent_plan_one_active_run"
    APPROVAL_RUN = "uq_agent_approval_run"
    RUN_APPROVAL = "uq_agent_run_approval"


_SQLITE_INTEGRITY_SIGNATURES = {
    (
        "UNIQUE constraint failed: agent_search_plan_revisions.plan_id, "
        "agent_search_plan_revisions.revision_number"
    ): AgentIntegrityConstraint.REVISION_NUMBER,
    (
        "UNIQUE constraint failed: agent_search_plan_revisions.plan_id, "
        "agent_search_plan_revisions.content_hash"
    ): AgentIntegrityConstraint.REVISION_HASH,
    (
        "UNIQUE constraint failed: agent_search_plan_revisions.household_id, "
        "agent_search_plan_revisions.clone_idempotency_key"
    ): AgentIntegrityConstraint.CLONE_IDEMPOTENCY,
    (
        "UNIQUE constraint failed: agent_plan_runs.household_id, "
        "agent_plan_runs.execute_idempotency_key"
    ): AgentIntegrityConstraint.EXECUTE_IDEMPOTENCY,
    "UNIQUE constraint failed: agent_plan_runs.plan_id": AgentIntegrityConstraint.ACTIVE_RUN,
    (
        "UNIQUE constraint failed: agent_plan_execution_approvals.run_id"
    ): AgentIntegrityConstraint.APPROVAL_RUN,
    "UNIQUE constraint failed: agent_plan_runs.approval_id": AgentIntegrityConstraint.RUN_APPROVAL,
}


def classify_agent_integrity_constraint(
    error: IntegrityError,
) -> AgentIntegrityConstraint | None:
    diagnostic = getattr(error.orig, "diag", None)
    constraint_name = getattr(diagnostic, "constraint_name", None)
    if isinstance(constraint_name, str):
        try:
            return AgentIntegrityConstraint(constraint_name)
        except ValueError:
            return None
    return _SQLITE_INTEGRITY_SIGNATURES.get(str(error.orig))


class AgentPlanError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AgentPlanNotFound(AgentPlanError):
    pass


class AgentPlanConflict(AgentPlanError):
    pass


@dataclass(frozen=True, slots=True)
class AgentPlanApprovalSnapshot:
    revision_content_hash: str
    approved_by_session_id: UUID
    approved_budget: Mapping[str, object]
    approved_strategies: tuple[str, ...]
    risk_warning_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        approved_budget = _deep_freeze(self.approved_budget)
        approved_strategies = _deep_freeze(self.approved_strategies)
        risk_warning_versions = _deep_freeze(self.risk_warning_versions)
        object.__setattr__(
            self,
            "approved_budget",
            cast(Mapping[str, object], approved_budget),
        )
        object.__setattr__(
            self,
            "approved_strategies",
            cast(tuple[str, ...], approved_strategies),
        )
        object.__setattr__(
            self,
            "risk_warning_versions",
            cast(Mapping[str, str], risk_warning_versions),
        )


@dataclass(frozen=True, slots=True)
class NewAgentPlan:
    id: UUID
    household_id: UUID
    created_by_user_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewAgentPlanRevision:
    id: UUID
    state: AgentPlanRevisionState
    plan: Mapping[str, object]
    scope_snapshot: Mapping[str, object]
    capability_snapshot: Mapping[str, object]
    cost_model_snapshot: Mapping[str, object]
    parser_version: str
    planner_version: str
    estimated_calendar_searches: int | None
    estimated_exact_searches: int | None
    estimated_logical_operations: int | None
    estimated_http_attempts: int | None
    estimated_deadline_seconds: int | None
    expires_at: datetime
    created_at: datetime
    clone_idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AgentPlanRecord:
    id: UUID
    household_id: UUID
    created_by_user_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentPlanRevisionRecord:
    id: UUID
    plan_id: UUID
    household_id: UUID
    source_revision_id: UUID | None
    revision_number: int
    state: str
    plan_json: str
    scope_snapshot_json: str
    capability_snapshot_json: str
    cost_model_snapshot_json: str
    parser_version: str
    planner_version: str
    estimated_calendar_searches: int | None
    estimated_exact_searches: int | None
    estimated_logical_operations: int | None
    estimated_http_attempts: int | None
    estimated_deadline_seconds: int | None
    content_hash: str
    clone_idempotency_key: str | None
    created_at: datetime
    expires_at: datetime
    superseded_at: datetime | None
    consumed_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewAgentPlanApproval:
    id: UUID
    household_id: UUID
    revision_id: UUID
    approved_by_user_id: UUID
    approved_at: datetime
    expires_at: datetime
    snapshot: AgentPlanApprovalSnapshot


@dataclass(frozen=True, slots=True)
class AgentPlanApprovalRecord:
    id: UUID
    household_id: UUID
    plan_id: UUID
    revision_id: UUID
    approved_by_user_id: UUID
    approved_at: datetime
    expires_at: datetime
    snapshot: AgentPlanApprovalSnapshot
    consumed_at: datetime | None
    run_id: UUID | None


@dataclass(frozen=True, slots=True)
class NewAgentPlanRun:
    id: UUID
    execute_idempotency_key: str
    created_at: datetime
    deadline_at: datetime


@dataclass(frozen=True, slots=True)
class AgentPlanRunRecord:
    id: UUID
    household_id: UUID
    plan_id: UUID
    revision_id: UUID
    approval_id: UUID
    execute_idempotency_key: str
    status: str
    created_at: datetime
    deadline_at: datetime
    started_at: datetime | None
    cancel_requested_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    logical_operation_budget: int
    logical_operations_consumed: int
    http_attempt_budget: int
    http_attempts_consumed: int


class AgentPlanStageKind(StrEnum):
    SCOPE = "scope"
    CALENDAR_DISCOVERY = "calendar_discovery"
    EXACT_SEARCH = "exact_search"
    COMPOSITION = "composition"
    RANKING = "ranking"
    ANALYSIS = "analysis"


class AgentStageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AgentOperationKind(StrEnum):
    SCOPE_FREEZE = "scope_freeze"
    CALENDAR_SEARCH = "calendar_search"
    EXACT_START = "exact_start"
    EXACT_POLL = "exact_poll"
    SUGGEST_DISCOVERY = "suggest_discovery"
    COMPARISON = "comparison"
    COMPOSITION = "composition"
    RANKING = "ranking"
    ANALYSIS = "analysis"


class AgentOperationStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentOperationResultType(StrEnum):
    SCOPE_SNAPSHOT = "scope_snapshot"
    DISCOVERY_SIGNAL = "discovery_signal"
    CONFIRMED_OFFER = "confirmed_offer"
    COMPOSED_CANDIDATE = "composed_candidate"
    RANKING_SNAPSHOT = "ranking_snapshot"
    OPERATION = "operation"


class BaggageEvidenceStatus(StrEnum):
    INCLUDED = "included"
    NOT_INCLUDED = "not_included"
    UNKNOWN = "unknown"


class TransferEvidenceStatus(StrEnum):
    PROTECTED = "protected"
    SELF_TRANSFER = "self_transfer"
    UNKNOWN = "unknown"


class VisaEvidenceStatus(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class AttemptKind(StrEnum):
    START = "start"
    POLL = "poll"
    RETRY = "retry"


class AttemptReservationStatus(StrEnum):
    RESERVED = "reserved"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"


class AgentCircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitPermitStatus(StrEnum):
    ALLOWED = "allowed"
    OPEN = "open"
    HALF_OPEN_PROBE = "half_open_probe"


class CircuitPermitMode(StrEnum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"


class CircuitOutcome(StrEnum):
    SUCCESS = "success"
    TRANSIENT_FAILURE = "transient_failure"
    NON_TRANSIENT_FAILURE = "non_transient_failure"


class AgentOperationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AgentOperationConflict(AgentOperationError):
    """A concurrent or invalid execution-ledger mutation was rejected."""


class AgentEvidenceError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AttemptReservationResult:
    status: AttemptReservationStatus
    retry_at: datetime | None = None
    reservation_id: UUID | None = None
    reused: bool = False

    def __post_init__(self) -> None:
        status = AttemptReservationStatus(self.status)
        if type(self.reused) is not bool:
            raise TypeError("reused must be bool")
        if status is AttemptReservationStatus.RESERVED:
            if not isinstance(self.reservation_id, UUID):
                raise ValueError("reserved attempt requires reservation_id")
            if self.retry_at is not None:
                raise ValueError("retry_at is only valid for rate_limited reservations")
        elif status is AttemptReservationStatus.RATE_LIMITED:
            if self.retry_at is None:
                raise ValueError("rate_limited reservation requires retry_at")
            _require_aware(self.retry_at, "retry_at")
            if self.reservation_id is not None or self.reused:
                raise ValueError("denied reservation cannot have an identity")
        else:
            if self.retry_at is not None:
                raise ValueError("retry_at is only valid for rate_limited reservations")
            if self.reservation_id is not None or self.reused:
                raise ValueError("denied reservation cannot have an identity")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class ServerPrivateCircuitPermit:
    provider_id: str
    operation_id: UUID
    operation_attempt_number: int
    generation: int
    mode: CircuitPermitMode
    token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id must not be blank")
        if not isinstance(self.operation_id, UUID):
            raise TypeError("operation_id must be UUID")
        if type(self.operation_attempt_number) is not int or self.operation_attempt_number <= 0:
            raise ValueError("operation_attempt_number must be positive")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("generation must be non-negative")
        if not isinstance(self.token, str) or not self.token:
            raise ValueError("permit token must not be blank")
        _require_aware(self.expires_at, "expires_at")
        object.__setattr__(self, "mode", CircuitPermitMode(self.mode))


@dataclass(frozen=True, slots=True)
class CircuitPermitResult:
    status: CircuitPermitStatus
    retry_at: datetime | None = None
    permit: ServerPrivateCircuitPermit | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        status = CircuitPermitStatus(self.status)
        if status is CircuitPermitStatus.OPEN:
            if self.retry_at is None:
                raise ValueError("open circuit permit requires retry_at")
            _require_aware(self.retry_at, "retry_at")
            if self.permit is not None:
                raise ValueError("open circuit result cannot include permit")
        else:
            if self.retry_at is not None:
                raise ValueError("retry_at is only valid for an open circuit permit")
            if self.permit is None:
                raise ValueError("allowed circuit result requires permit")
            expected_mode = (
                CircuitPermitMode.CLOSED
                if status is CircuitPermitStatus.ALLOWED
                else CircuitPermitMode.HALF_OPEN
            )
            if self.permit.mode is not expected_mode:
                raise ValueError("circuit permit mode does not match status")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class NewAgentPlanStage:
    id: UUID
    household_id: UUID
    run_id: UUID
    kind: AgentPlanStageKind
    status: AgentStageStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentPlanStageRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    kind: AgentPlanStageKind
    status: AgentStageStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AgentStageProgress:
    stage_id: UUID
    total: int
    pending: int
    leased: int
    retry_wait: int
    succeeded: int
    failed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class AgentRunLedgerProgress:
    run_id: UUID
    stage_total: int = 0
    stage_pending: int = 0
    stage_running: int = 0
    stage_completed: int = 0
    stage_partial: int = 0
    stage_failed: int = 0
    stage_skipped: int = 0
    stage_cancelled: int = 0
    operation_total: int = 0
    operation_attempted: int = 0
    operation_pending: int = 0
    operation_leased: int = 0
    operation_retry_wait: int = 0
    operation_succeeded: int = 0
    operation_failed: int = 0
    operation_skipped: int = 0


@dataclass(frozen=True, slots=True)
class NewAgentRunOperation:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str | None
    kind: AgentOperationKind
    operation_fingerprint: str
    logical_operation_fingerprint: str
    consumes_logical_unit: bool
    immutable_input: Mapping[str, object]
    private_continuation: Mapping[str, object] | None = field(repr=False)
    max_attempts: int
    created_at: datetime
    logical_root_operation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AgentRunOperationRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str | None
    kind: AgentOperationKind
    operation_fingerprint: str
    logical_operation_fingerprint: str
    logical_root_operation_id: UUID | None
    handoff_predecessor_operation_id: UUID | None
    consumes_logical_unit: bool
    immutable_input: Mapping[str, object]
    status: AgentOperationStatus
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    next_retry_at: datetime | None
    http_attempts_consumed: int
    result_type: AgentOperationResultType | None
    result_id: UUID | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "immutable_input",
            cast(Mapping[str, object], _deep_freeze(self.immutable_input)),
        )


@dataclass(frozen=True, slots=True)
class ServerPrivateOperationLease:
    operation: AgentRunOperationRecord
    private_continuation: Mapping[str, object] | None = field(repr=False)

    def __post_init__(self) -> None:
        if self.private_continuation is not None:
            object.__setattr__(
                self,
                "private_continuation",
                cast(Mapping[str, object], _deep_freeze(self.private_continuation)),
            )


@dataclass(frozen=True, slots=True)
class NewAgentRunScopeSnapshot:
    id: UUID
    household_id: UUID
    run_id: UUID
    fingerprint: str
    snapshot: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentRunScopeSnapshotRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    fingerprint: str
    snapshot: Mapping[str, object]
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot",
            cast(Mapping[str, object], _deep_freeze(self.snapshot)),
        )


@dataclass(frozen=True, slots=True)
class AgentCircuitStateRecord:
    provider_id: str
    state: AgentCircuitState
    consecutive_transient_failures: int
    opened_at: datetime | None
    cooldown_until: datetime | None
    half_open_probe_operation_id: UUID | None
    half_open_probe_attempt_number: int | None
    half_open_probe_expires_at: datetime | None
    generation: int
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewAgentDiscoverySignal:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    amount_minor: int | None
    currency: str | None
    passengers: int
    passenger_basis: PriceBasis
    source_kind: DiscoverySource
    freshness: Freshness
    observed_at: datetime
    signal_evidence: Mapping[str, object]
    fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentDiscoverySignalRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    amount_minor: int | None
    currency: str | None
    passengers: int
    passenger_basis: PriceBasis
    source_kind: DiscoverySource
    freshness: Freshness
    observed_at: datetime
    signal_evidence: Mapping[str, object]
    fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "signal_evidence",
            cast(Mapping[str, object], _deep_freeze(self.signal_evidence)),
        )


@dataclass(frozen=True, slots=True)
class NewAgentConfirmedOfferEvidence:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str
    source: str
    observed_at: datetime
    freshness: Freshness
    passengers: int
    passenger_basis: PriceBasis
    amount_minor: int | None
    currency: str | None
    itinerary_evidence: Mapping[str, object]
    protection_status: ProtectionStatus
    baggage_status: BaggageEvidenceStatus | None
    transfer_status: TransferEvidenceStatus | None
    visa_status: VisaEvidenceStatus | None
    fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentConfirmedOfferEvidenceRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str
    source: str
    observed_at: datetime
    freshness: Freshness
    passengers: int
    passenger_basis: PriceBasis
    amount_minor: int | None
    currency: str | None
    itinerary_evidence: Mapping[str, object]
    protection_status: ProtectionStatus
    baggage_status: BaggageEvidenceStatus | None
    transfer_status: TransferEvidenceStatus | None
    visa_status: VisaEvidenceStatus | None
    fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "itinerary_evidence",
            cast(Mapping[str, object], _deep_freeze(self.itinerary_evidence)),
        )


@dataclass(frozen=True, slots=True, repr=False)
class NewAgentBookingActionDescriptor:
    id: UUID
    household_id: UUID
    run_id: UUID
    confirmed_evidence_id: UUID
    provider_id: str
    private_descriptor: Mapping[str, object] = field(repr=False)
    fingerprint: str
    created_at: datetime
    expires_at: datetime

    def __repr__(self) -> str:
        return "NewAgentBookingActionDescriptor(<private>)"


@dataclass(frozen=True, slots=True, repr=False)
class AgentBookingActionDescriptorRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    confirmed_evidence_id: UUID
    provider_id: str
    private_descriptor: Mapping[str, object] = field(repr=False)
    fingerprint: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "private_descriptor",
            cast(Mapping[str, object], _deep_freeze(self.private_descriptor)),
        )

    def __repr__(self) -> str:
        return "AgentBookingActionDescriptorRecord(<private>)"


@dataclass(frozen=True, slots=True)
class NewAgentComposedRouteCandidate:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    component_evidence_ids: tuple[UUID, ...]
    observed_at: datetime
    passengers: int
    passenger_basis: PriceBasis
    amount_minor: int | None
    currency: str | None
    itinerary_evidence: Mapping[str, object]
    protection_status: ProtectionStatus
    baggage_status: BaggageEvidenceStatus | None
    transfer_status: TransferEvidenceStatus | None
    visa_status: VisaEvidenceStatus | None
    fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentComposedRouteCandidateRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    component_evidence_ids: tuple[UUID, ...]
    observed_at: datetime
    passengers: int
    passenger_basis: PriceBasis
    amount_minor: int | None
    currency: str | None
    itinerary_evidence: Mapping[str, object]
    protection_status: ProtectionStatus
    baggage_status: BaggageEvidenceStatus | None
    transfer_status: TransferEvidenceStatus | None
    visa_status: VisaEvidenceStatus | None
    fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "itinerary_evidence",
            cast(Mapping[str, object], _deep_freeze(self.itinerary_evidence)),
        )


@dataclass(frozen=True, slots=True)
class NewAgentRankingSnapshot:
    id: UUID
    household_id: UUID
    run_id: UUID
    confirmed_evidence_ids: tuple[UUID, ...]
    composed_candidate_ids: tuple[UUID, ...]
    ranking: Mapping[str, object]
    fingerprint: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentRankingSnapshotRecord:
    id: UUID
    household_id: UUID
    run_id: UUID
    confirmed_evidence_ids: tuple[UUID, ...]
    composed_candidate_ids: tuple[UUID, ...]
    ranking: Mapping[str, object]
    fingerprint: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ranking",
            cast(Mapping[str, object], _deep_freeze(self.ranking)),
        )


class AgentPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_plan(
        self,
        plan: NewAgentPlan,
        initial_revision: NewAgentPlanRevision,
    ) -> AgentPlanRevisionRecord:
        _require_aware(plan.created_at, "created_at")
        _validate_new_revision(initial_revision)
        try:
            await self._session.execute(
                insert(agent_search_plans_table).values(
                    id=str(plan.id),
                    household_id=str(plan.household_id),
                    created_by_user_id=str(plan.created_by_user_id),
                    created_at=_utc_datetime(plan.created_at),
                )
            )
            await self._session.execute(
                insert(agent_search_plan_revisions_table).values(
                    **_revision_values(
                        plan_id=plan.id,
                        household_id=plan.household_id,
                        source_revision_id=None,
                        revision_number=1,
                        revision=initial_revision,
                    )
                )
            )
        except IntegrityError as error:
            constraint = classify_agent_integrity_constraint(error)
            if constraint in {
                AgentIntegrityConstraint.REVISION_NUMBER,
                AgentIntegrityConstraint.REVISION_HASH,
            }:
                raise AgentPlanConflict("agent_plan_conflict") from error
            raise

        stored = await self.get_revision(plan.household_id, initial_revision.id)
        if stored is None:
            raise RuntimeError("created agent plan revision is missing")
        return stored

    async def get_plan(self, household_id: UUID, plan_id: UUID) -> AgentPlanRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_search_plans_table)
                    .where(agent_search_plans_table.c.id == str(plan_id))
                    .where(agent_search_plans_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _plan_record(row) if row is not None else None

    async def get_revision(
        self,
        household_id: UUID,
        revision_id: UUID,
    ) -> AgentPlanRevisionRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.id == str(revision_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _revision_record(row) if row is not None else None

    async def get_revisions_by_ids(
        self,
        household_id: UUID,
        revision_ids: Sequence[UUID],
    ) -> Mapping[UUID, AgentPlanRevisionRecord]:
        ids = _bounded_uuid_ids(revision_ids, "revision_ids")
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                select(agent_search_plan_revisions_table)
                .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                .where(
                    agent_search_plan_revisions_table.c.id.in_(
                        tuple(str(revision_id) for revision_id in ids)
                    )
                )
            )
        ).mappings()
        records = tuple(_revision_record(row) for row in rows)
        return {record.id: record for record in records}

    async def get_revision_for_update(
        self,
        household_id: UUID,
        plan_id: UUID,
        revision_id: UUID,
    ) -> AgentPlanRevisionRecord | None:
        statement = (
            select(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == str(revision_id))
            .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
            .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return _revision_record(row) if row is not None else None

    async def list_revisions(
        self,
        household_id: UUID,
        plan_id: UUID,
    ) -> tuple[AgentPlanRevisionRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_search_plan_revisions_table)
                .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
                .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                .order_by(
                    agent_search_plan_revisions_table.c.revision_number.asc(),
                    agent_search_plan_revisions_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_revision_record(row) for row in rows)

    async def create_successor(
        self,
        *,
        household_id: UUID,
        source_revision_id: UUID,
        revision: NewAgentPlanRevision,
    ) -> AgentPlanRevisionRecord:
        _validate_new_revision(revision)
        await _acquire_sqlite_write_transaction(self._session)

        try:
            async with self._session.begin_nested():
                result = await self._session.execute(
                    update(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.id == str(source_revision_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                    .where(
                        agent_search_plan_revisions_table.c.state.in_(
                            ("draft", "awaiting_approval")
                        )
                    )
                    .where(agent_search_plan_revisions_table.c.superseded_at.is_(None))
                    .values(
                        state="superseded",
                        superseded_at=_utc_datetime(revision.created_at),
                    )
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    if revision.clone_idempotency_key is not None:
                        existing = await self._find_clone(
                            household_id,
                            revision.clone_idempotency_key,
                        )
                        if existing is not None:
                            return existing
                    source = await self.get_revision(household_id, source_revision_id)
                    if source is None:
                        raise AgentPlanNotFound("agent_plan_not_found")
                    raise AgentPlanConflict("agent_plan_stale")

                source_row = (
                    (
                        await self._session.execute(
                            select(agent_search_plan_revisions_table)
                            .where(
                                agent_search_plan_revisions_table.c.id == str(source_revision_id)
                            )
                            .where(
                                agent_search_plan_revisions_table.c.household_id
                                == str(household_id)
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                await self._session.execute(
                    insert(agent_search_plan_revisions_table).values(
                        **_revision_values(
                            plan_id=UUID(str(source_row["plan_id"])),
                            household_id=household_id,
                            source_revision_id=source_revision_id,
                            revision_number=int(source_row["revision_number"]) + 1,
                            revision=revision,
                        )
                    )
                )
        except IntegrityError as error:
            constraint = classify_agent_integrity_constraint(error)
            if (
                constraint is AgentIntegrityConstraint.CLONE_IDEMPOTENCY
                and revision.clone_idempotency_key is not None
            ):
                existing = await self._find_clone(
                    household_id,
                    revision.clone_idempotency_key,
                )
                if existing is not None:
                    return existing
            if constraint in {
                AgentIntegrityConstraint.REVISION_NUMBER,
                AgentIntegrityConstraint.REVISION_HASH,
            }:
                raise AgentPlanConflict("agent_plan_duplicate_revision") from error
            raise

        stored = await self.get_revision(household_id, revision.id)
        if stored is None:
            raise RuntimeError("created successor revision is missing")
        return stored

    async def expire_revision(
        self,
        *,
        household_id: UUID,
        plan_id: UUID,
        revision_id: UUID,
        expired_at: datetime,
    ) -> AgentPlanRevisionRecord:
        _require_aware(expired_at, "expired_at")
        normalized_expired_at = _utc_datetime(expired_at)
        result = await self._session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == str(revision_id))
            .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
            .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
            .where(agent_search_plan_revisions_table.c.state == "awaiting_approval")
            .where(agent_search_plan_revisions_table.c.expires_at <= normalized_expired_at)
            .where(agent_search_plan_revisions_table.c.superseded_at.is_(None))
            .where(agent_search_plan_revisions_table.c.consumed_at.is_(None))
            .values(state="expired")
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            stored = await self.get_revision_for_update(
                household_id,
                plan_id,
                revision_id,
            )
            if stored is None:
                raise AgentPlanNotFound("agent_plan_not_found")
            return stored
        stored = await self.get_revision_for_update(household_id, plan_id, revision_id)
        if stored is None:
            raise RuntimeError("expired agent plan revision is missing")
        return stored

    async def create_clone(
        self,
        *,
        household_id: UUID,
        plan_id: UUID,
        source_revision_id: UUID,
        revision: NewAgentPlanRevision,
    ) -> AgentPlanRevisionRecord:
        _validate_new_revision(revision)
        if revision.clone_idempotency_key is None:
            raise ValueError("clone revision requires an idempotency key")
        await _acquire_sqlite_write_transaction(self._session)
        existing = await self._find_clone(household_id, revision.clone_idempotency_key)
        if existing is not None:
            return existing

        try:
            async with self._session.begin_nested():
                source_statement = (
                    select(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.id == str(source_revision_id))
                    .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                )
                latest_statement = (
                    select(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                    .order_by(agent_search_plan_revisions_table.c.revision_number.desc())
                    .limit(1)
                )
                if self._session.get_bind().dialect.name != "sqlite":
                    source_statement = source_statement.with_for_update()
                    latest_statement = latest_statement.with_for_update()
                source_row = (
                    (await self._session.execute(source_statement)).mappings().one_or_none()
                )
                if source_row is None:
                    raise AgentPlanNotFound("agent_plan_not_found")
                if str(source_row["state"]) not in {"consumed", "expired", "superseded"}:
                    raise AgentPlanConflict("agent_plan_stale")

                latest_row = (await self._session.execute(latest_statement)).mappings().one()
                next_revision_number = int(latest_row["revision_number"]) + 1
                generated_revision = _with_clone_approval_generation(
                    revision,
                    generation=next_revision_number,
                )
                await self._session.execute(
                    update(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.plan_id == str(plan_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                    .where(
                        agent_search_plan_revisions_table.c.state.in_(
                            ("draft", "awaiting_approval")
                        )
                    )
                    .where(agent_search_plan_revisions_table.c.superseded_at.is_(None))
                    .values(
                        state="superseded",
                        superseded_at=_utc_datetime(generated_revision.created_at),
                    )
                )
                await self._session.execute(
                    insert(agent_search_plan_revisions_table).values(
                        **_revision_values(
                            plan_id=plan_id,
                            household_id=household_id,
                            source_revision_id=source_revision_id,
                            revision_number=next_revision_number,
                            revision=generated_revision,
                        )
                    )
                )
        except IntegrityError as error:
            constraint = classify_agent_integrity_constraint(error)
            if constraint is AgentIntegrityConstraint.CLONE_IDEMPOTENCY:
                existing = await self._find_clone(
                    household_id,
                    revision.clone_idempotency_key,
                )
                if existing is not None:
                    return existing
            if constraint in {
                AgentIntegrityConstraint.REVISION_NUMBER,
                AgentIntegrityConstraint.REVISION_HASH,
            }:
                raise AgentPlanConflict("agent_plan_duplicate_revision") from error
            raise

        stored = await self.get_revision(household_id, revision.id)
        if stored is None:
            raise RuntimeError("created cloned revision is missing")
        return stored

    async def _find_clone(
        self,
        household_id: UUID,
        clone_idempotency_key: str,
    ) -> AgentPlanRevisionRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                    .where(
                        agent_search_plan_revisions_table.c.clone_idempotency_key
                        == clone_idempotency_key
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _revision_record(row) if row is not None else None


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def approve_and_execute(
        self,
        *,
        approval: NewAgentPlanApproval,
        run: NewAgentPlanRun,
    ) -> AgentPlanRunRecord:
        await _acquire_sqlite_write_transaction(self._session)
        existing = await self._get_by_execute_idempotency(
            approval.household_id,
            run.execute_idempotency_key,
        )
        if existing is not None:
            return existing
        stored_approval = await self.create_approval(approval)
        return await self.execute(
            household_id=approval.household_id,
            approval_id=stored_approval.id,
            run=run,
        )

    async def create_approval(
        self,
        approval: NewAgentPlanApproval,
    ) -> AgentPlanApprovalRecord:
        _require_aware(approval.approved_at, "approved_at")
        _require_aware(approval.expires_at, "expires_at")
        _validate_approval_snapshot(approval.snapshot)
        if approval.expires_at <= approval.approved_at:
            raise ValueError("approval expires_at must be after approved_at")

        revision = await AgentPlanRepository(self._session).get_revision(
            approval.household_id,
            approval.revision_id,
        )
        if revision is None:
            raise AgentPlanNotFound("agent_plan_not_found")
        if (
            revision.state != "awaiting_approval"
            or revision.superseded_at is not None
            or revision.consumed_at is not None
        ):
            raise AgentPlanConflict("agent_plan_stale")
        if revision.expires_at <= approval.approved_at:
            raise AgentPlanConflict("agent_plan_expired")
        if revision.content_hash != approval.snapshot.revision_content_hash:
            raise AgentPlanConflict("agent_approval_snapshot_mismatch")

        await self._session.execute(
            insert(agent_plan_execution_approvals_table).values(
                id=str(approval.id),
                household_id=str(approval.household_id),
                plan_id=str(revision.plan_id),
                revision_id=str(approval.revision_id),
                approved_by_user_id=str(approval.approved_by_user_id),
                revision_content_hash=approval.snapshot.revision_content_hash,
                approved_by_session_id=str(approval.snapshot.approved_by_session_id),
                approved_budget_json=_canonical_json(dict(approval.snapshot.approved_budget)),
                approved_strategies_json=_canonical_json(
                    list(approval.snapshot.approved_strategies)
                ),
                risk_warning_versions_json=_canonical_json(
                    dict(approval.snapshot.risk_warning_versions)
                ),
                approved_at=_utc_datetime(approval.approved_at),
                expires_at=_utc_datetime(approval.expires_at),
                consumed_at=None,
                run_id=None,
            )
        )

        stored = await self.get_approval(approval.household_id, approval.id)
        if stored is None:
            raise RuntimeError("created agent approval is missing")
        return stored

    async def get_approval(
        self,
        household_id: UUID,
        approval_id: UUID,
    ) -> AgentPlanApprovalRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_execution_approvals_table)
                    .where(agent_plan_execution_approvals_table.c.id == str(approval_id))
                    .where(agent_plan_execution_approvals_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _approval_record(row) if row is not None else None

    async def execute(
        self,
        *,
        household_id: UUID,
        approval_id: UUID,
        run: NewAgentPlanRun,
    ) -> AgentPlanRunRecord:
        _validate_new_run(run)
        await _acquire_sqlite_write_transaction(self._session)
        existing = await self._get_by_execute_idempotency(
            household_id,
            run.execute_idempotency_key,
        )
        if existing is not None:
            return existing

        approval = await self.get_approval(household_id, approval_id)
        if approval is None:
            raise AgentPlanNotFound("agent_plan_not_found")

        active = await self._get_active_run(household_id, approval.plan_id)
        if active is not None:
            existing = await self._get_by_execute_idempotency(
                household_id,
                run.execute_idempotency_key,
            )
            if existing is not None:
                return existing
            raise AgentPlanConflict("agent_plan_active_run")
        if approval.run_id is not None or approval.consumed_at is not None:
            existing = await self._get_by_execute_idempotency(
                household_id,
                run.execute_idempotency_key,
            )
            if existing is not None:
                return existing
            raise AgentPlanConflict("agent_approval_consumed")
        if approval.expires_at <= run.created_at:
            raise AgentPlanConflict("agent_approval_expired")

        revision = await AgentPlanRepository(self._session).get_revision(
            household_id,
            approval.revision_id,
        )
        if revision is None:
            raise AgentPlanNotFound("agent_plan_not_found")
        if (
            revision.state != "awaiting_approval"
            or revision.superseded_at is not None
            or revision.consumed_at is not None
        ):
            existing = await self._get_by_execute_idempotency(
                household_id,
                run.execute_idempotency_key,
            )
            if existing is not None:
                return existing
            raise AgentPlanConflict("agent_plan_stale")
        if revision.expires_at <= run.created_at:
            raise AgentPlanConflict("agent_plan_expired")
        if approval.snapshot.revision_content_hash != revision.content_hash:
            raise AgentPlanConflict("agent_approval_snapshot_mismatch")

        logical_operation_budget = revision.estimated_logical_operations
        http_attempt_budget = revision.estimated_http_attempts
        if logical_operation_budget is None or http_attempt_budget is None:
            raise AgentPlanConflict("agent_approval_snapshot_mismatch")
        if logical_operation_budget <= 0 or http_attempt_budget <= 0:
            raise AgentPlanConflict("agent_approval_snapshot_mismatch")

        created_at = _utc_datetime(run.created_at)
        deadline_at = _utc_datetime(run.deadline_at)

        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_plan_runs_table).values(
                        id=str(run.id),
                        household_id=str(household_id),
                        plan_id=str(approval.plan_id),
                        revision_id=str(approval.revision_id),
                        approval_id=str(approval.id),
                        execute_idempotency_key=run.execute_idempotency_key,
                        status="queued",
                        created_at=created_at,
                        deadline_at=deadline_at,
                        started_at=None,
                        cancel_requested_at=None,
                        finished_at=None,
                        error_code=None,
                        error_message=None,
                        logical_operation_budget=logical_operation_budget,
                        logical_operations_consumed=0,
                        http_attempt_budget=http_attempt_budget,
                        http_attempts_consumed=0,
                    )
                )
                approval_result = await self._session.execute(
                    update(agent_plan_execution_approvals_table)
                    .where(agent_plan_execution_approvals_table.c.id == str(approval_id))
                    .where(agent_plan_execution_approvals_table.c.household_id == str(household_id))
                    .where(agent_plan_execution_approvals_table.c.run_id.is_(None))
                    .where(agent_plan_execution_approvals_table.c.consumed_at.is_(None))
                    .values(run_id=str(run.id), consumed_at=created_at)
                )
                if cast(CursorResult[Any], approval_result).rowcount != 1:
                    raise AgentPlanConflict("agent_approval_consumed")

                revision_result = await self._session.execute(
                    update(agent_search_plan_revisions_table)
                    .where(agent_search_plan_revisions_table.c.id == str(approval.revision_id))
                    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
                    .where(agent_search_plan_revisions_table.c.state == "awaiting_approval")
                    .where(agent_search_plan_revisions_table.c.superseded_at.is_(None))
                    .where(agent_search_plan_revisions_table.c.consumed_at.is_(None))
                    .where(
                        agent_search_plan_revisions_table.c.content_hash
                        == approval.snapshot.revision_content_hash
                    )
                    .values(state="consumed", consumed_at=created_at)
                )
                if cast(CursorResult[Any], revision_result).rowcount != 1:
                    raise AgentPlanConflict("agent_plan_stale")
        except IntegrityError as error:
            constraint = classify_agent_integrity_constraint(error)
            if constraint is AgentIntegrityConstraint.EXECUTE_IDEMPOTENCY:
                existing = await self._get_by_execute_idempotency(
                    household_id,
                    run.execute_idempotency_key,
                )
                if existing is not None:
                    return existing
                raise AgentPlanConflict("agent_run_idempotency_conflict") from error
            if constraint is AgentIntegrityConstraint.ACTIVE_RUN:
                raise AgentPlanConflict("agent_plan_active_run") from error
            if constraint in {
                AgentIntegrityConstraint.APPROVAL_RUN,
                AgentIntegrityConstraint.RUN_APPROVAL,
            }:
                raise AgentPlanConflict("agent_approval_consumed") from error
            raise

        stored = await self.get_run(household_id, run.id)
        if stored is None:
            raise RuntimeError("created agent run is missing")
        return stored

    async def get_run(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> AgentPlanRunRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_runs_table)
                    .where(agent_plan_runs_table.c.id == str(run_id))
                    .where(agent_plan_runs_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _run_record(row) if row is not None else None

    async def get_by_execute_idempotency(
        self,
        household_id: UUID,
        execute_idempotency_key: str,
    ) -> AgentPlanRunRecord | None:
        return await self._get_by_execute_idempotency(
            household_id,
            execute_idempotency_key,
        )

    async def list_runs(
        self,
        household_id: UUID,
        plan_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[AgentPlanRunRecord, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        rows = (
            await self._session.execute(
                select(agent_plan_runs_table)
                .where(agent_plan_runs_table.c.household_id == str(household_id))
                .where(agent_plan_runs_table.c.plan_id == str(plan_id))
                .order_by(
                    agent_plan_runs_table.c.created_at.desc(),
                    agent_plan_runs_table.c.id.desc(),
                )
                .limit(limit)
            )
        ).mappings()
        return tuple(reversed(tuple(_run_record(row) for row in rows)))

    async def get_latest_run(
        self,
        household_id: UUID,
        plan_id: UUID | None = None,
    ) -> AgentPlanRunRecord | None:
        statement = select(agent_plan_runs_table).where(
            agent_plan_runs_table.c.household_id == str(household_id)
        )
        if plan_id is not None:
            statement = statement.where(agent_plan_runs_table.c.plan_id == str(plan_id))
        row = (
            (
                await self._session.execute(
                    statement.order_by(
                        agent_plan_runs_table.c.created_at.desc(),
                        agent_plan_runs_table.c.id.desc(),
                    ).limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _run_record(row) if row is not None else None

    async def list_execution_candidates(
        self,
        *,
        limit: int = 100,
        after: AgentPlanRunRecord | None = None,
    ) -> tuple[AgentPlanRunRecord, ...]:
        """System-worker view of active runs; every returned row retains household scope."""

        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        priority = case(
            (agent_plan_runs_table.c.status == "cancel_requested", 0),
            (agent_plan_runs_table.c.status == "queued", 1),
            else_=2,
        )
        query = select(agent_plan_runs_table).where(
            agent_plan_runs_table.c.status.in_(_ACTIVE_RUN_STATUSES)
        )
        if after is not None:
            after_priority = _execution_candidate_priority(after.status)
            after_created_at = _utc_datetime(after.created_at)
            query = query.where(
                or_(
                    priority > after_priority,
                    and_(
                        priority == after_priority,
                        or_(
                            agent_plan_runs_table.c.created_at > after_created_at,
                            and_(
                                agent_plan_runs_table.c.created_at == after_created_at,
                                agent_plan_runs_table.c.id > str(after.id),
                            ),
                        ),
                    ),
                )
            )
        rows = (
            await self._session.execute(
                query.order_by(
                    priority,
                    agent_plan_runs_table.c.created_at.asc(),
                    agent_plan_runs_table.c.id.asc(),
                ).limit(limit)
            )
        ).mappings()
        return tuple(_run_record(row) for row in rows)

    async def set_status(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        status: AgentRunStatus,
        changed_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> AgentPlanRunRecord:
        _require_aware(changed_at, "changed_at")
        if status not in _RUN_STATUSES or status not in _TRANSITION_SOURCES:
            raise ValueError("unsupported agent run status")
        if status not in {"partial", "failed"} and (
            error_code is not None or error_message is not None
        ):
            raise ValueError("error fields are only allowed for partial or failed runs")
        if status == "failed" and error_code is None:
            raise ValueError("failed transition requires error_code")
        normalized_changed_at = _utc_datetime(changed_at)
        values: dict[str, object] = {
            "status": status,
            "error_code": error_code,
            "error_message": error_message,
        }
        if status == "running":
            values["started_at"] = normalized_changed_at
        elif status == "cancel_requested":
            values["cancel_requested_at"] = normalized_changed_at
        elif status in _TERMINAL_RUN_STATUSES:
            values["finished_at"] = normalized_changed_at

        statement = (
            update(agent_plan_runs_table)
            .where(agent_plan_runs_table.c.id == str(run_id))
            .where(agent_plan_runs_table.c.household_id == str(household_id))
            .where(agent_plan_runs_table.c.status.in_(_TRANSITION_SOURCES[status]))
            .where(agent_plan_runs_table.c.created_at <= normalized_changed_at)
        )
        if status in {"completed", "partial", "failed"}:
            statement = statement.where(agent_plan_runs_table.c.started_at.is_not(None)).where(
                agent_plan_runs_table.c.started_at <= normalized_changed_at
            )
        elif status == "cancelled":
            statement = statement.where(
                agent_plan_runs_table.c.cancel_requested_at.is_not(None)
            ).where(agent_plan_runs_table.c.cancel_requested_at <= normalized_changed_at)
        elif status == "cancel_requested":
            statement = statement.where(
                (agent_plan_runs_table.c.started_at.is_(None))
                | (agent_plan_runs_table.c.started_at <= normalized_changed_at)
            )

        result = await self._session.execute(statement.values(**values))
        if cast(CursorResult[Any], result).rowcount != 1:
            stored = await self.get_run(household_id, run_id)
            if stored is None:
                raise AgentPlanNotFound("agent_plan_not_found")
            raise AgentPlanConflict("agent_run_transition_conflict")
        stored = await self.get_run(household_id, run_id)
        if stored is None:
            raise RuntimeError("updated agent run is missing")
        return stored

    async def _get_by_execute_idempotency(
        self,
        household_id: UUID,
        execute_idempotency_key: str,
    ) -> AgentPlanRunRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_runs_table)
                    .where(agent_plan_runs_table.c.household_id == str(household_id))
                    .where(
                        agent_plan_runs_table.c.execute_idempotency_key == execute_idempotency_key
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _run_record(row) if row is not None else None

    async def _get_active_run(
        self,
        household_id: UUID,
        plan_id: UUID,
    ) -> AgentPlanRunRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_runs_table)
                    .where(agent_plan_runs_table.c.household_id == str(household_id))
                    .where(agent_plan_runs_table.c.plan_id == str(plan_id))
                    .where(agent_plan_runs_table.c.status.in_(_ACTIVE_RUN_STATUSES))
                    .order_by(
                        agent_plan_runs_table.c.created_at.desc(),
                        agent_plan_runs_table.c.id.desc(),
                    )
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _run_record(row) if row is not None else None


AgentPlanRunRepository = AgentRunRepository


class AgentOperationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_run_ledger_progress(
        self,
        household_id: UUID,
        run_ids: Sequence[UUID],
    ) -> Mapping[UUID, AgentRunLedgerProgress]:
        ordered_ids = tuple(dict.fromkeys(run_ids))
        progress = {run_id: AgentRunLedgerProgress(run_id=run_id) for run_id in ordered_ids}
        if not ordered_ids:
            return progress
        stored_ids = tuple(str(run_id) for run_id in ordered_ids)
        stage_rows = (
            await self._session.execute(
                select(
                    agent_plan_stages_table.c.run_id,
                    func.count().label("total"),
                    *(
                        func.sum(
                            case(
                                (agent_plan_stages_table.c.status == status.value, 1),
                                else_=0,
                            )
                        ).label(status.value)
                        for status in AgentStageStatus
                    ),
                )
                .where(agent_plan_stages_table.c.household_id == str(household_id))
                .where(agent_plan_stages_table.c.run_id.in_(stored_ids))
                .group_by(agent_plan_stages_table.c.run_id)
            )
        ).mappings()
        for row in stage_rows:
            run_id = UUID(str(row["run_id"]))
            progress[run_id] = replace(
                progress[run_id],
                stage_total=int(row["total"] or 0),
                stage_pending=int(row[AgentStageStatus.PENDING.value] or 0),
                stage_running=int(row[AgentStageStatus.RUNNING.value] or 0),
                stage_completed=int(row[AgentStageStatus.COMPLETED.value] or 0),
                stage_partial=int(row[AgentStageStatus.PARTIAL.value] or 0),
                stage_failed=int(row[AgentStageStatus.FAILED.value] or 0),
                stage_skipped=int(row[AgentStageStatus.SKIPPED.value] or 0),
                stage_cancelled=int(row[AgentStageStatus.CANCELLED.value] or 0),
            )
        operation_rows = (
            await self._session.execute(
                select(
                    agent_run_operations_table.c.run_id,
                    func.count().label("total"),
                    func.sum(
                        case((agent_run_operations_table.c.attempt_count > 0, 1), else_=0)
                    ).label("attempted"),
                    *(
                        func.sum(
                            case(
                                (agent_run_operations_table.c.status == status.value, 1),
                                else_=0,
                            )
                        ).label(status.value)
                        for status in AgentOperationStatus
                    ),
                )
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(agent_run_operations_table.c.run_id.in_(stored_ids))
                .group_by(agent_run_operations_table.c.run_id)
            )
        ).mappings()
        for row in operation_rows:
            run_id = UUID(str(row["run_id"]))
            progress[run_id] = replace(
                progress[run_id],
                operation_total=int(row["total"] or 0),
                operation_attempted=int(row["attempted"] or 0),
                operation_pending=int(row[AgentOperationStatus.PENDING.value] or 0),
                operation_leased=int(row[AgentOperationStatus.LEASED.value] or 0),
                operation_retry_wait=int(row[AgentOperationStatus.RETRY_WAIT.value] or 0),
                operation_succeeded=int(row[AgentOperationStatus.SUCCEEDED.value] or 0),
                operation_failed=int(row[AgentOperationStatus.FAILED.value] or 0),
                operation_skipped=int(row[AgentOperationStatus.SKIPPED.value] or 0),
            )
        return progress

    async def create_stage(self, stage: NewAgentPlanStage) -> AgentPlanStageRecord:
        _validate_new_stage(stage)
        await self._acquire_write_transaction()
        existing = await self._get_stage_by_kind(stage.household_id, stage.run_id, stage.kind)
        if existing is not None:
            return existing
        await self._require_run(stage.household_id, stage.run_id)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_plan_stages_table).values(
                        id=str(stage.id),
                        household_id=str(stage.household_id),
                        run_id=str(stage.run_id),
                        stage_kind=stage.kind.value,
                        status=stage.status.value,
                        created_at=_utc_datetime(stage.created_at),
                        updated_at=_utc_datetime(stage.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_stage_by_kind(stage.household_id, stage.run_id, stage.kind)
            if existing is not None:
                return existing
            raise
        stored = await self.get_stage(stage.household_id, stage.id)
        if stored is None:
            raise RuntimeError("created agent stage is missing")
        return stored

    async def get_stage(
        self,
        household_id: UUID,
        stage_id: UUID,
    ) -> AgentPlanStageRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_stages_table)
                    .where(agent_plan_stages_table.c.id == str(stage_id))
                    .where(agent_plan_stages_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _stage_record(row) if row is not None else None

    async def list_stages(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> tuple[AgentPlanStageRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_plan_stages_table)
                .where(agent_plan_stages_table.c.household_id == str(household_id))
                .where(agent_plan_stages_table.c.run_id == str(run_id))
                .order_by(
                    agent_plan_stages_table.c.created_at.asc(),
                    agent_plan_stages_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_stage_record(row) for row in rows)

    async def get_stage_progress(
        self,
        household_id: UUID,
        stage_id: UUID,
    ) -> AgentStageProgress | None:
        if await self.get_stage(household_id, stage_id) is None:
            return None
        row = (
            (
                await self._session.execute(
                    select(
                        func.count().label("total"),
                        *(
                            func.sum(
                                case(
                                    (agent_run_operations_table.c.status == status.value, 1),
                                    else_=0,
                                )
                            ).label(status.value)
                            for status in AgentOperationStatus
                        ),
                    )
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                    .where(agent_run_operations_table.c.stage_id == str(stage_id))
                )
            )
            .mappings()
            .one()
        )
        return AgentStageProgress(
            stage_id=stage_id,
            total=int(row["total"] or 0),
            pending=int(row[AgentOperationStatus.PENDING.value] or 0),
            leased=int(row[AgentOperationStatus.LEASED.value] or 0),
            retry_wait=int(row[AgentOperationStatus.RETRY_WAIT.value] or 0),
            succeeded=int(row[AgentOperationStatus.SUCCEEDED.value] or 0),
            failed=int(row[AgentOperationStatus.FAILED.value] or 0),
            skipped=int(row[AgentOperationStatus.SKIPPED.value] or 0),
        )

    async def set_stage_status(
        self,
        *,
        household_id: UUID,
        stage_id: UUID,
        status: AgentStageStatus | str,
        now: datetime,
    ) -> AgentPlanStageRecord:
        """Project operation progress onto a durable stage without exposing internals."""

        _require_aware(now, "now")
        normalized_status = AgentStageStatus(status)
        result = await self._session.execute(
            update(agent_plan_stages_table)
            .where(agent_plan_stages_table.c.id == str(stage_id))
            .where(agent_plan_stages_table.c.household_id == str(household_id))
            .where(agent_plan_stages_table.c.updated_at <= _utc_datetime(now))
            .values(status=normalized_status.value, updated_at=_utc_datetime(now))
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            stored = await self.get_stage(household_id, stage_id)
            if stored is None:
                raise AgentOperationConflict("agent_stage_not_found")
            if stored.status is normalized_status:
                return stored
            raise AgentOperationConflict("agent_stage_transition_conflict")
        stored = await self.get_stage(household_id, stage_id)
        if stored is None:
            raise RuntimeError("updated agent stage is missing")
        return stored

    async def materialize_operation(
        self,
        operation: NewAgentRunOperation,
    ) -> AgentRunOperationRecord:
        immutable_input_json, private_continuation_json = _validate_new_operation(operation)
        await self._acquire_write_transaction()
        existing_row = await self._get_operation_by_fingerprint(
            operation.household_id,
            operation.run_id,
            operation.operation_fingerprint,
        )
        if existing_row is not None:
            existing = _operation_record(existing_row)
            _require_materialization_match(
                existing,
                operation,
                existing_private_continuation_json=_optional_text(
                    existing_row["private_continuation_json"]
                ),
                requested_private_continuation_json=private_continuation_json,
            )
            return existing
        if not await self._run_allows_io(
            operation.household_id,
            operation.run_id,
            _utc_datetime(operation.created_at),
        ):
            raise AgentOperationConflict("agent_run_not_executable")
        await self._require_stage_ownership(
            operation.household_id,
            operation.run_id,
            operation.stage_id,
        )
        logical_root: AgentRunOperationRecord | None = None
        if operation.consumes_logical_unit:
            logical_root = await self._get_logical_root(
                operation.household_id,
                operation.run_id,
                operation.logical_operation_fingerprint,
            )
            if logical_root is not None:
                if logical_root.operation_fingerprint == operation.operation_fingerprint:
                    logical_row = await self._get_operation_by_fingerprint(
                        operation.household_id,
                        operation.run_id,
                        operation.operation_fingerprint,
                    )
                    if logical_row is None:
                        raise AgentOperationConflict("agent_operation_fingerprint_conflict")
                    existing = _operation_record(logical_row)
                    _require_materialization_match(
                        existing,
                        operation,
                        existing_private_continuation_json=_optional_text(
                            logical_row["private_continuation_json"]
                        ),
                        requested_private_continuation_json=private_continuation_json,
                    )
                    return existing
                raise AgentOperationConflict("agent_logical_operation_exists")
        elif operation.kind is AgentOperationKind.EXACT_POLL:
            if operation.logical_root_operation_id is None:
                raise AgentOperationConflict("agent_logical_operation_root_missing")
            logical_root = await self._get_logical_root_by_id(
                operation.household_id,
                operation.run_id,
                operation.logical_root_operation_id,
            )
            if logical_root is None:
                raise AgentOperationConflict("agent_logical_operation_root_not_found")
            if not _logical_root_matches_child(logical_root, operation):
                raise AgentOperationConflict("agent_logical_operation_root_mismatch")

        collision_existing: AgentRunOperationRecord | None = None
        collision_conflict_code: str | None = None
        try:
            async with self._session.begin_nested():
                if operation.consumes_logical_unit:
                    budget_result = await self._session.execute(
                        update(agent_plan_runs_table)
                        .where(agent_plan_runs_table.c.id == str(operation.run_id))
                        .where(agent_plan_runs_table.c.household_id == str(operation.household_id))
                        .where(
                            agent_plan_runs_table.c.logical_operations_consumed
                            < agent_plan_runs_table.c.logical_operation_budget
                        )
                        .values(
                            logical_operations_consumed=(
                                agent_plan_runs_table.c.logical_operations_consumed + 1
                            )
                        )
                    )
                    if cast(CursorResult[Any], budget_result).rowcount != 1:
                        await self._require_run(operation.household_id, operation.run_id)
                        raise AgentOperationConflict("agent_logical_budget_exhausted")
                await self._session.execute(
                    insert(agent_run_operations_table).values(
                        id=str(operation.id),
                        household_id=str(operation.household_id),
                        run_id=str(operation.run_id),
                        stage_id=str(operation.stage_id),
                        provider_id=operation.provider_id,
                        operation_kind=operation.kind.value,
                        operation_fingerprint=operation.operation_fingerprint,
                        logical_operation_fingerprint=(operation.logical_operation_fingerprint),
                        logical_root_operation_id=(
                            str(operation.logical_root_operation_id)
                            if operation.logical_root_operation_id is not None
                            else None
                        ),
                        handoff_predecessor_operation_id=None,
                        consumes_logical_unit=operation.consumes_logical_unit,
                        immutable_input_json=immutable_input_json,
                        private_continuation_json=private_continuation_json,
                        status=AgentOperationStatus.PENDING.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        attempt_count=0,
                        max_attempts=operation.max_attempts,
                        next_retry_at=None,
                        http_attempts_consumed=0,
                        circuit_permit_token_digest=None,
                        circuit_permit_generation=None,
                        circuit_permit_mode=None,
                        circuit_permit_attempt_number=None,
                        circuit_permit_expires_at=None,
                        circuit_permit_consumed_at=None,
                        result_type=None,
                        result_id=None,
                        error_code=None,
                        created_at=_utc_datetime(operation.created_at),
                        updated_at=_utc_datetime(operation.created_at),
                        completed_at=None,
                    )
                )
        except IntegrityError:
            existing_row = await self._get_operation_by_fingerprint(
                operation.household_id,
                operation.run_id,
                operation.operation_fingerprint,
            )
            if existing_row is not None:
                collision_existing = _operation_record(existing_row)
                collision_conflict_code = _materialization_conflict_code(
                    collision_existing,
                    operation,
                    existing_private_continuation_json=_optional_text(
                        existing_row["private_continuation_json"]
                    ),
                    requested_private_continuation_json=private_continuation_json,
                )
            else:
                logical_root = await self._get_logical_root(
                    operation.household_id,
                    operation.run_id,
                    operation.logical_operation_fingerprint,
                )
                collision_conflict_code = (
                    "agent_logical_operation_exists"
                    if operation.consumes_logical_unit and logical_root is not None
                    else "agent_operation_fingerprint_conflict"
                )

        if collision_existing is not None and collision_conflict_code is None:
            return collision_existing
        if collision_conflict_code is not None:
            raise AgentOperationConflict(collision_conflict_code)

        stored = await self.get_operation(operation.household_id, operation.id)
        if stored is None:
            raise RuntimeError("created agent operation is missing")
        return stored

    async def defer_pending_operation(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        next_retry_at: datetime,
        error_code: str,
        now: datetime,
    ) -> AgentRunOperationRecord:
        _validate_operation_completion("scheduler", error_code, now)
        _require_aware(next_retry_at, "next_retry_at")
        if next_retry_at <= now:
            raise ValueError("next_retry_at must be after now")
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.PENDING.value)
            .where(agent_run_operations_table.c.attempt_count == 0)
            .values(
                status=AgentOperationStatus.RETRY_WAIT.value,
                next_retry_at=_utc_datetime(next_retry_at),
                error_code=error_code,
                updated_at=_utc_datetime(now),
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            stored = await self._required_operation(household_id, operation_id)
            if stored.status is AgentOperationStatus.RETRY_WAIT:
                return stored
            raise AgentOperationConflict("agent_operation_defer_conflict")
        return await self._required_operation(household_id, operation_id)

    async def get_operation(
        self,
        household_id: UUID,
        operation_id: UUID,
    ) -> AgentRunOperationRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == str(operation_id))
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _operation_record(row) if row is not None else None

    async def list_operations(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> tuple[AgentRunOperationRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_run_operations_table)
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(agent_run_operations_table.c.run_id == str(run_id))
                .order_by(
                    agent_run_operations_table.c.created_at.asc(),
                    agent_run_operations_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_operation_record(row) for row in rows)

    async def list_operations_for_runs(
        self,
        household_id: UUID,
        run_ids: Sequence[UUID],
    ) -> Mapping[UUID, tuple[AgentRunOperationRecord, ...]]:
        ids = _bounded_uuid_ids(run_ids, "run_ids")
        grouped: dict[UUID, list[AgentRunOperationRecord]] = {run_id: [] for run_id in ids}
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                select(agent_run_operations_table)
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(
                    agent_run_operations_table.c.run_id.in_(tuple(str(run_id) for run_id in ids))
                )
                .order_by(
                    agent_run_operations_table.c.run_id.asc(),
                    agent_run_operations_table.c.created_at.asc(),
                    agent_run_operations_table.c.id.asc(),
                )
            )
        ).mappings()
        for row in rows:
            record = _operation_record(row)
            grouped[record.run_id].append(record)
        return {run_id: tuple(records) for run_id, records in grouped.items()}

    async def claim_next_operation(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> ServerPrivateOperationLease | None:
        _require_aware(now, "now")
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        await self._acquire_write_transaction()
        normalized_now = _utc_datetime(now)
        run_state = await self._locked_run_execution_state(household_id, run_id)
        if run_state is None:
            return None
        inactive_error = _inactive_run_error(run_state, normalized_now)
        if inactive_error is not None:
            await self._reconcile_inactive_run_operations(
                household_id,
                run_id,
                inactive_error,
                normalized_now,
            )
            return None
        if not _run_state_allows_io(run_state, normalized_now):
            return None
        await self._terminally_recover_expired_final_attempts(
            household_id,
            run_id,
            normalized_now,
        )
        eligible = _operation_claim_eligibility(normalized_now)
        statement = (
            select(agent_run_operations_table)
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(agent_run_operations_table.c.created_at <= normalized_now)
            .where(eligible)
            .where(
                agent_run_operations_table.c.attempt_count
                < agent_run_operations_table.c.max_attempts
            )
            .order_by(
                func.coalesce(
                    agent_run_operations_table.c.next_retry_at,
                    agent_run_operations_table.c.created_at,
                ).asc(),
                agent_run_operations_table.c.created_at.asc(),
                agent_run_operations_table.c.id.asc(),
            )
            .limit(1)
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update(skip_locked=True)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return None
        operation_id = str(row["id"])
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == operation_id)
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(agent_run_operations_table.c.created_at <= normalized_now)
            .where(_operation_claim_eligibility(normalized_now))
            .where(
                agent_run_operations_table.c.attempt_count
                < agent_run_operations_table.c.max_attempts
            )
            .values(
                status=AgentOperationStatus.LEASED.value,
                lease_owner=worker_id,
                lease_expires_at=normalized_now + timedelta(seconds=lease_seconds),
                attempt_count=agent_run_operations_table.c.attempt_count + 1,
                next_retry_at=None,
                error_code=None,
                circuit_permit_token_digest=None,
                circuit_permit_generation=None,
                circuit_permit_mode=None,
                circuit_permit_attempt_number=None,
                circuit_permit_expires_at=None,
                circuit_permit_consumed_at=None,
                updated_at=normalized_now,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            return None
        private_row = (
            (
                await self._session.execute(
                    select(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == operation_id)
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one()
        )
        return _private_operation_lease(private_row)

    async def schedule_retry(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        next_retry_at: datetime,
        error_code: str,
        now: datetime,
    ) -> AgentRunOperationRecord:
        _validate_operation_completion(worker_id, error_code, now)
        _require_aware(next_retry_at, "next_retry_at")
        if next_retry_at <= now:
            raise ValueError("next_retry_at must be after now")
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at >= _utc_datetime(now))
            .where(
                agent_run_operations_table.c.attempt_count
                < agent_run_operations_table.c.max_attempts
            )
            .values(
                status=AgentOperationStatus.RETRY_WAIT.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=_utc_datetime(next_retry_at),
                error_code=error_code,
                updated_at=_utc_datetime(now),
            )
        )
        await self._require_operation_transition(result, household_id, operation_id)
        return await self._required_operation(household_id, operation_id)

    async def mark_operation_succeeded(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        result_type: AgentOperationResultType | str,
        result_id: UUID,
        now: datetime,
    ) -> AgentRunOperationRecord:
        _validate_operation_completion(worker_id, "result", now)
        normalized_result_type = AgentOperationResultType(result_type)
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        claimed = await self._locked_claimed_operation(
            household_id,
            operation_id,
            worker_id,
            normalized_now,
        )
        if claimed is None:
            await self._raise_operation_transition_conflict(household_id, operation_id)
        try:
            async with self._session.begin_nested():
                await self._validate_operation_result_reference(
                    cast(RowMapping, claimed),
                    normalized_result_type,
                    result_id,
                    normalized_now,
                )
                result = await self._session.execute(
                    update(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == str(operation_id))
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                    .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                    .where(agent_run_operations_table.c.lease_owner == worker_id)
                    .where(agent_run_operations_table.c.lease_expires_at >= normalized_now)
                    .values(
                        status=AgentOperationStatus.SUCCEEDED.value,
                        lease_owner=None,
                        lease_expires_at=None,
                        next_retry_at=None,
                        result_type=normalized_result_type.value,
                        result_id=str(result_id),
                        error_code=None,
                        updated_at=normalized_now,
                        completed_at=normalized_now,
                    )
                )
                await self._require_operation_transition(result, household_id, operation_id)
        except IntegrityError:
            if normalized_result_type is AgentOperationResultType.OPERATION:
                raise AgentOperationConflict("agent_operation_handoff_conflict") from None
            raise
        return await self._required_operation(household_id, operation_id)

    async def mark_operation_failed(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        error_code: str,
        now: datetime,
    ) -> AgentRunOperationRecord:
        _validate_operation_completion(worker_id, error_code, now)
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at >= _utc_datetime(now))
            .values(
                status=AgentOperationStatus.FAILED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=None,
                result_id=None,
                error_code=error_code,
                updated_at=_utc_datetime(now),
                completed_at=_utc_datetime(now),
            )
        )
        await self._require_operation_transition(result, household_id, operation_id)
        return await self._required_operation(household_id, operation_id)

    async def mark_operation_skipped(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        error_code: str,
        now: datetime,
    ) -> AgentRunOperationRecord:
        _require_aware(now, "now")
        if not error_code.strip():
            raise ValueError("error_code must not be blank")
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(
                agent_run_operations_table.c.status.in_(
                    (AgentOperationStatus.PENDING.value, AgentOperationStatus.RETRY_WAIT.value)
                )
            )
            .values(
                status=AgentOperationStatus.SKIPPED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=None,
                result_id=None,
                error_code=error_code,
                updated_at=_utc_datetime(now),
                completed_at=_utc_datetime(now),
            )
        )
        await self._require_operation_transition(result, household_id, operation_id)
        return await self._required_operation(household_id, operation_id)

    async def mark_claimed_operation_skipped(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        error_code: str,
        now: datetime,
    ) -> AgentRunOperationRecord:
        """Release a live lease for an inactive run or a typed empty discovery result."""

        _validate_operation_completion(worker_id, error_code, now)
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        row = await self._locked_operation_with_run(household_id, operation_id)
        if row is None:
            raise AgentOperationConflict("agent_operation_not_found")
        inactive_error = _inactive_run_error(row, normalized_now)
        empty_discovery = (
            error_code == "agent_no_discovery_results"
            and row["operation_kind"] == AgentOperationKind.SUGGEST_DISCOVERY.value
        )
        if inactive_error is None and not empty_discovery:
            raise AgentOperationConflict("agent_operation_skip_reason_invalid")
        effective_error = inactive_error or error_code
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at >= normalized_now)
            .values(
                status=AgentOperationStatus.SKIPPED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=None,
                result_id=None,
                error_code=effective_error,
                updated_at=normalized_now,
                completed_at=normalized_now,
            )
        )
        await self._require_operation_transition(result, household_id, operation_id)
        return await self._required_operation(household_id, operation_id)

    async def reserve_http_attempt(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        operation_id: UUID,
        worker_id: str,
        provider_id: str,
        attempt_kind: AttemptKind,
        provider_rpm: int,
        now: datetime,
        circuit_permit: ServerPrivateCircuitPermit,
    ) -> AttemptReservationResult:
        _require_aware(now, "now")
        if type(provider_rpm) is not int or provider_rpm <= 0:
            raise ValueError("provider_rpm must be a positive integer")
        if not provider_id.strip() or not worker_id.strip():
            raise ValueError("provider_id and worker_id must not be blank")
        normalized_kind = AttemptKind(attempt_kind)
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        operation = await self._require_reservable_operation(
            household_id,
            run_id,
            operation_id,
            provider_id,
            worker_id,
            normalized_now,
        )
        expected_kind = _expected_attempt_kind(operation)
        if normalized_kind is not expected_kind:
            raise AgentOperationConflict("agent_attempt_kind_invalid")
        permit_digest = _permit_digest(circuit_permit.token)
        _require_permit_call_binding(
            circuit_permit,
            permit_digest=permit_digest,
            operation=operation,
            provider_id=provider_id,
        )

        existing = await self._get_http_reservation(
            operation_id,
            int(operation["attempt_count"]),
        )
        if existing is not None:
            if (
                existing["attempt_kind"] != expected_kind.value
                or existing["circuit_permit_generation"] != circuit_permit.generation
                or existing["circuit_permit_token_digest"] != permit_digest
            ):
                raise AgentOperationConflict("agent_http_reservation_conflict")
            return AttemptReservationResult(
                status=AttemptReservationStatus.RESERVED,
                reservation_id=UUID(str(existing["id"])),
                reused=True,
            )

        await self._validate_unconsumed_circuit_permit(
            operation,
            circuit_permit,
            permit_digest,
            normalized_now,
        )
        await self._ensure_provider_lock(provider_id, normalized_now)
        recent_rows = (
            (
                await self._session.execute(
                    select(agent_provider_http_attempts_table.c.reserved_at)
                    .where(agent_provider_http_attempts_table.c.provider_id == provider_id)
                    .where(
                        agent_provider_http_attempts_table.c.reserved_at
                        > normalized_now - timedelta(minutes=1)
                    )
                    .order_by(agent_provider_http_attempts_table.c.reserved_at.asc())
                )
            )
            .scalars()
            .all()
        )
        if len(recent_rows) >= provider_rpm:
            oldest = _aware_datetime(recent_rows[0])
            return AttemptReservationResult(
                status=AttemptReservationStatus.RATE_LIMITED,
                retry_at=oldest + timedelta(minutes=1),
            )

        reservation_id = uuid4()
        try:
            async with self._session.begin_nested():
                budget_result = await self._session.execute(
                    update(agent_plan_runs_table)
                    .where(agent_plan_runs_table.c.id == str(run_id))
                    .where(agent_plan_runs_table.c.household_id == str(household_id))
                    .where(agent_plan_runs_table.c.status.in_(("queued", "running")))
                    .where(agent_plan_runs_table.c.deadline_at > normalized_now)
                    .where(
                        agent_plan_runs_table.c.http_attempts_consumed
                        < agent_plan_runs_table.c.http_attempt_budget
                    )
                    .values(
                        http_attempts_consumed=agent_plan_runs_table.c.http_attempts_consumed + 1
                    )
                )
                if cast(CursorResult[Any], budget_result).rowcount != 1:
                    return AttemptReservationResult(
                        status=AttemptReservationStatus.BUDGET_EXHAUSTED
                    )
                await self._session.execute(
                    insert(agent_provider_http_attempts_table).values(
                        id=str(reservation_id),
                        household_id=str(household_id),
                        provider_id=provider_id,
                        run_id=str(run_id),
                        operation_id=str(operation_id),
                        attempt_kind=expected_kind.value,
                        operation_attempt_number=int(operation["attempt_count"]),
                        circuit_permit_generation=circuit_permit.generation,
                        circuit_permit_token_digest=permit_digest,
                        reserved_at=normalized_now,
                        circuit_outcome=None,
                        circuit_outcome_recorded_at=None,
                    )
                )
                operation_result = await self._session.execute(
                    update(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == str(operation_id))
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                    .where(agent_run_operations_table.c.run_id == str(run_id))
                    .where(agent_run_operations_table.c.provider_id == provider_id)
                    .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                    .where(agent_run_operations_table.c.lease_owner == worker_id)
                    .where(agent_run_operations_table.c.lease_expires_at > normalized_now)
                    .where(
                        agent_run_operations_table.c.attempt_count
                        == int(operation["attempt_count"])
                    )
                    .where(
                        agent_run_operations_table.c.circuit_permit_token_digest == permit_digest
                    )
                    .where(
                        agent_run_operations_table.c.circuit_permit_generation
                        == circuit_permit.generation
                    )
                    .where(agent_run_operations_table.c.circuit_permit_consumed_at.is_(None))
                    .values(
                        http_attempts_consumed=(
                            agent_run_operations_table.c.http_attempts_consumed + 1
                        ),
                        circuit_permit_consumed_at=normalized_now,
                        updated_at=normalized_now,
                    )
                )
                if cast(CursorResult[Any], operation_result).rowcount != 1:
                    raise AgentOperationConflict("agent_circuit_permit_stale")
        except IntegrityError:
            existing = await self._get_http_reservation(
                operation_id,
                int(operation["attempt_count"]),
            )
            if existing is None:
                raise
            if (
                existing["attempt_kind"] != expected_kind.value
                or existing["circuit_permit_generation"] != circuit_permit.generation
                or existing["circuit_permit_token_digest"] != permit_digest
            ):
                raise AgentOperationConflict("agent_http_reservation_conflict") from None
            return AttemptReservationResult(
                status=AttemptReservationStatus.RESERVED,
                reservation_id=UUID(str(existing["id"])),
                reused=True,
            )
        return AttemptReservationResult(
            status=AttemptReservationStatus.RESERVED,
            reservation_id=reservation_id,
        )

    async def append_scope_snapshot(
        self,
        snapshot: NewAgentRunScopeSnapshot,
    ) -> AgentRunScopeSnapshotRecord:
        if not all(
            isinstance(value, UUID)
            for value in (snapshot.id, snapshot.household_id, snapshot.run_id)
        ):
            raise TypeError("scope snapshot ownership ids must be UUID values")
        _require_aware(snapshot.created_at, "created_at")
        _validate_fingerprint(snapshot.fingerprint, "fingerprint")
        snapshot_json = _canonical_scope_snapshot_json(snapshot.snapshot)
        await self._acquire_write_transaction()
        await self._require_run(snapshot.household_id, snapshot.run_id)
        existing = await self._get_scope_snapshot_by_run(snapshot.household_id, snapshot.run_id)
        if existing is not None:
            if existing.fingerprint == snapshot.fingerprint:
                return existing
            raise AgentOperationConflict("agent_run_scope_conflict")
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_run_scope_snapshots_table).values(
                        id=str(snapshot.id),
                        household_id=str(snapshot.household_id),
                        run_id=str(snapshot.run_id),
                        fingerprint=snapshot.fingerprint,
                        snapshot_json=snapshot_json,
                        created_at=_utc_datetime(snapshot.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_scope_snapshot_by_run(snapshot.household_id, snapshot.run_id)
            if existing is not None:
                if existing.fingerprint == snapshot.fingerprint:
                    return existing
                raise AgentOperationConflict("agent_run_scope_conflict") from None
            raise
        stored = await self.get_scope_snapshot(snapshot.household_id, snapshot.id)
        if stored is None:
            raise RuntimeError("created run scope snapshot is missing")
        return stored

    async def get_scope_snapshot(
        self,
        household_id: UUID,
        snapshot_id: UUID,
    ) -> AgentRunScopeSnapshotRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_run_scope_snapshots_table)
                    .where(agent_run_scope_snapshots_table.c.id == str(snapshot_id))
                    .where(agent_run_scope_snapshots_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _scope_snapshot_record(row) if row is not None else None

    async def get_scope_snapshot_for_run(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> AgentRunScopeSnapshotRecord | None:
        return await self._get_scope_snapshot_by_run(household_id, run_id)

    async def get_scope_snapshots_for_runs(
        self,
        household_id: UUID,
        run_ids: Sequence[UUID],
    ) -> Mapping[UUID, AgentRunScopeSnapshotRecord]:
        ids = _bounded_uuid_ids(run_ids, "run_ids")
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                select(agent_run_scope_snapshots_table)
                .where(agent_run_scope_snapshots_table.c.household_id == str(household_id))
                .where(
                    agent_run_scope_snapshots_table.c.run_id.in_(
                        tuple(str(run_id) for run_id in ids)
                    )
                )
            )
        ).mappings()
        records = tuple(_scope_snapshot_record(row) for row in rows)
        return {record.run_id: record for record in records}

    async def get_circuit_state(self, provider_id: str) -> AgentCircuitStateRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_provider_circuit_state_table).where(
                        agent_provider_circuit_state_table.c.provider_id == provider_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _circuit_record(row) if row is not None else None

    async def acquire_circuit_permit(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        operation_id: UUID,
        provider_id: str,
        worker_id: str,
        now: datetime,
        probe_lease_seconds: int,
    ) -> CircuitPermitResult:
        _require_aware(now, "now")
        if not provider_id.strip() or not worker_id.strip():
            raise ValueError("provider_id and worker_id must not be blank")
        if type(probe_lease_seconds) is not int or probe_lease_seconds <= 0:
            raise ValueError("probe_lease_seconds must be positive")
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        operation = await self._require_reservable_operation(
            household_id,
            run_id,
            operation_id,
            provider_id,
            worker_id,
            normalized_now,
        )
        kind = AgentOperationKind(str(operation["operation_kind"]))
        if kind not in _NETWORK_OPERATION_KINDS:
            raise AgentOperationConflict("agent_operation_not_networked")
        if operation["circuit_permit_token_digest"] is not None:
            raise AgentOperationConflict("agent_circuit_permit_already_issued")

        await self._ensure_circuit_row(provider_id, normalized_now)
        state = await self._locked_circuit_row(provider_id)
        state_value = AgentCircuitState(str(state["state"]))
        if state_value is AgentCircuitState.OPEN:
            cooldown_until = _aware_datetime(cast(datetime, state["cooldown_until"]))
            if normalized_now < cooldown_until:
                return CircuitPermitResult(
                    CircuitPermitStatus.OPEN,
                    retry_at=cooldown_until,
                )
        elif state_value is AgentCircuitState.HALF_OPEN:
            probe_expires_at = _aware_datetime(cast(datetime, state["half_open_probe_expires_at"]))
            if normalized_now < probe_expires_at:
                return CircuitPermitResult(
                    CircuitPermitStatus.OPEN,
                    retry_at=probe_expires_at,
                )

        token = secrets.token_urlsafe(32)
        token_digest = _permit_digest(token)
        attempt_number = int(operation["attempt_count"])
        lease_expires_at = _aware_datetime(cast(datetime, operation["lease_expires_at"]))
        if state_value is AgentCircuitState.CLOSED:
            mode = CircuitPermitMode.CLOSED
            status = CircuitPermitStatus.ALLOWED
            generation = int(state["generation"])
            permit_expires_at = lease_expires_at
        else:
            mode = CircuitPermitMode.HALF_OPEN
            status = CircuitPermitStatus.HALF_OPEN_PROBE
            generation = int(state["generation"]) + 1
            permit_expires_at = min(
                lease_expires_at,
                normalized_now + timedelta(seconds=probe_lease_seconds),
            )
        async with self._session.begin_nested():
            if mode is CircuitPermitMode.HALF_OPEN:
                transition = await self._session.execute(
                    update(agent_provider_circuit_state_table)
                    .where(agent_provider_circuit_state_table.c.provider_id == provider_id)
                    .where(agent_provider_circuit_state_table.c.version == int(state["version"]))
                    .values(
                        state=AgentCircuitState.HALF_OPEN.value,
                        half_open_probe_operation_id=str(operation_id),
                        half_open_probe_attempt_number=attempt_number,
                        half_open_probe_token_digest=token_digest,
                        half_open_probe_expires_at=permit_expires_at,
                        generation=generation,
                        version=agent_provider_circuit_state_table.c.version + 1,
                        updated_at=normalized_now,
                    )
                )
                if cast(CursorResult[Any], transition).rowcount != 1:
                    raise AgentOperationConflict("agent_circuit_permit_stale")

            operation_result = await self._session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(operation_id))
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(agent_run_operations_table.c.run_id == str(run_id))
                .where(agent_run_operations_table.c.provider_id == provider_id)
                .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                .where(agent_run_operations_table.c.lease_owner == worker_id)
                .where(agent_run_operations_table.c.lease_expires_at > normalized_now)
                .where(agent_run_operations_table.c.attempt_count == attempt_number)
                .where(agent_run_operations_table.c.circuit_permit_token_digest.is_(None))
                .values(
                    circuit_permit_token_digest=token_digest,
                    circuit_permit_generation=generation,
                    circuit_permit_mode=mode.value,
                    circuit_permit_attempt_number=attempt_number,
                    circuit_permit_expires_at=permit_expires_at,
                    circuit_permit_consumed_at=None,
                    updated_at=normalized_now,
                )
            )
            if cast(CursorResult[Any], operation_result).rowcount != 1:
                raise AgentOperationConflict("agent_circuit_permit_already_issued")
        return CircuitPermitResult(
            status,
            permit=ServerPrivateCircuitPermit(
                provider_id=provider_id,
                operation_id=operation_id,
                operation_attempt_number=attempt_number,
                generation=generation,
                mode=mode,
                token=token,
                expires_at=permit_expires_at,
            ),
        )

    async def record_circuit_failure(
        self,
        *,
        circuit_permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        transient: bool,
        failure_threshold: int,
        cooldown_seconds: int,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        _require_aware(now, "now")
        if not isinstance(reservation_id, UUID):
            raise TypeError("reservation_id must be UUID")
        if type(failure_threshold) is not int or failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if type(cooldown_seconds) is not int or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        outcome = (
            CircuitOutcome.TRANSIENT_FAILURE if transient else CircuitOutcome.NON_TRANSIENT_FAILURE
        )
        state, replayed, mutate_circuit = await self._prepare_circuit_outcome(
            circuit_permit,
            reservation_id,
            outcome,
            normalized_now,
        )
        if replayed:
            return _circuit_record(state)
        if not mutate_circuit:
            await self._persist_circuit_outcome(
                reservation_id,
                outcome,
                normalized_now,
            )
            return _circuit_record(state)
        async with self._session.begin_nested():
            if transient:
                failures = int(state["consecutive_transient_failures"]) + 1
                state_value = AgentCircuitState(str(state["state"]))
                should_open = (
                    state_value is not AgentCircuitState.CLOSED or failures >= failure_threshold
                )
                values: dict[str, object] = {
                    "consecutive_transient_failures": failures,
                    "version": agent_provider_circuit_state_table.c.version + 1,
                    "updated_at": normalized_now,
                }
                if should_open:
                    values.update(
                        state=AgentCircuitState.OPEN.value,
                        opened_at=normalized_now,
                        cooldown_until=normalized_now + timedelta(seconds=cooldown_seconds),
                        half_open_probe_operation_id=None,
                        half_open_probe_attempt_number=None,
                        half_open_probe_token_digest=None,
                        half_open_probe_expires_at=None,
                        generation=int(state["generation"]) + 1,
                    )
                result = await self._session.execute(
                    update(agent_provider_circuit_state_table)
                    .where(
                        agent_provider_circuit_state_table.c.provider_id
                        == circuit_permit.provider_id
                    )
                    .where(agent_provider_circuit_state_table.c.version == int(state["version"]))
                    .values(**values)
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise AgentOperationConflict("agent_circuit_permit_stale")
            else:
                generation = int(state["generation"])
                if circuit_permit.mode is CircuitPermitMode.HALF_OPEN:
                    generation += 1
                result = await self._session.execute(
                    update(agent_provider_circuit_state_table)
                    .where(
                        agent_provider_circuit_state_table.c.provider_id
                        == circuit_permit.provider_id
                    )
                    .where(agent_provider_circuit_state_table.c.version == int(state["version"]))
                    .values(
                        state=AgentCircuitState.CLOSED.value,
                        consecutive_transient_failures=0,
                        opened_at=None,
                        cooldown_until=None,
                        half_open_probe_operation_id=None,
                        half_open_probe_attempt_number=None,
                        half_open_probe_token_digest=None,
                        half_open_probe_expires_at=None,
                        generation=generation,
                        version=agent_provider_circuit_state_table.c.version + 1,
                        updated_at=normalized_now,
                    )
                )
                if cast(CursorResult[Any], result).rowcount != 1:
                    raise AgentOperationConflict("agent_circuit_permit_stale")
            await self._persist_circuit_outcome(
                reservation_id,
                outcome,
                normalized_now,
            )
        return await self._locked_circuit_state(circuit_permit.provider_id)

    async def abandon_circuit_permit(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        worker_id: str,
        circuit_permit: ServerPrivateCircuitPermit,
        now: datetime,
    ) -> None:
        """Release an unconsumed permit when local admission denies provider I/O."""

        _require_aware(now, "now")
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        normalized_now = _utc_datetime(now)
        permit_digest = _permit_digest(circuit_permit.token)
        await self._acquire_write_transaction()
        operation = await self._require_reservable_operation(
            household_id,
            run_id,
            circuit_permit.operation_id,
            circuit_permit.provider_id,
            worker_id,
            normalized_now,
            require_active_run=False,
        )
        _require_permit_call_binding(
            circuit_permit,
            permit_digest=permit_digest,
            operation=operation,
            provider_id=circuit_permit.provider_id,
        )
        await self._validate_unconsumed_circuit_permit(
            operation,
            circuit_permit,
            permit_digest,
            normalized_now,
        )
        state = await self._locked_circuit_row(circuit_permit.provider_id)

        async with self._session.begin_nested():
            operation_result = await self._session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(circuit_permit.operation_id))
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(agent_run_operations_table.c.run_id == str(run_id))
                .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                .where(agent_run_operations_table.c.lease_owner == worker_id)
                .where(agent_run_operations_table.c.lease_expires_at > normalized_now)
                .where(agent_run_operations_table.c.circuit_permit_token_digest == permit_digest)
                .where(
                    agent_run_operations_table.c.circuit_permit_generation
                    == circuit_permit.generation
                )
                .where(agent_run_operations_table.c.circuit_permit_consumed_at.is_(None))
                .values(
                    circuit_permit_token_digest=None,
                    circuit_permit_generation=None,
                    circuit_permit_mode=None,
                    circuit_permit_attempt_number=None,
                    circuit_permit_expires_at=None,
                    circuit_permit_consumed_at=None,
                    updated_at=normalized_now,
                )
            )
            if cast(CursorResult[Any], operation_result).rowcount != 1:
                raise AgentOperationConflict("agent_circuit_permit_stale")

            if circuit_permit.mode is CircuitPermitMode.HALF_OPEN:
                state_result = await self._session.execute(
                    update(agent_provider_circuit_state_table)
                    .where(
                        agent_provider_circuit_state_table.c.provider_id
                        == circuit_permit.provider_id
                    )
                    .where(agent_provider_circuit_state_table.c.version == int(state["version"]))
                    .where(
                        agent_provider_circuit_state_table.c.state
                        == AgentCircuitState.HALF_OPEN.value
                    )
                    .where(
                        agent_provider_circuit_state_table.c.half_open_probe_token_digest
                        == permit_digest
                    )
                    .values(
                        state=AgentCircuitState.OPEN.value,
                        cooldown_until=normalized_now,
                        half_open_probe_operation_id=None,
                        half_open_probe_attempt_number=None,
                        half_open_probe_token_digest=None,
                        half_open_probe_expires_at=None,
                        generation=int(state["generation"]) + 1,
                        version=agent_provider_circuit_state_table.c.version + 1,
                        updated_at=normalized_now,
                    )
                )
                if cast(CursorResult[Any], state_result).rowcount != 1:
                    raise AgentOperationConflict("agent_circuit_permit_stale")

    async def abandon_reserved_http_attempt(
        self,
        *,
        household_id: UUID,
        run_id: UUID,
        worker_id: str,
        circuit_permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        now: datetime,
    ) -> None:
        """Release a consumed permit when admission changes before transport dispatch."""

        _require_aware(now, "now")
        if not isinstance(reservation_id, UUID):
            raise TypeError("reservation_id must be UUID")
        if not worker_id.strip():
            raise ValueError("worker_id must not be blank")
        normalized_now = _utc_datetime(now)
        permit_digest = _permit_digest(circuit_permit.token)
        await self._acquire_write_transaction()
        operation = await self._require_reservable_operation(
            household_id,
            run_id,
            circuit_permit.operation_id,
            circuit_permit.provider_id,
            worker_id,
            normalized_now,
            require_active_run=False,
        )
        _require_permit_call_binding(
            circuit_permit,
            permit_digest=permit_digest,
            operation=operation,
            provider_id=circuit_permit.provider_id,
        )
        reservation = (
            (
                await self._session.execute(
                    select(agent_provider_http_attempts_table)
                    .where(agent_provider_http_attempts_table.c.id == str(reservation_id))
                    .where(
                        agent_provider_http_attempts_table.c.operation_id
                        == str(circuit_permit.operation_id)
                    )
                    .where(
                        agent_provider_http_attempts_table.c.operation_attempt_number
                        == circuit_permit.operation_attempt_number
                    )
                    .where(
                        agent_provider_http_attempts_table.c.circuit_permit_generation
                        == circuit_permit.generation
                    )
                    .where(
                        agent_provider_http_attempts_table.c.circuit_permit_token_digest
                        == permit_digest
                    )
                    .where(agent_provider_http_attempts_table.c.circuit_outcome.is_(None))
                )
            )
            .mappings()
            .one_or_none()
        )
        if reservation is None or operation["circuit_permit_consumed_at"] is None:
            raise AgentOperationConflict("agent_circuit_permit_stale")

        async with self._session.begin_nested():
            operation_result = await self._session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(circuit_permit.operation_id))
                .where(agent_run_operations_table.c.household_id == str(household_id))
                .where(agent_run_operations_table.c.run_id == str(run_id))
                .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                .where(agent_run_operations_table.c.lease_owner == worker_id)
                .where(agent_run_operations_table.c.lease_expires_at > normalized_now)
                .where(agent_run_operations_table.c.circuit_permit_token_digest == permit_digest)
                .where(
                    agent_run_operations_table.c.circuit_permit_generation
                    == circuit_permit.generation
                )
                .where(agent_run_operations_table.c.circuit_permit_consumed_at.is_not(None))
                .values(
                    circuit_permit_token_digest=None,
                    circuit_permit_generation=None,
                    circuit_permit_mode=None,
                    circuit_permit_attempt_number=None,
                    circuit_permit_expires_at=None,
                    circuit_permit_consumed_at=None,
                    updated_at=normalized_now,
                )
            )
            if cast(CursorResult[Any], operation_result).rowcount != 1:
                raise AgentOperationConflict("agent_circuit_permit_stale")

            if circuit_permit.mode is CircuitPermitMode.HALF_OPEN:
                await self._session.execute(
                    update(agent_provider_circuit_state_table)
                    .where(
                        agent_provider_circuit_state_table.c.provider_id
                        == circuit_permit.provider_id
                    )
                    .where(
                        agent_provider_circuit_state_table.c.state
                        == AgentCircuitState.HALF_OPEN.value
                    )
                    .where(
                        agent_provider_circuit_state_table.c.generation == circuit_permit.generation
                    )
                    .where(
                        agent_provider_circuit_state_table.c.half_open_probe_token_digest
                        == permit_digest
                    )
                    .values(
                        state=AgentCircuitState.OPEN.value,
                        cooldown_until=normalized_now,
                        half_open_probe_operation_id=None,
                        half_open_probe_attempt_number=None,
                        half_open_probe_token_digest=None,
                        half_open_probe_expires_at=None,
                        generation=agent_provider_circuit_state_table.c.generation + 1,
                        version=agent_provider_circuit_state_table.c.version + 1,
                        updated_at=normalized_now,
                    )
                )

    async def _acquire_write_transaction(self) -> None:
        try:
            await _acquire_sqlite_write_transaction(self._session)
        except AgentPlanConflict as error:
            raise AgentOperationConflict(error.code) from error

    async def _run_allows_io(
        self,
        household_id: UUID,
        run_id: UUID,
        now: datetime,
    ) -> bool:
        row = await self._locked_run_execution_state(household_id, run_id)
        return row is not None and _run_state_allows_io(row, now)

    async def _locked_run_execution_state(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> RowMapping | None:
        statement = (
            select(
                agent_plan_runs_table.c.status,
                agent_plan_runs_table.c.created_at,
                agent_plan_runs_table.c.deadline_at,
            )
            .where(agent_plan_runs_table.c.id == str(run_id))
            .where(agent_plan_runs_table.c.household_id == str(household_id))
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).mappings().one_or_none()

    async def _locked_operation_with_run(
        self,
        household_id: UUID,
        operation_id: UUID,
    ) -> RowMapping | None:
        statement = (
            select(
                agent_run_operations_table,
                agent_plan_runs_table.c.status.label("run_status"),
                agent_plan_runs_table.c.created_at.label("run_created_at"),
                agent_plan_runs_table.c.deadline_at.label("run_deadline_at"),
            )
            .join(
                agent_plan_runs_table,
                agent_plan_runs_table.c.id == agent_run_operations_table.c.run_id,
            )
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_plan_runs_table.c.household_id == str(household_id))
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).mappings().one_or_none()

    async def _reconcile_inactive_run_operations(
        self,
        household_id: UUID,
        run_id: UUID,
        error_code: str,
        now: datetime,
    ) -> None:
        await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(
                or_(
                    agent_run_operations_table.c.status.in_(
                        (
                            AgentOperationStatus.PENDING.value,
                            AgentOperationStatus.RETRY_WAIT.value,
                        )
                    ),
                    (
                        (agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
                        & (agent_run_operations_table.c.lease_expires_at <= now)
                    ),
                )
            )
            .values(
                status=AgentOperationStatus.SKIPPED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=None,
                result_id=None,
                error_code=error_code,
                updated_at=now,
                completed_at=now,
            )
        )

    async def _terminally_recover_expired_final_attempts(
        self,
        household_id: UUID,
        run_id: UUID,
        now: datetime,
    ) -> None:
        await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_expires_at <= now)
            .where(
                agent_run_operations_table.c.attempt_count
                >= agent_run_operations_table.c.max_attempts
            )
            .values(
                status=AgentOperationStatus.FAILED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=None,
                result_id=None,
                error_code="agent_lease_expired_attempts_exhausted",
                updated_at=now,
                completed_at=now,
            )
        )

    async def record_circuit_success(
        self,
        *,
        circuit_permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        _require_aware(now, "now")
        if not isinstance(reservation_id, UUID):
            raise TypeError("reservation_id must be UUID")
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        state, replayed, mutate_circuit = await self._prepare_circuit_outcome(
            circuit_permit,
            reservation_id,
            CircuitOutcome.SUCCESS,
            normalized_now,
        )
        if replayed:
            return _circuit_record(state)
        if not mutate_circuit:
            await self._persist_circuit_outcome(
                reservation_id,
                CircuitOutcome.SUCCESS,
                normalized_now,
            )
            return _circuit_record(state)
        generation = int(state["generation"])
        if CircuitPermitMode(circuit_permit.mode) is CircuitPermitMode.HALF_OPEN:
            generation += 1
        async with self._session.begin_nested():
            result = await self._session.execute(
                update(agent_provider_circuit_state_table)
                .where(
                    agent_provider_circuit_state_table.c.provider_id == circuit_permit.provider_id
                )
                .where(agent_provider_circuit_state_table.c.version == int(state["version"]))
                .values(
                    state=AgentCircuitState.CLOSED.value,
                    consecutive_transient_failures=0,
                    opened_at=None,
                    cooldown_until=None,
                    half_open_probe_operation_id=None,
                    half_open_probe_attempt_number=None,
                    half_open_probe_token_digest=None,
                    half_open_probe_expires_at=None,
                    generation=generation,
                    version=agent_provider_circuit_state_table.c.version + 1,
                    updated_at=normalized_now,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                raise AgentOperationConflict("agent_circuit_permit_stale")
            await self._persist_circuit_outcome(
                reservation_id,
                CircuitOutcome.SUCCESS,
                normalized_now,
            )
        return await self._locked_circuit_state(circuit_permit.provider_id)

    async def _require_run(self, household_id: UUID, run_id: UUID) -> None:
        exists = (
            await self._session.execute(
                select(agent_plan_runs_table.c.id)
                .where(agent_plan_runs_table.c.id == str(run_id))
                .where(agent_plan_runs_table.c.household_id == str(household_id))
            )
        ).scalar_one_or_none()
        if exists is None:
            raise AgentOperationConflict("agent_run_not_found")

    async def _require_stage_ownership(
        self,
        household_id: UUID,
        run_id: UUID,
        stage_id: UUID,
    ) -> None:
        exists = (
            await self._session.execute(
                select(agent_plan_stages_table.c.id)
                .join(
                    agent_plan_runs_table,
                    agent_plan_runs_table.c.id == agent_plan_stages_table.c.run_id,
                )
                .where(agent_plan_stages_table.c.id == str(stage_id))
                .where(agent_plan_stages_table.c.run_id == str(run_id))
                .where(agent_plan_stages_table.c.household_id == str(household_id))
                .where(agent_plan_runs_table.c.household_id == str(household_id))
            )
        ).scalar_one_or_none()
        if exists is None:
            raise AgentOperationConflict("agent_stage_not_found")

    async def _require_reservable_operation(
        self,
        household_id: UUID,
        run_id: UUID,
        operation_id: UUID,
        provider_id: str,
        worker_id: str,
        now: datetime,
        *,
        require_active_run: bool = True,
    ) -> RowMapping:
        statement = (
            select(agent_run_operations_table)
            .join(
                agent_plan_stages_table,
                agent_plan_stages_table.c.id == agent_run_operations_table.c.stage_id,
            )
            .join(
                agent_plan_runs_table,
                agent_plan_runs_table.c.id == agent_run_operations_table.c.run_id,
            )
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at > now)
            .where(agent_plan_stages_table.c.household_id == str(household_id))
            .where(agent_plan_runs_table.c.household_id == str(household_id))
        )
        if require_active_run:
            statement = statement.where(
                agent_plan_runs_table.c.status.in_(("queued", "running"))
            ).where(agent_plan_runs_table.c.deadline_at > now)
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            raise AgentOperationConflict("agent_operation_not_reservable")
        kind = AgentOperationKind(str(row["operation_kind"]))
        if row["provider_id"] is None or kind not in _NETWORK_OPERATION_KINDS:
            raise AgentOperationConflict("agent_operation_not_networked")
        if row["provider_id"] != provider_id:
            raise AgentOperationConflict("agent_operation_provider_mismatch")
        return row

    async def _get_http_reservation(
        self,
        operation_id: UUID,
        operation_attempt_number: int,
    ) -> RowMapping | None:
        return (
            (
                await self._session.execute(
                    select(agent_provider_http_attempts_table)
                    .where(agent_provider_http_attempts_table.c.operation_id == str(operation_id))
                    .where(
                        agent_provider_http_attempts_table.c.operation_attempt_number
                        == operation_attempt_number
                    )
                )
            )
            .mappings()
            .one_or_none()
        )

    async def _validate_unconsumed_circuit_permit(
        self,
        operation: RowMapping,
        permit: ServerPrivateCircuitPermit,
        permit_digest: str,
        now: datetime,
    ) -> None:
        stored_expiry = operation["circuit_permit_expires_at"]
        if (
            operation["circuit_permit_token_digest"] != permit_digest
            or operation["circuit_permit_generation"] != permit.generation
            or operation["circuit_permit_mode"] != permit.mode.value
            or operation["circuit_permit_attempt_number"] != permit.operation_attempt_number
            or stored_expiry is None
            or _aware_datetime(cast(datetime, stored_expiry)) != permit.expires_at
            or operation["circuit_permit_consumed_at"] is not None
            or now >= permit.expires_at
        ):
            raise AgentOperationConflict("agent_circuit_permit_stale")
        state = await self._locked_circuit_row(permit.provider_id)
        _require_current_circuit_binding(state, permit, permit_digest, now=now)

    async def _prepare_circuit_outcome(
        self,
        permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        desired_outcome: CircuitOutcome,
        now: datetime,
    ) -> tuple[RowMapping, bool, bool]:
        permit_digest = _permit_digest(permit.token)
        reservation_statement = (
            select(agent_provider_http_attempts_table)
            .where(agent_provider_http_attempts_table.c.id == str(reservation_id))
            .where(agent_provider_http_attempts_table.c.operation_id == str(permit.operation_id))
            .where(agent_provider_http_attempts_table.c.provider_id == permit.provider_id)
            .where(
                agent_provider_http_attempts_table.c.operation_attempt_number
                == permit.operation_attempt_number
            )
            .where(
                agent_provider_http_attempts_table.c.circuit_permit_generation == permit.generation
            )
            .where(
                agent_provider_http_attempts_table.c.circuit_permit_token_digest == permit_digest
            )
        )
        if self._session.get_bind().dialect.name != "sqlite":
            reservation_statement = reservation_statement.with_for_update()
        reservation = (await self._session.execute(reservation_statement)).mappings().one_or_none()
        if reservation is None:
            raise AgentOperationConflict("agent_circuit_permit_stale")
        stored_outcome = reservation["circuit_outcome"]
        if stored_outcome is not None:
            if CircuitOutcome(str(stored_outcome)) is not desired_outcome:
                raise AgentOperationConflict("agent_circuit_outcome_conflict")
            return await self._locked_circuit_row(permit.provider_id), True, False
        reserved_at = _aware_datetime(cast(datetime, reservation["reserved_at"]))
        if reserved_at > permit.expires_at or now < reserved_at:
            raise AgentOperationConflict("agent_circuit_permit_stale")
        state = await self._locked_circuit_row(permit.provider_id)
        try:
            _require_current_circuit_binding(state, permit, permit_digest, now=None)
        except AgentOperationConflict as error:
            if (
                error.code == "agent_circuit_permit_stale"
                and int(state["generation"]) > permit.generation
            ):
                return state, False, False
            raise
        operation = (
            (
                await self._session.execute(
                    select(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == str(permit.operation_id))
                    .where(
                        agent_run_operations_table.c.circuit_permit_token_digest == permit_digest
                    )
                    .where(
                        agent_run_operations_table.c.circuit_permit_generation == permit.generation
                    )
                    .where(
                        agent_run_operations_table.c.circuit_permit_attempt_number
                        == permit.operation_attempt_number
                    )
                    .where(agent_run_operations_table.c.circuit_permit_consumed_at.is_not(None))
                )
            )
            .mappings()
            .one_or_none()
        )
        if operation is None:
            raise AgentOperationConflict("agent_circuit_permit_stale")
        return state, False, True

    async def _persist_circuit_outcome(
        self,
        reservation_id: UUID,
        outcome: CircuitOutcome,
        recorded_at: datetime,
    ) -> None:
        result = await self._session.execute(
            update(agent_provider_http_attempts_table)
            .where(agent_provider_http_attempts_table.c.id == str(reservation_id))
            .where(agent_provider_http_attempts_table.c.circuit_outcome.is_(None))
            .where(agent_provider_http_attempts_table.c.circuit_outcome_recorded_at.is_(None))
            .values(
                circuit_outcome=outcome.value,
                circuit_outcome_recorded_at=recorded_at,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise AgentOperationConflict("agent_circuit_outcome_conflict")

    async def _locked_claimed_operation(
        self,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        now: datetime,
    ) -> RowMapping | None:
        statement = (
            select(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at >= now)
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).mappings().one_or_none()

    async def _raise_operation_transition_conflict(
        self,
        household_id: UUID,
        operation_id: UUID,
    ) -> None:
        if await self.get_operation(household_id, operation_id) is None:
            raise AgentOperationConflict("agent_operation_not_found")
        raise AgentOperationConflict("agent_operation_transition_conflict")

    async def _validate_operation_result_reference(
        self,
        source: RowMapping,
        result_type: AgentOperationResultType,
        result_id: UUID,
        now: datetime,
    ) -> None:
        kind = AgentOperationKind(str(source["operation_kind"]))
        allowed = _OPERATION_RESULT_MATRIX[kind]
        if result_type not in allowed:
            raise AgentOperationConflict("agent_operation_result_incompatible")
        if not isinstance(result_id, UUID):
            raise TypeError("result_id must be UUID")

        if result_type is AgentOperationResultType.OPERATION:
            await self._bind_operation_handoff(source, result_id, now)
            return

        table, stage_scoped = _RESULT_REFERENCE_TABLES[result_type]
        statement = (
            select(table.c.id)
            .where(table.c.id == str(result_id))
            .where(table.c.household_id == str(source["household_id"]))
            .where(table.c.run_id == str(source["run_id"]))
        )
        if stage_scoped:
            statement = statement.where(table.c.stage_id == str(source["stage_id"]))
        if (
            kind
            in {
                AgentOperationKind.CALENDAR_SEARCH,
                AgentOperationKind.SUGGEST_DISCOVERY,
            }
            and result_type is AgentOperationResultType.DISCOVERY_SIGNAL
        ) or (
            kind is AgentOperationKind.EXACT_POLL
            and result_type is AgentOperationResultType.CONFIRMED_OFFER
        ):
            statement = statement.where(table.c.provider_id == source["provider_id"])
        exists = (await self._session.execute(statement)).scalar_one_or_none()
        if exists is None:
            raise AgentOperationConflict("agent_operation_result_not_found")

    async def _bind_operation_handoff(
        self,
        source: RowMapping,
        target_id: UUID,
        now: datetime,
    ) -> None:
        if str(target_id) == str(source["id"]):
            raise AgentOperationConflict("agent_operation_result_invalid")
        statement = (
            select(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(target_id))
            .where(agent_run_operations_table.c.household_id == str(source["household_id"]))
            .where(agent_run_operations_table.c.run_id == str(source["run_id"]))
            .where(agent_run_operations_table.c.stage_id == str(source["stage_id"]))
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        target = (await self._session.execute(statement)).mappings().one_or_none()
        if target is None:
            raise AgentOperationConflict("agent_operation_result_not_found")
        source_kind = AgentOperationKind(str(source["operation_kind"]))
        source_root_id = source["logical_root_operation_id"]
        expected_root_id = (
            source["id"] if source_kind is AgentOperationKind.EXACT_START else source_root_id
        )
        if (
            AgentOperationKind(str(target["operation_kind"])) is not AgentOperationKind.EXACT_POLL
            or target["provider_id"] != source["provider_id"]
            or target["logical_operation_fingerprint"] != source["logical_operation_fingerprint"]
            or target["logical_root_operation_id"] != expected_root_id
        ):
            raise AgentOperationConflict("agent_operation_result_invalid")
        if (
            target["status"] != AgentOperationStatus.PENDING.value
            or int(target["attempt_count"]) != 0
            or target["handoff_predecessor_operation_id"] is not None
            or _aware_datetime(cast(datetime, target["created_at"]))
            < _aware_datetime(cast(datetime, source["created_at"]))
        ):
            raise AgentOperationConflict("agent_operation_handoff_conflict")
        target_created_at = _aware_datetime(cast(datetime, target["created_at"]))
        bound_at = max(now, target_created_at)
        bound = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(target_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.PENDING.value)
            .where(agent_run_operations_table.c.attempt_count == 0)
            .where(agent_run_operations_table.c.handoff_predecessor_operation_id.is_(None))
            .where(agent_run_operations_table.c.created_at >= source["created_at"])
            .values(
                handoff_predecessor_operation_id=str(source["id"]),
                updated_at=bound_at,
            )
        )
        if cast(CursorResult[Any], bound).rowcount != 1:
            raise AgentOperationConflict("agent_operation_handoff_conflict")

    async def _get_stage_by_kind(
        self,
        household_id: UUID,
        run_id: UUID,
        kind: AgentPlanStageKind,
    ) -> AgentPlanStageRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_plan_stages_table)
                    .where(agent_plan_stages_table.c.household_id == str(household_id))
                    .where(agent_plan_stages_table.c.run_id == str(run_id))
                    .where(agent_plan_stages_table.c.stage_kind == kind.value)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _stage_record(row) if row is not None else None

    async def _get_operation_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> RowMapping | None:
        return (
            (
                await self._session.execute(
                    select(agent_run_operations_table)
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                    .where(agent_run_operations_table.c.run_id == str(run_id))
                    .where(agent_run_operations_table.c.operation_fingerprint == fingerprint)
                )
            )
            .mappings()
            .one_or_none()
        )

    async def _get_logical_root(
        self,
        household_id: UUID,
        run_id: UUID,
        logical_fingerprint: str,
    ) -> AgentRunOperationRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_run_operations_table)
                    .where(agent_run_operations_table.c.household_id == str(household_id))
                    .where(agent_run_operations_table.c.run_id == str(run_id))
                    .where(
                        agent_run_operations_table.c.logical_operation_fingerprint
                        == logical_fingerprint
                    )
                    .where(agent_run_operations_table.c.consumes_logical_unit.is_(True))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _operation_record(row) if row is not None else None

    async def _get_logical_root_by_id(
        self,
        household_id: UUID,
        run_id: UUID,
        operation_id: UUID,
    ) -> AgentRunOperationRecord | None:
        statement = (
            select(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.run_id == str(run_id))
            .where(agent_run_operations_table.c.consumes_logical_unit.is_(True))
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return _operation_record(row) if row is not None else None

    async def _required_operation(
        self,
        household_id: UUID,
        operation_id: UUID,
    ) -> AgentRunOperationRecord:
        stored = await self.get_operation(household_id, operation_id)
        if stored is None:
            raise AgentOperationConflict("agent_operation_not_found")
        return stored

    async def _require_operation_transition(
        self,
        result: object,
        household_id: UUID,
        operation_id: UUID,
    ) -> None:
        if cast(CursorResult[Any], result).rowcount == 1:
            return
        if await self.get_operation(household_id, operation_id) is None:
            raise AgentOperationConflict("agent_operation_not_found")
        raise AgentOperationConflict("agent_operation_transition_conflict")

    async def _get_scope_snapshot_by_run(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> AgentRunScopeSnapshotRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_run_scope_snapshots_table)
                    .where(agent_run_scope_snapshots_table.c.household_id == str(household_id))
                    .where(agent_run_scope_snapshots_table.c.run_id == str(run_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _scope_snapshot_record(row) if row is not None else None

    async def _ensure_provider_lock(self, provider_id: str, now: datetime) -> None:
        dialect_name = self._session.get_bind().dialect.name
        values = {"provider_id": provider_id, "touched_at": now}
        statement: Any
        if dialect_name == "sqlite":
            statement = sqlite_insert(agent_provider_rate_locks_table).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["provider_id"])
        elif dialect_name == "postgresql":
            statement = postgresql_insert(agent_provider_rate_locks_table).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["provider_id"])
        else:
            statement = insert(agent_provider_rate_locks_table).values(**values)
        try:
            async with self._session.begin_nested():
                await self._session.execute(statement)
        except IntegrityError:
            if dialect_name in {"sqlite", "postgresql"}:
                raise
        await self._session.execute(
            update(agent_provider_rate_locks_table)
            .where(agent_provider_rate_locks_table.c.provider_id == provider_id)
            .values(touched_at=now)
        )

    async def _ensure_circuit_row(self, provider_id: str, now: datetime) -> None:
        dialect_name = self._session.get_bind().dialect.name
        values = {
            "provider_id": provider_id,
            "state": AgentCircuitState.CLOSED.value,
            "consecutive_transient_failures": 0,
            "opened_at": None,
            "cooldown_until": None,
            "half_open_probe_operation_id": None,
            "half_open_probe_attempt_number": None,
            "half_open_probe_token_digest": None,
            "half_open_probe_expires_at": None,
            "generation": 0,
            "version": 0,
            "updated_at": now,
        }
        statement: Any
        if dialect_name == "sqlite":
            statement = sqlite_insert(agent_provider_circuit_state_table).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["provider_id"])
        elif dialect_name == "postgresql":
            statement = postgresql_insert(agent_provider_circuit_state_table).values(**values)
            statement = statement.on_conflict_do_nothing(index_elements=["provider_id"])
        else:
            statement = insert(agent_provider_circuit_state_table).values(**values)
        try:
            async with self._session.begin_nested():
                await self._session.execute(statement)
        except IntegrityError:
            if dialect_name in {"sqlite", "postgresql"}:
                raise

    async def _locked_circuit_state(self, provider_id: str) -> AgentCircuitStateRecord:
        return _circuit_record(await self._locked_circuit_row(provider_id))

    async def _locked_circuit_row(self, provider_id: str) -> RowMapping:
        statement = select(agent_provider_circuit_state_table).where(
            agent_provider_circuit_state_table.c.provider_id == provider_id
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).mappings().one()


class AgentEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_discovery_signal(
        self,
        signal: NewAgentDiscoverySignal,
    ) -> AgentDiscoverySignalRecord:
        evidence_json = _validate_discovery_signal(signal)
        await self._acquire_write_transaction()
        existing = await self._get_discovery_by_fingerprint(
            signal.household_id,
            signal.run_id,
            signal.fingerprint,
        )
        if existing is not None:
            return existing
        await self._require_stage(signal.household_id, signal.run_id, signal.stage_id)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_discovery_signals_table).values(
                        id=str(signal.id),
                        household_id=str(signal.household_id),
                        run_id=str(signal.run_id),
                        stage_id=str(signal.stage_id),
                        provider_id=signal.provider_id,
                        origin=signal.origin,
                        destination=signal.destination,
                        departure_date=signal.departure_date,
                        return_date=signal.return_date,
                        amount_minor=signal.amount_minor,
                        currency=signal.currency,
                        passengers=signal.passengers,
                        passenger_basis=PriceBasis(signal.passenger_basis).value,
                        source_kind=DiscoverySource(signal.source_kind).value,
                        freshness=Freshness(signal.freshness).value,
                        observed_at=_utc_datetime(signal.observed_at),
                        signal_evidence_json=evidence_json,
                        fingerprint=signal.fingerprint,
                        created_at=_utc_datetime(signal.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_discovery_by_fingerprint(
                signal.household_id,
                signal.run_id,
                signal.fingerprint,
            )
            if existing is not None:
                return existing
            raise
        stored = await self.get_discovery_signal(signal.household_id, signal.id)
        if stored is None:
            raise RuntimeError("created discovery signal is missing")
        return stored

    async def get_discovery_signal(
        self,
        household_id: UUID,
        signal_id: UUID,
    ) -> AgentDiscoverySignalRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_discovery_signals_table)
                    .where(agent_discovery_signals_table.c.id == str(signal_id))
                    .where(agent_discovery_signals_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _discovery_signal_record(row) if row is not None else None

    async def list_discovery_signals(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> tuple[AgentDiscoverySignalRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_discovery_signals_table)
                .where(agent_discovery_signals_table.c.household_id == str(household_id))
                .where(agent_discovery_signals_table.c.run_id == str(run_id))
                .order_by(
                    agent_discovery_signals_table.c.observed_at.asc(),
                    agent_discovery_signals_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_discovery_signal_record(row) for row in rows)

    async def list_discovery_signals_for_runs(
        self,
        household_id: UUID,
        run_ids: Sequence[UUID],
    ) -> Mapping[UUID, tuple[AgentDiscoverySignalRecord, ...]]:
        ids = _bounded_uuid_ids(run_ids, "run_ids")
        grouped: dict[UUID, list[AgentDiscoverySignalRecord]] = {run_id: [] for run_id in ids}
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                select(agent_discovery_signals_table)
                .where(agent_discovery_signals_table.c.household_id == str(household_id))
                .where(
                    agent_discovery_signals_table.c.run_id.in_(tuple(str(run_id) for run_id in ids))
                )
                .order_by(
                    agent_discovery_signals_table.c.run_id.asc(),
                    agent_discovery_signals_table.c.observed_at.asc(),
                    agent_discovery_signals_table.c.id.asc(),
                )
            )
        ).mappings()
        for row in rows:
            record = _discovery_signal_record(row)
            grouped[record.run_id].append(record)
        return {run_id: tuple(records) for run_id, records in grouped.items()}

    async def append_confirmed_evidence(
        self,
        evidence: NewAgentConfirmedOfferEvidence,
    ) -> AgentConfirmedOfferEvidenceRecord:
        itinerary_json = _validate_confirmed_evidence(evidence)
        await self._acquire_write_transaction()
        existing = await self._get_confirmed_by_fingerprint(
            evidence.household_id,
            evidence.run_id,
            evidence.fingerprint,
        )
        if existing is not None:
            return existing
        await self._require_stage(evidence.household_id, evidence.run_id, evidence.stage_id)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_confirmed_offer_evidence_table).values(
                        id=str(evidence.id),
                        household_id=str(evidence.household_id),
                        run_id=str(evidence.run_id),
                        stage_id=str(evidence.stage_id),
                        provider_id=evidence.provider_id,
                        source=evidence.source,
                        observed_at=_utc_datetime(evidence.observed_at),
                        freshness=Freshness(evidence.freshness).value,
                        passengers=evidence.passengers,
                        passenger_basis=PriceBasis(evidence.passenger_basis).value,
                        amount_minor=evidence.amount_minor,
                        currency=evidence.currency,
                        itinerary_evidence_json=itinerary_json,
                        protection_status=ProtectionStatus(evidence.protection_status).value,
                        baggage_status=_optional_enum_value(
                            evidence.baggage_status,
                            BaggageEvidenceStatus,
                        ),
                        transfer_status=_optional_enum_value(
                            evidence.transfer_status,
                            TransferEvidenceStatus,
                        ),
                        visa_status=_optional_enum_value(
                            evidence.visa_status,
                            VisaEvidenceStatus,
                        ),
                        fingerprint=evidence.fingerprint,
                        created_at=_utc_datetime(evidence.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_confirmed_by_fingerprint(
                evidence.household_id,
                evidence.run_id,
                evidence.fingerprint,
            )
            if existing is not None:
                return existing
            raise
        stored = await self.get_confirmed_evidence(evidence.household_id, evidence.id)
        if stored is None:
            raise RuntimeError("created confirmed evidence is missing")
        return stored

    async def get_confirmed_evidence(
        self,
        household_id: UUID,
        evidence_id: UUID,
    ) -> AgentConfirmedOfferEvidenceRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_confirmed_offer_evidence_table)
                    .where(agent_confirmed_offer_evidence_table.c.id == str(evidence_id))
                    .where(agent_confirmed_offer_evidence_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _confirmed_evidence_record(row) if row is not None else None

    async def list_confirmed_evidence(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> tuple[AgentConfirmedOfferEvidenceRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_confirmed_offer_evidence_table)
                .where(agent_confirmed_offer_evidence_table.c.household_id == str(household_id))
                .where(agent_confirmed_offer_evidence_table.c.run_id == str(run_id))
                .order_by(
                    agent_confirmed_offer_evidence_table.c.observed_at.asc(),
                    agent_confirmed_offer_evidence_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_confirmed_evidence_record(row) for row in rows)

    async def append_booking_action_descriptor(
        self,
        descriptor: NewAgentBookingActionDescriptor,
    ) -> AgentBookingActionDescriptorRecord:
        private_json = _validate_booking_action_descriptor(descriptor)
        await self._acquire_write_transaction()
        existing = await self.get_booking_action_descriptor_for_evidence(
            descriptor.household_id,
            descriptor.confirmed_evidence_id,
        )
        if existing is not None:
            if _booking_action_descriptor_matches(existing, descriptor):
                return existing
            raise AgentEvidenceError("agent_booking_descriptor_conflict")
        await self._require_confirmed_references(
            descriptor.household_id,
            descriptor.run_id,
            (descriptor.confirmed_evidence_id,),
        )
        integrity_collision = False
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_booking_action_descriptors_table).values(
                        id=str(descriptor.id),
                        household_id=str(descriptor.household_id),
                        run_id=str(descriptor.run_id),
                        confirmed_evidence_id=str(descriptor.confirmed_evidence_id),
                        provider_id=descriptor.provider_id,
                        private_descriptor_json=private_json,
                        fingerprint=descriptor.fingerprint,
                        created_at=_utc_datetime(descriptor.created_at),
                        expires_at=_utc_datetime(descriptor.expires_at),
                    )
                )
        except IntegrityError:
            integrity_collision = True
        if integrity_collision:
            existing_by_evidence = await self.get_booking_action_descriptor_for_evidence(
                descriptor.household_id,
                descriptor.confirmed_evidence_id,
            )
            if existing_by_evidence is not None and _booking_action_descriptor_matches(
                existing_by_evidence,
                descriptor,
            ):
                return existing_by_evidence
            existing_by_id = await self.get_booking_action_descriptor(
                descriptor.household_id,
                descriptor.id,
            )
            if existing_by_id is not None and _booking_action_descriptor_matches(
                existing_by_id, descriptor
            ):
                return existing_by_id
            raise AgentEvidenceError("agent_booking_descriptor_conflict")
        stored = await self.get_booking_action_descriptor(
            descriptor.household_id,
            descriptor.id,
        )
        if stored is None:
            raise RuntimeError("created booking descriptor is missing")
        return stored

    async def get_booking_action_descriptor(
        self,
        household_id: UUID,
        descriptor_id: UUID,
    ) -> AgentBookingActionDescriptorRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_booking_action_descriptors_table)
                    .where(agent_booking_action_descriptors_table.c.id == str(descriptor_id))
                    .where(
                        agent_booking_action_descriptors_table.c.household_id == str(household_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _booking_action_descriptor_record(row) if row is not None else None

    async def get_booking_action_descriptor_for_evidence(
        self,
        household_id: UUID,
        confirmed_evidence_id: UUID,
    ) -> AgentBookingActionDescriptorRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_booking_action_descriptors_table)
                    .where(
                        agent_booking_action_descriptors_table.c.confirmed_evidence_id
                        == str(confirmed_evidence_id)
                    )
                    .where(
                        agent_booking_action_descriptors_table.c.household_id == str(household_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _booking_action_descriptor_record(row) if row is not None else None

    async def list_booking_action_descriptors(
        self,
        household_id: UUID,
        run_id: UUID,
        *,
        active_at: datetime,
    ) -> tuple[AgentBookingActionDescriptorRecord, ...]:
        _require_aware(active_at, "active_at")
        rows = (
            await self._session.execute(
                select(agent_booking_action_descriptors_table)
                .where(agent_booking_action_descriptors_table.c.household_id == str(household_id))
                .where(agent_booking_action_descriptors_table.c.run_id == str(run_id))
                .where(
                    agent_booking_action_descriptors_table.c.expires_at > _utc_datetime(active_at)
                )
                .order_by(agent_booking_action_descriptors_table.c.confirmed_evidence_id.asc())
            )
        ).mappings()
        return tuple(_booking_action_descriptor_record(row) for row in rows)

    async def append_composed_candidate(
        self,
        candidate: NewAgentComposedRouteCandidate,
    ) -> AgentComposedRouteCandidateRecord:
        itinerary_json = _validate_composed_candidate(candidate)
        await self._acquire_write_transaction()
        existing = await self._get_candidate_by_fingerprint(
            candidate.household_id,
            candidate.run_id,
            candidate.fingerprint,
        )
        if existing is not None:
            return existing
        await self._require_stage(candidate.household_id, candidate.run_id, candidate.stage_id)
        components = await self._require_confirmed_references(
            candidate.household_id,
            candidate.run_id,
            candidate.component_evidence_ids,
        )
        _validate_composed_component_consistency(candidate, components)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_composed_route_candidates_table).values(
                        id=str(candidate.id),
                        household_id=str(candidate.household_id),
                        run_id=str(candidate.run_id),
                        stage_id=str(candidate.stage_id),
                        component_evidence_ids_json=_uuid_tuple_json(
                            candidate.component_evidence_ids
                        ),
                        observed_at=_utc_datetime(candidate.observed_at),
                        passengers=candidate.passengers,
                        passenger_basis=PriceBasis(candidate.passenger_basis).value,
                        amount_minor=candidate.amount_minor,
                        currency=candidate.currency,
                        itinerary_evidence_json=itinerary_json,
                        protection_status=ProtectionStatus(candidate.protection_status).value,
                        baggage_status=_optional_enum_value(
                            candidate.baggage_status,
                            BaggageEvidenceStatus,
                        ),
                        transfer_status=_optional_enum_value(
                            candidate.transfer_status,
                            TransferEvidenceStatus,
                        ),
                        visa_status=_optional_enum_value(
                            candidate.visa_status,
                            VisaEvidenceStatus,
                        ),
                        fingerprint=candidate.fingerprint,
                        created_at=_utc_datetime(candidate.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_candidate_by_fingerprint(
                candidate.household_id,
                candidate.run_id,
                candidate.fingerprint,
            )
            if existing is not None:
                return existing
            raise
        stored = await self.get_composed_candidate(candidate.household_id, candidate.id)
        if stored is None:
            raise RuntimeError("created composed candidate is missing")
        return stored

    async def get_composed_candidate(
        self,
        household_id: UUID,
        candidate_id: UUID,
    ) -> AgentComposedRouteCandidateRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_composed_route_candidates_table)
                    .where(agent_composed_route_candidates_table.c.id == str(candidate_id))
                    .where(
                        agent_composed_route_candidates_table.c.household_id == str(household_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return _composed_candidate_record(row) if row is not None else None

    async def list_composed_candidates(
        self,
        household_id: UUID,
        run_id: UUID,
    ) -> tuple[AgentComposedRouteCandidateRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_composed_route_candidates_table)
                .where(agent_composed_route_candidates_table.c.household_id == str(household_id))
                .where(agent_composed_route_candidates_table.c.run_id == str(run_id))
                .order_by(
                    agent_composed_route_candidates_table.c.observed_at.asc(),
                    agent_composed_route_candidates_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_composed_candidate_record(row) for row in rows)

    async def create_ranking_snapshot(
        self,
        snapshot: NewAgentRankingSnapshot,
    ) -> AgentRankingSnapshotRecord:
        ranking_json = _validate_ranking_snapshot(snapshot)
        await self._acquire_write_transaction()
        existing = await self._get_ranking_by_fingerprint(
            snapshot.household_id,
            snapshot.run_id,
            snapshot.fingerprint,
        )
        if existing is not None:
            return existing
        await self._require_run(snapshot.household_id, snapshot.run_id)
        await self._require_ranking_references(snapshot)
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(agent_ranking_snapshots_table).values(
                        id=str(snapshot.id),
                        household_id=str(snapshot.household_id),
                        run_id=str(snapshot.run_id),
                        confirmed_evidence_ids_json=_uuid_tuple_json(
                            snapshot.confirmed_evidence_ids
                        ),
                        composed_candidate_ids_json=_uuid_tuple_json(
                            snapshot.composed_candidate_ids
                        ),
                        ranking_json=ranking_json,
                        fingerprint=snapshot.fingerprint,
                        created_at=_utc_datetime(snapshot.created_at),
                    )
                )
        except IntegrityError:
            existing = await self._get_ranking_by_fingerprint(
                snapshot.household_id,
                snapshot.run_id,
                snapshot.fingerprint,
            )
            if existing is not None:
                return existing
            raise
        stored = await self.get_ranking_snapshot(snapshot.household_id, snapshot.id)
        if stored is None:
            raise RuntimeError("created ranking snapshot is missing")
        return stored

    async def get_ranking_snapshot(
        self,
        household_id: UUID,
        snapshot_id: UUID,
    ) -> AgentRankingSnapshotRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_ranking_snapshots_table)
                    .where(agent_ranking_snapshots_table.c.id == str(snapshot_id))
                    .where(agent_ranking_snapshots_table.c.household_id == str(household_id))
                )
            )
            .mappings()
            .one_or_none()
        )
        return _ranking_snapshot_record(row) if row is not None else None

    async def _acquire_write_transaction(self) -> None:
        try:
            await _acquire_sqlite_write_transaction(self._session)
        except AgentPlanConflict as error:
            raise AgentEvidenceError(error.code) from error

    async def _require_run(self, household_id: UUID, run_id: UUID) -> None:
        exists = (
            await self._session.execute(
                select(agent_plan_runs_table.c.id)
                .where(agent_plan_runs_table.c.id == str(run_id))
                .where(agent_plan_runs_table.c.household_id == str(household_id))
            )
        ).scalar_one_or_none()
        if exists is None:
            raise AgentEvidenceError("agent_evidence_run_not_found")

    async def _require_stage(
        self,
        household_id: UUID,
        run_id: UUID,
        stage_id: UUID,
    ) -> None:
        exists = (
            await self._session.execute(
                select(agent_plan_stages_table.c.id)
                .join(
                    agent_plan_runs_table,
                    agent_plan_runs_table.c.id == agent_plan_stages_table.c.run_id,
                )
                .where(agent_plan_stages_table.c.id == str(stage_id))
                .where(agent_plan_stages_table.c.run_id == str(run_id))
                .where(agent_plan_stages_table.c.household_id == str(household_id))
                .where(agent_plan_runs_table.c.household_id == str(household_id))
            )
        ).scalar_one_or_none()
        if exists is None:
            raise AgentEvidenceError("agent_evidence_stage_not_found")

    async def _require_confirmed_references(
        self,
        household_id: UUID,
        run_id: UUID,
        evidence_ids: tuple[UUID, ...],
    ) -> tuple[AgentConfirmedOfferEvidenceRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_confirmed_offer_evidence_table)
                .where(agent_confirmed_offer_evidence_table.c.household_id == str(household_id))
                .where(agent_confirmed_offer_evidence_table.c.run_id == str(run_id))
                .where(
                    agent_confirmed_offer_evidence_table.c.id.in_(
                        [str(value) for value in evidence_ids]
                    )
                )
            )
        ).mappings()
        by_id = {record.id: record for record in (_confirmed_evidence_record(row) for row in rows)}
        if set(by_id) != set(evidence_ids):
            raise AgentEvidenceError("agent_evidence_reference_not_found")
        return tuple(by_id[value] for value in evidence_ids)

    async def _require_ranking_references(self, snapshot: NewAgentRankingSnapshot) -> None:
        requested_confirmed = {str(value) for value in snapshot.confirmed_evidence_ids}
        if requested_confirmed:
            stored_confirmed = set(
                (
                    await self._session.execute(
                        select(agent_confirmed_offer_evidence_table.c.id)
                        .where(
                            agent_confirmed_offer_evidence_table.c.household_id
                            == str(snapshot.household_id)
                        )
                        .where(
                            agent_confirmed_offer_evidence_table.c.run_id == str(snapshot.run_id)
                        )
                        .where(agent_confirmed_offer_evidence_table.c.id.in_(requested_confirmed))
                    )
                ).scalars()
            )
            missing = requested_confirmed - stored_confirmed
            if missing:
                discovery = (
                    await self._session.execute(
                        select(agent_discovery_signals_table.c.id)
                        .where(
                            agent_discovery_signals_table.c.household_id
                            == str(snapshot.household_id)
                        )
                        .where(agent_discovery_signals_table.c.run_id == str(snapshot.run_id))
                        .where(agent_discovery_signals_table.c.id.in_(missing))
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if discovery is not None:
                    raise AgentEvidenceError("agent_ranking_discovery_signal_forbidden")
                raise AgentEvidenceError("agent_evidence_reference_not_found")

        requested_candidates = {str(value) for value in snapshot.composed_candidate_ids}
        if requested_candidates:
            stored_candidates = set(
                (
                    await self._session.execute(
                        select(agent_composed_route_candidates_table.c.id)
                        .where(
                            agent_composed_route_candidates_table.c.household_id
                            == str(snapshot.household_id)
                        )
                        .where(
                            agent_composed_route_candidates_table.c.run_id == str(snapshot.run_id)
                        )
                        .where(agent_composed_route_candidates_table.c.id.in_(requested_candidates))
                    )
                ).scalars()
            )
            if stored_candidates != requested_candidates:
                raise AgentEvidenceError("agent_evidence_reference_not_found")

    async def _get_discovery_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> AgentDiscoverySignalRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_discovery_signals_table)
                    .where(agent_discovery_signals_table.c.household_id == str(household_id))
                    .where(agent_discovery_signals_table.c.run_id == str(run_id))
                    .where(agent_discovery_signals_table.c.fingerprint == fingerprint)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _discovery_signal_record(row) if row is not None else None

    async def _get_confirmed_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> AgentConfirmedOfferEvidenceRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_confirmed_offer_evidence_table)
                    .where(agent_confirmed_offer_evidence_table.c.household_id == str(household_id))
                    .where(agent_confirmed_offer_evidence_table.c.run_id == str(run_id))
                    .where(agent_confirmed_offer_evidence_table.c.fingerprint == fingerprint)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _confirmed_evidence_record(row) if row is not None else None

    async def _get_candidate_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> AgentComposedRouteCandidateRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_composed_route_candidates_table)
                    .where(
                        agent_composed_route_candidates_table.c.household_id == str(household_id)
                    )
                    .where(agent_composed_route_candidates_table.c.run_id == str(run_id))
                    .where(agent_composed_route_candidates_table.c.fingerprint == fingerprint)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _composed_candidate_record(row) if row is not None else None

    async def _get_ranking_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> AgentRankingSnapshotRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_ranking_snapshots_table)
                    .where(agent_ranking_snapshots_table.c.household_id == str(household_id))
                    .where(agent_ranking_snapshots_table.c.run_id == str(run_id))
                    .where(agent_ranking_snapshots_table.c.fingerprint == fingerprint)
                )
            )
            .mappings()
            .one_or_none()
        )
        return _ranking_snapshot_record(row) if row is not None else None


def _revision_values(
    *,
    plan_id: UUID,
    household_id: UUID,
    source_revision_id: UUID | None,
    revision_number: int,
    revision: NewAgentPlanRevision,
) -> dict[str, object]:
    return {
        "id": str(revision.id),
        "plan_id": str(plan_id),
        "household_id": str(household_id),
        "source_revision_id": str(source_revision_id) if source_revision_id is not None else None,
        "revision_number": revision_number,
        "state": revision.state,
        "plan_json": _canonical_json(revision.plan),
        "scope_snapshot_json": _canonical_json(revision.scope_snapshot),
        "capability_snapshot_json": _canonical_json(revision.capability_snapshot),
        "cost_model_snapshot_json": _canonical_json(revision.cost_model_snapshot),
        "parser_version": revision.parser_version,
        "planner_version": revision.planner_version,
        "estimated_calendar_searches": revision.estimated_calendar_searches,
        "estimated_exact_searches": revision.estimated_exact_searches,
        "estimated_logical_operations": revision.estimated_logical_operations,
        "estimated_http_attempts": revision.estimated_http_attempts,
        "estimated_deadline_seconds": revision.estimated_deadline_seconds,
        "content_hash": _content_hash(revision),
        "clone_idempotency_key": revision.clone_idempotency_key,
        "created_at": _utc_datetime(revision.created_at),
        "expires_at": _utc_datetime(revision.expires_at),
        "superseded_at": None,
        "consumed_at": None,
    }


def _content_hash(revision: NewAgentPlanRevision) -> str:
    return _revision_content_hash(
        plan=revision.plan,
        scope_snapshot=revision.scope_snapshot,
        capability_snapshot=revision.capability_snapshot,
        cost_model_snapshot=revision.cost_model_snapshot,
        parser_version=revision.parser_version,
        planner_version=revision.planner_version,
        calendar_searches=revision.estimated_calendar_searches,
        exact_searches=revision.estimated_exact_searches,
        logical_operations=revision.estimated_logical_operations,
        http_attempts=revision.estimated_http_attempts,
        deadline_seconds=revision.estimated_deadline_seconds,
    )


def recompute_agent_plan_revision_content_hash(revision: AgentPlanRevisionRecord) -> str:
    """Recompute an immutable revision hash from its persisted canonical payload."""

    return _revision_content_hash(
        plan=_json_object(revision.plan_json),
        scope_snapshot=_json_object(revision.scope_snapshot_json),
        capability_snapshot=_json_object(revision.capability_snapshot_json),
        cost_model_snapshot=_json_object(revision.cost_model_snapshot_json),
        parser_version=revision.parser_version,
        planner_version=revision.planner_version,
        calendar_searches=revision.estimated_calendar_searches,
        exact_searches=revision.estimated_exact_searches,
        logical_operations=revision.estimated_logical_operations,
        http_attempts=revision.estimated_http_attempts,
        deadline_seconds=revision.estimated_deadline_seconds,
    )


def _revision_content_hash(
    *,
    plan: Mapping[str, object],
    scope_snapshot: Mapping[str, object],
    capability_snapshot: Mapping[str, object],
    cost_model_snapshot: Mapping[str, object],
    parser_version: str,
    planner_version: str,
    calendar_searches: int | None,
    exact_searches: int | None,
    logical_operations: int | None,
    http_attempts: int | None,
    deadline_seconds: int | None,
) -> str:
    canonical = _canonical_json(
        {
            "plan": plan,
            "scope_snapshot": scope_snapshot,
            "capability_snapshot": capability_snapshot,
            "cost_model_snapshot": cost_model_snapshot,
            "parser_version": parser_version,
            "planner_version": planner_version,
            "estimates": {
                "calendar_searches": calendar_searches,
                "exact_searches": exact_searches,
                "logical_operations": logical_operations,
                "http_attempts": http_attempts,
                "deadline_seconds": deadline_seconds,
            },
        }
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_clone_approval_generation(
    revision: NewAgentPlanRevision,
    *,
    generation: int,
) -> NewAgentPlanRevision:
    plan = dict(revision.plan)
    plan["approval"] = {
        "generation": generation,
        "expires_at": _utc_datetime(revision.expires_at).isoformat(),
    }
    return replace(revision, plan=plan)


def _canonical_json(value: object) -> str:
    return json.dumps(
        _json_mutable_copy(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_new_revision(revision: NewAgentPlanRevision) -> None:
    if revision.state not in _NEW_REVISION_STATES:
        raise ValueError("new agent revision must be draft or awaiting_approval")
    _require_aware(revision.created_at, "created_at")
    _require_aware(revision.expires_at, "expires_at")
    if revision.expires_at <= revision.created_at:
        raise ValueError("revision expires_at must be after created_at")
    if not revision.parser_version.strip() or not revision.planner_version.strip():
        raise ValueError("parser and planner versions are required")
    if revision.clone_idempotency_key is not None and not revision.clone_idempotency_key.strip():
        raise ValueError("clone_idempotency_key must not be blank")
    if revision.state == "awaiting_approval":
        estimates = (
            revision.estimated_calendar_searches,
            revision.estimated_exact_searches,
            revision.estimated_logical_operations,
            revision.estimated_http_attempts,
            revision.estimated_deadline_seconds,
        )
        if any(value is None for value in estimates):
            raise ValueError("awaiting_approval estimates must be complete")
        calendar, exact, logical, http_attempts, deadline_seconds = cast(
            tuple[int, int, int, int, int], estimates
        )
        if (
            type(calendar) is not int
            or calendar < 0
            or type(exact) is not int
            or exact < 0
            or type(logical) is not int
            or logical <= 0
            or type(http_attempts) is not int
            or http_attempts <= 0
            or type(deadline_seconds) is not int
            or deadline_seconds <= 0
        ):
            raise ValueError("awaiting_approval estimates must be valid")
        if logical != calendar + exact:
            raise ValueError("awaiting_approval estimates must be consistent")
    for field_name in ("estimated_calendar_searches", "estimated_exact_searches"):
        value = getattr(revision, field_name)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{field_name} must be a non-negative integer or None")
    for field_name in (
        "estimated_logical_operations",
        "estimated_http_attempts",
        "estimated_deadline_seconds",
    ):
        value = getattr(revision, field_name)
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError(f"{field_name} must be a positive integer or None")


def _validate_approval_snapshot(snapshot: AgentPlanApprovalSnapshot) -> None:
    if len(snapshot.revision_content_hash) != 71 or not snapshot.revision_content_hash.startswith(
        "sha256:"
    ):
        raise ValueError("revision_content_hash must be a sha256 checksum")
    if any(not strategy.strip() for strategy in snapshot.approved_strategies):
        raise ValueError("approved strategies must not be blank")
    if any(
        not warning_id.strip() or not version.strip()
        for warning_id, version in snapshot.risk_warning_versions.items()
    ):
        raise ValueError("risk warning ids and versions must not be blank")


def _validate_new_run(run: NewAgentPlanRun) -> None:
    _require_aware(run.created_at, "created_at")
    _require_aware(run.deadline_at, "deadline_at")
    if run.deadline_at <= run.created_at:
        raise ValueError("run deadline_at must be after created_at")
    if not run.execute_idempotency_key.strip():
        raise ValueError("execute_idempotency_key must not be blank")


def _plan_record(row: RowMapping) -> AgentPlanRecord:
    return AgentPlanRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        created_by_user_id=UUID(str(row["created_by_user_id"])),
        created_at=_aware_datetime(row["created_at"]),
    )


def _revision_record(row: RowMapping) -> AgentPlanRevisionRecord:
    source_revision_id = row["source_revision_id"]
    superseded_at = row["superseded_at"]
    consumed_at = row["consumed_at"]
    return AgentPlanRevisionRecord(
        id=UUID(str(row["id"])),
        plan_id=UUID(str(row["plan_id"])),
        household_id=UUID(str(row["household_id"])),
        source_revision_id=(
            UUID(str(source_revision_id)) if source_revision_id is not None else None
        ),
        revision_number=int(row["revision_number"]),
        state=str(row["state"]),
        plan_json=str(row["plan_json"]),
        scope_snapshot_json=str(row["scope_snapshot_json"]),
        capability_snapshot_json=str(row["capability_snapshot_json"]),
        cost_model_snapshot_json=str(row["cost_model_snapshot_json"]),
        parser_version=str(row["parser_version"]),
        planner_version=str(row["planner_version"]),
        estimated_calendar_searches=row["estimated_calendar_searches"],
        estimated_exact_searches=row["estimated_exact_searches"],
        estimated_logical_operations=row["estimated_logical_operations"],
        estimated_http_attempts=row["estimated_http_attempts"],
        estimated_deadline_seconds=row["estimated_deadline_seconds"],
        content_hash=str(row["content_hash"]),
        clone_idempotency_key=row["clone_idempotency_key"],
        created_at=_aware_datetime(row["created_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
        superseded_at=(_aware_datetime(superseded_at) if superseded_at is not None else None),
        consumed_at=_aware_datetime(consumed_at) if consumed_at is not None else None,
    )


def _approval_record(row: RowMapping) -> AgentPlanApprovalRecord:
    consumed_at = row["consumed_at"]
    run_id = row["run_id"]
    return AgentPlanApprovalRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        plan_id=UUID(str(row["plan_id"])),
        revision_id=UUID(str(row["revision_id"])),
        approved_by_user_id=UUID(str(row["approved_by_user_id"])),
        approved_at=_aware_datetime(row["approved_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
        snapshot=AgentPlanApprovalSnapshot(
            revision_content_hash=str(row["revision_content_hash"]),
            approved_by_session_id=UUID(str(row["approved_by_session_id"])),
            approved_budget=_json_object(str(row["approved_budget_json"])),
            approved_strategies=_json_string_tuple(str(row["approved_strategies_json"])),
            risk_warning_versions=_json_string_mapping(str(row["risk_warning_versions_json"])),
        ),
        consumed_at=_aware_datetime(consumed_at) if consumed_at is not None else None,
        run_id=UUID(str(run_id)) if run_id is not None else None,
    )


def _execution_candidate_priority(status: str) -> int:
    if status == "cancel_requested":
        return 0
    if status == "queued":
        return 1
    return 2


def _run_record(row: RowMapping) -> AgentPlanRunRecord:
    started_at = row["started_at"]
    cancel_requested_at = row["cancel_requested_at"]
    finished_at = row["finished_at"]
    return AgentPlanRunRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        plan_id=UUID(str(row["plan_id"])),
        revision_id=UUID(str(row["revision_id"])),
        approval_id=UUID(str(row["approval_id"])),
        execute_idempotency_key=str(row["execute_idempotency_key"]),
        status=str(row["status"]),
        created_at=_aware_datetime(row["created_at"]),
        deadline_at=_aware_datetime(row["deadline_at"]),
        started_at=_aware_datetime(started_at) if started_at is not None else None,
        cancel_requested_at=(
            _aware_datetime(cancel_requested_at) if cancel_requested_at is not None else None
        ),
        finished_at=_aware_datetime(finished_at) if finished_at is not None else None,
        error_code=row["error_code"],
        error_message=row["error_message"],
        logical_operation_budget=int(row["logical_operation_budget"]),
        logical_operations_consumed=int(row["logical_operations_consumed"]),
        http_attempt_budget=int(row["http_attempt_budget"]),
        http_attempts_consumed=int(row["http_attempts_consumed"]),
    )


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_datetime(value: datetime) -> datetime:
    _require_aware(value, "datetime")
    return value.astimezone(UTC)


async def _acquire_sqlite_write_transaction(session: AsyncSession) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        return
    if session.in_nested_transaction():
        raise AgentPlanConflict("agent_sqlite_nested_transaction_unsupported")
    connection = await session.connection()
    sync_connection = connection.sync_connection
    if sync_connection is None:
        raise RuntimeError("SQLite synchronous connection is unavailable")
    pooled_connection = sync_connection.connection
    if pooled_connection is None:
        raise RuntimeError("SQLite pooled connection is unavailable")
    driver_connection = pooled_connection.driver_connection
    in_transaction = getattr(driver_connection, "in_transaction", None)
    if not isinstance(in_transaction, bool):
        raise RuntimeError("SQLite driver does not expose transaction state")
    if not in_transaction:
        await connection.exec_driver_sql("BEGIN IMMEDIATE")


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _json_mutable_copy(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_mutable_copy(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_mutable_copy(item) for item in value]
    return value


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _json_object(raw: str) -> dict[str, object]:
    payload: object = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("stored approval JSON must be an object")
    return {str(key): value for key, value in payload.items()}


def _json_string_tuple(raw: str) -> tuple[str, ...]:
    payload: object = json.loads(raw)
    if not isinstance(payload, list) or not all(isinstance(value, str) for value in payload):
        raise RuntimeError("stored approved strategies JSON must be a string array")
    return tuple(payload)


def _json_string_mapping(raw: str) -> dict[str, str]:
    payload = _json_object(raw)
    if not all(isinstance(value, str) for value in payload.values()):
        raise RuntimeError("stored risk warning versions JSON must contain strings")
    return {key: cast(str, value) for key, value in payload.items()}


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UNSAFE_JSON_KEY_PARTS = (
    "authorization",
    "signature",
    "marker",
    "token",
    "cookie",
    "secret",
    "password",
    "signed_url",
    "booking_url",
    "provider_payload",
    "provider_response",
    "provider_request",
    "provider_ref",
    "raw_payload",
    "raw_response",
    "raw_request",
    "passenger_email",
    "passenger_phone",
    "passenger_name",
    "full_name",
    "pii",
    "api_key",
    "apikey",
    "credential",
    "access_key",
    "accesskey",
    "email",
    "phone",
    "contact",
)
_PROVIDER_BOUND_OPERATION_KINDS = frozenset(
    {
        AgentOperationKind.CALENDAR_SEARCH,
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
        AgentOperationKind.SUGGEST_DISCOVERY,
    }
)
_INDEPENDENT_OPERATION_KINDS = frozenset(
    {
        AgentOperationKind.SCOPE_FREEZE,
        AgentOperationKind.COMPARISON,
        AgentOperationKind.COMPOSITION,
        AgentOperationKind.RANKING,
        AgentOperationKind.ANALYSIS,
    }
)
_LOGICAL_ROOT_OPERATION_KINDS = frozenset(
    {
        AgentOperationKind.CALENDAR_SEARCH,
        AgentOperationKind.EXACT_START,
        AgentOperationKind.SUGGEST_DISCOVERY,
    }
)
_NETWORK_OPERATION_KINDS = frozenset(
    {
        AgentOperationKind.CALENDAR_SEARCH,
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
        AgentOperationKind.SUGGEST_DISCOVERY,
    }
)
_OPERATION_RESULT_MATRIX: dict[AgentOperationKind, frozenset[AgentOperationResultType]] = {
    AgentOperationKind.SCOPE_FREEZE: frozenset({AgentOperationResultType.SCOPE_SNAPSHOT}),
    AgentOperationKind.CALENDAR_SEARCH: frozenset({AgentOperationResultType.DISCOVERY_SIGNAL}),
    AgentOperationKind.EXACT_START: frozenset({AgentOperationResultType.OPERATION}),
    AgentOperationKind.EXACT_POLL: frozenset(
        {AgentOperationResultType.OPERATION, AgentOperationResultType.CONFIRMED_OFFER}
    ),
    AgentOperationKind.SUGGEST_DISCOVERY: frozenset({AgentOperationResultType.DISCOVERY_SIGNAL}),
    AgentOperationKind.COMPARISON: frozenset(),
    AgentOperationKind.COMPOSITION: frozenset({AgentOperationResultType.COMPOSED_CANDIDATE}),
    AgentOperationKind.RANKING: frozenset({AgentOperationResultType.RANKING_SNAPSHOT}),
    AgentOperationKind.ANALYSIS: frozenset({AgentOperationResultType.RANKING_SNAPSHOT}),
}
_RESULT_REFERENCE_TABLES: dict[AgentOperationResultType, tuple[Table, bool]] = {
    AgentOperationResultType.SCOPE_SNAPSHOT: (agent_run_scope_snapshots_table, False),
    AgentOperationResultType.DISCOVERY_SIGNAL: (agent_discovery_signals_table, True),
    AgentOperationResultType.CONFIRMED_OFFER: (agent_confirmed_offer_evidence_table, True),
    AgentOperationResultType.COMPOSED_CANDIDATE: (
        agent_composed_route_candidates_table,
        True,
    ),
    AgentOperationResultType.RANKING_SNAPSHOT: (agent_ranking_snapshots_table, False),
}

_OPERATION_INPUT_KEYS = frozenset(
    {
        "value",
        "origin",
        "destination",
        "route",
        "date",
        "departure_date",
        "return_date",
        "date_from",
        "date_to",
        "max_destination_seeds",
        "seed_limit",
        "source_id",
        "source_signal_id",
        "leg_ordinal",
        "search_role",
        "split_source_evidence_id",
        "split_component_ordinal",
        "passengers",
        "adults",
        "children",
        "infants",
        "phase",
        "poll_round",
        "round",
        "currency",
        "cabin",
        "segment_ids",
        "component_evidence_ids",
        "ranking_profile",
        "workflow_version",
        "analysis_mode",
        "comparison_key",
        "ordered",
        "version",
    }
)
_PRIVATE_CONTINUATION_KEYS = frozenset(
    {
        "value",
        "search_session",
        "search_id",
        "cursor",
        "poll_round",
        "request_id",
        "complete",
        "evidence_namespace",
        "origin",
        "destination",
        "departure_date",
        "return_date",
        "currency",
        "passengers",
    }
)
_SCOPE_SNAPSHOT_KEYS = frozenset(
    {
        "value",
        "airports",
        "origins",
        "destinations",
        "source_signal_ids",
        "catalog_checksum",
        "taxonomy_version",
        "coverage",
    }
)
_DISCOVERY_EVIDENCE_KEYS = frozenset(
    {
        "value",
        "calendar_bucket",
        "route_key",
        "source_id",
        "source_version",
        "leg_ordinal",
    }
)
_CONFIRMED_ITINERARY_KEYS = frozenset(
    {
        "value",
        "leg_ordinal",
        "search_role",
        "split_source_evidence_id",
        "split_component_ordinal",
        "segments",
        "origin",
        "destination",
        "departure_date",
        "return_date",
        "passenger_mix",
        "price_basis",
        "adults",
        "children",
        "infants",
        "depart_at",
        "arrive_at",
        "depart_at_utc",
        "arrive_at_utc",
        "segment_ref",
        "carrier",
        "flight_number",
        "duration_seconds",
        "stops",
        "ticket_structure",
        "seller",
        "fare_family",
    }
)
_COMPOSED_ITINERARY_KEYS = frozenset(
    {
        "value",
        "composition_version",
        "trip_shape",
        "components",
        "component_amounts",
        "minor_units",
        "currency",
        "ordered_legs",
        "ordinal",
        "origin",
        "destination",
        "departure_date",
        "passenger_mix",
        "adults",
        "children",
        "infants",
        "price_basis",
        "target_currency",
        "known_total",
        "price_comparison_status",
        "tickets",
        "ticket_index",
        "leg_ordinal",
        "component_evidence_id",
        "segment_refs",
        "connections",
        "inbound_component_id",
        "outbound_component_id",
        "arrival_airport",
        "departure_airport",
        "layover_seconds",
        "required_minimum_seconds",
        "airport_change",
        "provenance",
        "transfer_cost",
        "unknown_costs",
        "kind",
        "description",
        "protection_status",
        "ranking_reasons",
    }
)
_RANKING_KEYS = frozenset(
    {
        "value",
        "ordered",
        "version",
        "profile",
        "scores",
        "reasons",
        "comparison_currency",
        "confirmed_evidence_ids",
        "composed_candidate_ids",
        "views",
        "fingerprint",
        "name",
        "weights",
        "price",
        "duration",
        "risk",
        "candidates",
        "kind",
        "id",
        "rank",
    }
)


def _bounded_uuid_ids(values: Sequence[UUID], field_name: str) -> tuple[UUID, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise TypeError(f"{field_name} must be an ordered UUID collection")
    if not all(isinstance(value, UUID) for value in values):
        raise TypeError(f"{field_name} must contain UUID values")
    unique = tuple(dict.fromkeys(values))
    if len(unique) > 100:
        raise ValueError(f"{field_name} cannot contain more than 100 values")
    return unique


def canonical_sanitized_json(value: Mapping[str, object]) -> str:
    sanitized = _sanitize_json_value(value, path="$", inspect_keys=True)
    return json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sanitize_json_value(
    value: object,
    *,
    path: str,
    inspect_keys: bool,
) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if path == "$.catalog_checksum" and _SHA256_RE.fullmatch(stripped):
            return stripped
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", stripped, flags=re.IGNORECASE):
            raise ValueError(f"unsafe field at {path}: URI values are not allowed")
        if re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", stripped):
            raise ValueError(f"unsafe field at {path}: email values are not allowed")
        if re.fullmatch(r"\+[0-9() .-]{7,}", stripped):
            raise ValueError(f"unsafe field at {path}: phone values are not allowed")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} JSON object keys must be strings")
            normalized_key = re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")
            compact_key = re.sub(r"[^a-z0-9]+", "", key.casefold())
            if inspect_keys and any(
                re.sub(r"[^a-z0-9]+", "", part.casefold()) in compact_key or part in normalized_key
                for part in _UNSAFE_JSON_KEY_PARTS
            ):
                raise ValueError(f"unsafe field at {path}.{key}")
            sanitized[key] = _sanitize_json_value(
                item,
                path=f"{path}.{key}",
                inspect_keys=inspect_keys,
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _sanitize_json_value(item, path=f"{path}[{index}]", inspect_keys=inspect_keys)
            for index, item in enumerate(value)
        ]
    raise TypeError(f"{path} must contain JSON-compatible values")


def canonical_operation_input_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "operation_input", _OPERATION_INPUT_KEYS)


def _canonical_private_continuation_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "private_continuation", _PRIVATE_CONTINUATION_KEYS)


def _canonical_scope_snapshot_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "scope_snapshot", _SCOPE_SNAPSHOT_KEYS)


def _canonical_discovery_evidence_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "discovery_evidence", _DISCOVERY_EVIDENCE_KEYS)


def _canonical_confirmed_itinerary_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "confirmed_itinerary", _CONFIRMED_ITINERARY_KEYS)


def _canonical_composed_itinerary_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "composed_itinerary", _COMPOSED_ITINERARY_KEYS)


def _canonical_ranking_json(value: Mapping[str, object]) -> str:
    return _canonical_context_json(value, "ranking", _RANKING_KEYS)


def _canonical_context_json(
    value: Mapping[str, object],
    context: str,
    allowed_keys: frozenset[str],
) -> str:
    sanitized = _sanitize_json_value(value, path="$", inspect_keys=True)
    _validate_context_keys(sanitized, context=context, allowed_keys=allowed_keys, path="$")
    _validate_typed_context_values(sanitized, context=context, path="$")
    return json.dumps(
        sanitized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _validate_context_keys(
    value: object,
    *,
    context: str,
    allowed_keys: frozenset[str],
    path: str,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key not in allowed_keys:
                raise ValueError(f"field {path}.{key} is not allowed in {context}")
            _validate_context_keys(
                item,
                context=context,
                allowed_keys=allowed_keys,
                path=f"{path}.{key}",
            )
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_context_keys(
                item,
                context=context,
                allowed_keys=allowed_keys,
                path=f"{path}[{index}]",
            )


def _validate_typed_context_values(value: object, *, context: str, path: str) -> None:
    if isinstance(value, Mapping):
        if "date_from" in value and "date_to" in value:
            date_from = _canonical_context_date(value["date_from"], f"{path}.date_from")
            date_to = _canonical_context_date(value["date_to"], f"{path}.date_to")
            if date_to < date_from:
                raise ValueError(f"{path}.date_to cannot precede date_from")
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in {"origin", "destination"}:
                if not isinstance(item, str) or not re.fullmatch(r"[A-Z0-9]{3}", item):
                    raise ValueError(f"{item_path} must be a normalized IATA code")
            elif (
                key
                in {
                    "date",
                    "departure_date",
                    "return_date",
                    "date_from",
                    "date_to",
                }
                and item is not None
            ):
                _canonical_context_date(item, item_path)
            elif key in {
                "poll_round",
                "round",
                "cursor",
                "duration_seconds",
                "stops",
                "adults",
                "children",
                "infants",
            }:
                if type(item) is not int or item < 0:
                    raise ValueError(f"{item_path} must be a non-negative integer")
            elif key in {"max_destination_seeds", "seed_limit"}:
                if type(item) is not int or item <= 0:
                    raise ValueError(f"{item_path} must be a positive integer")
            elif key == "source_id":
                if not isinstance(item, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", item):
                    raise ValueError(f"{item_path} must be a stable source id")
            elif key == "source_signal_id":
                if not isinstance(item, str):
                    raise TypeError(f"{item_path} must be a canonical UUID string")
                try:
                    parsed_source_signal_id = UUID(item)
                except ValueError as error:
                    raise ValueError(f"{item_path} must be a canonical UUID string") from error
                if str(parsed_source_signal_id) != item:
                    raise ValueError(f"{item_path} must be a canonical UUID string")
            elif key in {"route", "airports", "origins", "destinations"}:
                if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)):
                    raise TypeError(f"{item_path} must be an ordered code collection")
                if not all(
                    isinstance(code, str) and re.fullmatch(r"[A-Z0-9]{3}", code) for code in item
                ):
                    raise ValueError(f"{item_path} must contain normalized IATA codes")
            elif key in {"segments", "components", "ordered"}:
                if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)):
                    raise TypeError(f"{item_path} must be an ordered collection")
            elif key == "passengers" and not (
                (type(item) is int and item > 0) or (isinstance(item, Mapping) and bool(item))
            ):
                raise ValueError(f"{item_path} must be a positive count or typed mix")
            _validate_typed_context_values(item, context=context, path=item_path)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _validate_typed_context_values(item, context=context, path=f"{path}[{index}]")


def _canonical_context_date(value: object, path: str) -> date:
    if not isinstance(value, str):
        raise TypeError(f"{path} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{path} must be an ISO date string") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{path} must be a canonical ISO date string")
    return parsed


def _permit_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _expected_attempt_kind(operation: Mapping[Any, Any]) -> AttemptKind:
    if int(operation["attempt_count"]) > 1:
        return AttemptKind.RETRY
    kind = AgentOperationKind(str(operation["operation_kind"]))
    if kind is AgentOperationKind.EXACT_POLL:
        return AttemptKind.POLL
    if kind in {
        AgentOperationKind.CALENDAR_SEARCH,
        AgentOperationKind.EXACT_START,
        AgentOperationKind.SUGGEST_DISCOVERY,
    }:
        return AttemptKind.START
    raise AgentOperationConflict("agent_operation_not_networked")


def _require_permit_call_binding(
    permit: ServerPrivateCircuitPermit,
    *,
    permit_digest: str,
    operation: Mapping[Any, Any],
    provider_id: str,
) -> None:
    if (
        permit.provider_id != provider_id
        or permit.operation_id != UUID(str(operation["id"]))
        or permit.operation_attempt_number != int(operation["attempt_count"])
        or operation["provider_id"] != provider_id
        or not _SHA256_RE.fullmatch(permit_digest)
    ):
        raise AgentOperationConflict("agent_circuit_permit_stale")


def _require_current_circuit_binding(
    state: Mapping[Any, Any],
    permit: ServerPrivateCircuitPermit,
    permit_digest: str,
    *,
    now: datetime | None,
) -> None:
    if int(state["generation"]) != permit.generation:
        raise AgentOperationConflict("agent_circuit_permit_stale")
    state_value = AgentCircuitState(str(state["state"]))
    if permit.mode is CircuitPermitMode.CLOSED:
        if state_value is not AgentCircuitState.CLOSED:
            raise AgentOperationConflict("agent_circuit_permit_stale")
        return
    probe_expiry = state["half_open_probe_expires_at"]
    if (
        state_value is not AgentCircuitState.HALF_OPEN
        or state["half_open_probe_operation_id"] != str(permit.operation_id)
        or state["half_open_probe_attempt_number"] != permit.operation_attempt_number
        or state["half_open_probe_token_digest"] != permit_digest
        or probe_expiry is None
        or _aware_datetime(cast(datetime, probe_expiry)) != permit.expires_at
        or (now is not None and now >= permit.expires_at)
    ):
        raise AgentOperationConflict("agent_circuit_permit_stale")


def _validate_new_stage(stage: NewAgentPlanStage) -> None:
    if not isinstance(stage.id, UUID) or not isinstance(stage.run_id, UUID):
        raise TypeError("stage and run ids must be UUID values")
    if not isinstance(stage.household_id, UUID):
        raise TypeError("household_id must be UUID")
    AgentPlanStageKind(stage.kind)
    AgentStageStatus(stage.status)
    _require_aware(stage.created_at, "created_at")


def _validate_new_operation(operation: NewAgentRunOperation) -> tuple[str, str | None]:
    if not all(
        isinstance(value, UUID)
        for value in (operation.id, operation.household_id, operation.run_id, operation.stage_id)
    ):
        raise TypeError("operation ownership ids must be UUID values")
    kind = AgentOperationKind(operation.kind)
    if operation.logical_root_operation_id is not None and not isinstance(
        operation.logical_root_operation_id, UUID
    ):
        raise TypeError("logical_root_operation_id must be UUID or None")
    if operation.provider_id is not None and not operation.provider_id.strip():
        raise ValueError("provider_id must not be blank")
    if kind in _PROVIDER_BOUND_OPERATION_KINDS:
        if operation.provider_id is None:
            raise ValueError("provider-bound operation requires provider_id")
    elif operation.provider_id is not None:
        raise ValueError("provider-neutral operation cannot have provider_id")
    if type(operation.consumes_logical_unit) is not bool:
        raise TypeError("consumes_logical_unit must be bool")
    if kind in _LOGICAL_ROOT_OPERATION_KINDS:
        if not operation.consumes_logical_unit or operation.logical_root_operation_id is not None:
            raise AgentOperationConflict("agent_logical_operation_shape_invalid")
    elif kind is AgentOperationKind.EXACT_POLL:
        if operation.consumes_logical_unit:
            raise AgentOperationConflict("agent_logical_operation_shape_invalid")
    elif kind in _INDEPENDENT_OPERATION_KINDS and (
        operation.consumes_logical_unit or operation.logical_root_operation_id is not None
    ):
        raise AgentOperationConflict("agent_logical_operation_shape_invalid")
    if type(operation.max_attempts) is not int or operation.max_attempts <= 0:
        raise ValueError("max_attempts must be a positive integer")
    _validate_fingerprint(operation.operation_fingerprint, "operation_fingerprint")
    _validate_fingerprint(
        operation.logical_operation_fingerprint,
        "logical_operation_fingerprint",
    )
    _require_aware(operation.created_at, "created_at")
    if (
        kind is AgentOperationKind.SUGGEST_DISCOVERY
        and "seed_limit" not in operation.immutable_input
    ):
        raise ValueError("suggest discovery operation requires seed_limit")
    immutable_input_json = canonical_operation_input_json(operation.immutable_input)
    private_continuation_json = (
        _canonical_private_continuation_json(operation.private_continuation)
        if operation.private_continuation is not None
        else None
    )
    return immutable_input_json, private_continuation_json


def _validate_fingerprint(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 fingerprint")


def _require_materialization_match(
    existing: AgentRunOperationRecord,
    requested: NewAgentRunOperation,
    *,
    existing_private_continuation_json: str | None,
    requested_private_continuation_json: str | None,
) -> None:
    conflict_code = _materialization_conflict_code(
        existing,
        requested,
        existing_private_continuation_json=existing_private_continuation_json,
        requested_private_continuation_json=requested_private_continuation_json,
    )
    if conflict_code is not None:
        raise AgentOperationConflict(conflict_code)


def _materialization_conflict_code(
    existing: AgentRunOperationRecord,
    requested: NewAgentRunOperation,
    *,
    existing_private_continuation_json: str | None,
    requested_private_continuation_json: str | None,
) -> str | None:
    if (
        existing.household_id != requested.household_id
        or existing.run_id != requested.run_id
        or existing.stage_id != requested.stage_id
        or existing.provider_id != requested.provider_id
        or existing.kind is not AgentOperationKind(requested.kind)
        or existing.logical_operation_fingerprint != requested.logical_operation_fingerprint
        or existing.logical_root_operation_id != requested.logical_root_operation_id
        or existing.consumes_logical_unit is not requested.consumes_logical_unit
        or canonical_operation_input_json(existing.immutable_input)
        != canonical_operation_input_json(requested.immutable_input)
        or existing.max_attempts != requested.max_attempts
    ):
        return "agent_operation_fingerprint_conflict"
    if existing_private_continuation_json != requested_private_continuation_json:
        return "agent_operation_private_continuation_conflict"
    return None


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _logical_root_matches_child(
    root: AgentRunOperationRecord,
    child: NewAgentRunOperation,
) -> bool:
    return (
        root.kind is AgentOperationKind.EXACT_START
        and AgentOperationKind(child.kind) is AgentOperationKind.EXACT_POLL
        and root.household_id == child.household_id
        and root.run_id == child.run_id
        and root.stage_id == child.stage_id
        and root.provider_id == child.provider_id
        and root.logical_operation_fingerprint == child.logical_operation_fingerprint
        and root.id == child.logical_root_operation_id
    )


def _stage_record(row: RowMapping) -> AgentPlanStageRecord:
    return AgentPlanStageRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        kind=AgentPlanStageKind(str(row["stage_kind"])),
        status=AgentStageStatus(str(row["status"])),
        created_at=_aware_datetime(row["created_at"]),
        updated_at=_aware_datetime(row["updated_at"]),
    )


def _operation_record(row: RowMapping) -> AgentRunOperationRecord:
    lease_expires_at = row["lease_expires_at"]
    next_retry_at = row["next_retry_at"]
    result_type = row["result_type"]
    result_id = row["result_id"]
    completed_at = row["completed_at"]
    return AgentRunOperationRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        stage_id=UUID(str(row["stage_id"])),
        provider_id=str(row["provider_id"]) if row["provider_id"] is not None else None,
        kind=AgentOperationKind(str(row["operation_kind"])),
        operation_fingerprint=str(row["operation_fingerprint"]),
        logical_operation_fingerprint=str(row["logical_operation_fingerprint"]),
        logical_root_operation_id=(
            UUID(str(row["logical_root_operation_id"]))
            if row["logical_root_operation_id"] is not None
            else None
        ),
        handoff_predecessor_operation_id=(
            UUID(str(row["handoff_predecessor_operation_id"]))
            if row["handoff_predecessor_operation_id"] is not None
            else None
        ),
        consumes_logical_unit=bool(row["consumes_logical_unit"]),
        immutable_input=_json_object(str(row["immutable_input_json"])),
        status=AgentOperationStatus(str(row["status"])),
        lease_owner=str(row["lease_owner"]) if row["lease_owner"] is not None else None,
        lease_expires_at=(
            _aware_datetime(lease_expires_at) if lease_expires_at is not None else None
        ),
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        next_retry_at=_aware_datetime(next_retry_at) if next_retry_at is not None else None,
        http_attempts_consumed=int(row["http_attempts_consumed"]),
        result_type=(
            AgentOperationResultType(str(result_type)) if result_type is not None else None
        ),
        result_id=UUID(str(result_id)) if result_id is not None else None,
        error_code=str(row["error_code"]) if row["error_code"] is not None else None,
        created_at=_aware_datetime(row["created_at"]),
        updated_at=_aware_datetime(row["updated_at"]),
        completed_at=_aware_datetime(completed_at) if completed_at is not None else None,
    )


def _private_operation_lease(row: RowMapping) -> ServerPrivateOperationLease:
    raw_continuation = row["private_continuation_json"]
    return ServerPrivateOperationLease(
        operation=_operation_record(row),
        private_continuation=(
            _json_object(str(raw_continuation)) if raw_continuation is not None else None
        ),
    )


def _operation_claim_eligibility(now: datetime) -> Any:
    status_eligible = or_(
        agent_run_operations_table.c.status == AgentOperationStatus.PENDING.value,
        (
            (agent_run_operations_table.c.status == AgentOperationStatus.RETRY_WAIT.value)
            & (agent_run_operations_table.c.next_retry_at <= now)
        ),
        (
            (agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            & (agent_run_operations_table.c.lease_expires_at <= now)
        ),
    )
    handoff_eligible = or_(
        agent_run_operations_table.c.operation_kind != AgentOperationKind.EXACT_POLL.value,
        agent_run_operations_table.c.handoff_predecessor_operation_id.is_not(None),
    )
    return status_eligible & handoff_eligible


def _run_state_allows_io(row: Mapping[Any, Any], now: datetime) -> bool:
    status, created_at, deadline_at = _run_execution_values(row)
    return status in {"queued", "running"} and created_at <= now < deadline_at


def _inactive_run_error(row: Mapping[Any, Any], now: datetime) -> str | None:
    status, _created_at, deadline_at = _run_execution_values(row)
    if status in {"cancel_requested", "cancelled"}:
        return "agent_run_cancelled"
    if now >= deadline_at:
        return "agent_run_deadline_exceeded"
    if status in _TERMINAL_RUN_STATUSES:
        return "agent_run_terminal"
    return None


def _run_execution_values(row: Mapping[Any, Any]) -> tuple[str, datetime, datetime]:
    prefixed = "run_status" in row
    status_key = "run_status" if prefixed else "status"
    created_key = "run_created_at" if prefixed else "created_at"
    deadline_key = "run_deadline_at" if prefixed else "deadline_at"
    return (
        str(row[status_key]),
        _aware_datetime(cast(datetime, row[created_key])),
        _aware_datetime(cast(datetime, row[deadline_key])),
    )


def _validate_operation_completion(worker_id: str, code: str, now: datetime) -> None:
    _require_aware(now, "now")
    if not worker_id.strip():
        raise ValueError("worker_id must not be blank")
    if not code.strip():
        raise ValueError("operation code must not be blank")


def _scope_snapshot_record(row: RowMapping) -> AgentRunScopeSnapshotRecord:
    return AgentRunScopeSnapshotRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        fingerprint=str(row["fingerprint"]),
        snapshot=_json_object(str(row["snapshot_json"])),
        created_at=_aware_datetime(row["created_at"]),
    )


def _circuit_record(row: RowMapping) -> AgentCircuitStateRecord:
    opened_at = row["opened_at"]
    cooldown_until = row["cooldown_until"]
    probe_expires_at = row["half_open_probe_expires_at"]
    return AgentCircuitStateRecord(
        provider_id=str(row["provider_id"]),
        state=AgentCircuitState(str(row["state"])),
        consecutive_transient_failures=int(row["consecutive_transient_failures"]),
        opened_at=_aware_datetime(opened_at) if opened_at is not None else None,
        cooldown_until=(_aware_datetime(cooldown_until) if cooldown_until is not None else None),
        half_open_probe_operation_id=(
            UUID(str(row["half_open_probe_operation_id"]))
            if row["half_open_probe_operation_id"] is not None
            else None
        ),
        half_open_probe_attempt_number=(
            int(row["half_open_probe_attempt_number"])
            if row["half_open_probe_attempt_number"] is not None
            else None
        ),
        half_open_probe_expires_at=(
            _aware_datetime(probe_expires_at) if probe_expires_at is not None else None
        ),
        generation=int(row["generation"]),
        version=int(row["version"]),
        updated_at=_aware_datetime(row["updated_at"]),
    )


def _validate_evidence_ownership(
    evidence_id: UUID,
    household_id: UUID,
    run_id: UUID,
    stage_id: UUID | None,
) -> None:
    values: tuple[UUID, ...] = (evidence_id, household_id, run_id)
    if stage_id is not None:
        values = (*values, stage_id)
    if not all(isinstance(value, UUID) for value in values):
        raise TypeError("evidence ownership ids must be UUID values")


def _validate_evidence_times(observed_at: datetime, created_at: datetime) -> None:
    _require_aware(observed_at, "observed_at")
    _require_aware(created_at, "created_at")
    if created_at < observed_at:
        raise ValueError("created_at cannot be before observed_at")


def _validate_money_fields(amount_minor: int | None, currency: str | None) -> None:
    if amount_minor is None:
        if currency is not None:
            raise ValueError("currency requires amount_minor")
        return
    if type(amount_minor) is not int or amount_minor < 0 or amount_minor > MAX_MONEY_MINOR_UNITS:
        raise ValueError("amount_minor must fit the non-negative persistence range or be None")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be an uppercase ISO code")


def _validate_passengers_and_basis(passengers: int, basis: PriceBasis) -> None:
    if type(passengers) is not int or passengers <= 0:
        raise ValueError("passengers must be a positive integer")
    PriceBasis(basis)


def _validate_provider_id(provider_id: str) -> None:
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ValueError("provider_id must not be blank")


def _validate_risk_statuses(
    protection_status: ProtectionStatus,
    baggage_status: BaggageEvidenceStatus | None,
    transfer_status: TransferEvidenceStatus | None,
    visa_status: VisaEvidenceStatus | None,
) -> None:
    ProtectionStatus(protection_status)
    _optional_enum_value(baggage_status, BaggageEvidenceStatus)
    _optional_enum_value(transfer_status, TransferEvidenceStatus)
    _optional_enum_value(visa_status, VisaEvidenceStatus)


def _validate_uuid_references(
    values: tuple[UUID, ...],
    field_name: str,
    *,
    allow_empty: bool,
) -> None:
    if isinstance(values, (str, bytes, bytearray)):
        raise TypeError(f"{field_name} must be an ordered UUID collection")
    normalized = tuple(values)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if not all(isinstance(value, UUID) for value in normalized):
        raise TypeError(f"{field_name} must contain UUID values")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must contain distinct values")


def _validate_discovery_signal(signal: NewAgentDiscoverySignal) -> str:
    _validate_evidence_ownership(
        signal.id,
        signal.household_id,
        signal.run_id,
        signal.stage_id,
    )
    _validate_provider_id(signal.provider_id)
    if not isinstance(signal.origin, str) or not re.fullmatch(r"[A-Z]{3}", signal.origin):
        raise ValueError("origin must be an uppercase IATA code")
    if not isinstance(signal.destination, str) or not re.fullmatch(r"[A-Z]{3}", signal.destination):
        raise ValueError("destination must be an uppercase IATA code")
    if type(signal.departure_date) is not date:
        raise TypeError("departure_date must be a date")
    if signal.return_date is not None:
        if type(signal.return_date) is not date:
            raise TypeError("return_date must be a date or None")
        if signal.return_date < signal.departure_date:
            raise ValueError("return_date cannot be before departure_date")
    _validate_money_fields(signal.amount_minor, signal.currency)
    _validate_passengers_and_basis(signal.passengers, signal.passenger_basis)
    DiscoverySource(signal.source_kind)
    Freshness(signal.freshness)
    _validate_evidence_times(signal.observed_at, signal.created_at)
    _validate_fingerprint(signal.fingerprint, "fingerprint")
    return _canonical_discovery_evidence_json(signal.signal_evidence)


def _validate_confirmed_evidence(evidence: NewAgentConfirmedOfferEvidence) -> str:
    _validate_evidence_ownership(
        evidence.id,
        evidence.household_id,
        evidence.run_id,
        evidence.stage_id,
    )
    _validate_provider_id(evidence.provider_id)
    if not isinstance(evidence.source, str) or not evidence.source.strip():
        raise ValueError("source must not be blank")
    Freshness(evidence.freshness)
    _validate_passengers_and_basis(evidence.passengers, evidence.passenger_basis)
    _validate_money_fields(evidence.amount_minor, evidence.currency)
    _validate_risk_statuses(
        evidence.protection_status,
        evidence.baggage_status,
        evidence.transfer_status,
        evidence.visa_status,
    )
    _validate_evidence_times(evidence.observed_at, evidence.created_at)
    _validate_fingerprint(evidence.fingerprint, "fingerprint")
    return _canonical_confirmed_itinerary_json(evidence.itinerary_evidence)


def _validate_booking_action_descriptor(
    descriptor: NewAgentBookingActionDescriptor,
) -> str:
    _validate_evidence_ownership(
        descriptor.id,
        descriptor.household_id,
        descriptor.run_id,
        None,
    )
    if not isinstance(descriptor.confirmed_evidence_id, UUID):
        raise TypeError("confirmed_evidence_id must be UUID")
    _validate_provider_id(descriptor.provider_id)
    _require_aware(descriptor.created_at, "created_at")
    _require_aware(descriptor.expires_at, "expires_at")
    if descriptor.expires_at <= descriptor.created_at:
        raise ValueError("booking descriptor expiry must follow creation")
    _validate_fingerprint(descriptor.fingerprint, "fingerprint")
    payload = descriptor.private_descriptor
    if not isinstance(payload, Mapping) or set(payload) != {
        "provider_id",
        "search_id",
        "proposal_id",
        "results_url",
    }:
        raise ValueError("booking descriptor fields are invalid")
    if payload.get("provider_id") != descriptor.provider_id:
        raise ValueError("booking descriptor provider is inconsistent")
    for key in ("search_id", "proposal_id", "results_url"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError("booking descriptor value is invalid")
    results_url = cast(str, payload["results_url"])
    if (
        "://" in results_url
        or "/" in results_url
        or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", results_url)
    ):
        raise ValueError("booking descriptor results host is invalid")
    return json.dumps(
        dict(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _booking_action_descriptor_matches(
    existing: AgentBookingActionDescriptorRecord,
    candidate: NewAgentBookingActionDescriptor,
) -> bool:
    return (
        existing.id == candidate.id
        and existing.household_id == candidate.household_id
        and existing.run_id == candidate.run_id
        and existing.confirmed_evidence_id == candidate.confirmed_evidence_id
        and existing.provider_id == candidate.provider_id
        and existing.private_descriptor == candidate.private_descriptor
        and existing.fingerprint == candidate.fingerprint
        and existing.created_at == _utc_datetime(candidate.created_at)
        and existing.expires_at == _utc_datetime(candidate.expires_at)
    )


def _validate_composed_candidate(candidate: NewAgentComposedRouteCandidate) -> str:
    _validate_evidence_ownership(
        candidate.id,
        candidate.household_id,
        candidate.run_id,
        candidate.stage_id,
    )
    _validate_uuid_references(
        candidate.component_evidence_ids,
        "component_evidence_ids",
        allow_empty=False,
    )
    _validate_passengers_and_basis(candidate.passengers, candidate.passenger_basis)
    _validate_money_fields(candidate.amount_minor, candidate.currency)
    _validate_risk_statuses(
        candidate.protection_status,
        candidate.baggage_status,
        candidate.transfer_status,
        candidate.visa_status,
    )
    _validate_evidence_times(candidate.observed_at, candidate.created_at)
    _validate_fingerprint(candidate.fingerprint, "fingerprint")
    return _canonical_composed_itinerary_json(candidate.itinerary_evidence)


def _validate_composed_component_consistency(
    candidate: NewAgentComposedRouteCandidate,
    components: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> None:
    try:
        _validate_composed_component_facts(candidate, components)
    except AgentEvidenceError:
        raise
    except (KeyError, TypeError, ValueError, OverflowError):
        raise AgentEvidenceError("agent_composed_component_mismatch") from None


@dataclass(frozen=True, slots=True)
class _StoredCompositionSegment:
    segment_ref: str
    origin: str
    destination: str
    depart_at_utc: datetime | None
    arrive_at_utc: datetime | None


@dataclass(frozen=True, slots=True)
class _StoredCompositionComponent:
    id: UUID
    origin: str
    destination: str
    departure_date: date
    passenger_mix: tuple[int, int, int]
    price_basis: PriceBasis
    amount_minor: int
    currency: str
    segments: tuple[_StoredCompositionSegment, ...]


@dataclass(frozen=True, slots=True)
class _StoredCompositionLeg:
    ordinal: int
    origin: str
    destination: str
    departure_date: date
    component_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class _StoredCompositionMoney:
    minor_units: int
    currency: str


def _validate_composed_component_facts(
    candidate: NewAgentComposedRouteCandidate,
    components: Sequence[AgentConfirmedOfferEvidenceRecord],
) -> None:
    if tuple(component.id for component in components) != candidate.component_evidence_ids:
        raise AgentEvidenceError("agent_composed_component_mismatch")
    if candidate.observed_at != min(component.observed_at for component in components):
        raise AgentEvidenceError("agent_composed_component_mismatch")

    stored_components = tuple(_stored_composition_component(component) for component in components)
    expected_mix = stored_components[0].passenger_mix
    expected_basis = stored_components[0].price_basis
    if (
        any(component.passenger_mix != expected_mix for component in stored_components)
        or any(component.price_basis is not expected_basis for component in stored_components)
        or sum(expected_mix) != candidate.passengers
        or PriceBasis(candidate.passenger_basis) is not expected_basis
    ):
        raise AgentEvidenceError("agent_composed_component_mismatch")

    facts = _composition_mapping(candidate.itinerary_evidence, "composed itinerary")
    if _composition_text(facts["composition_version"], "composition version") != (
        "route-composer-v1"
    ):
        raise AgentEvidenceError("agent_composed_component_mismatch")

    expected_component_ids = candidate.component_evidence_ids
    raw_component_ids = tuple(
        _composition_uuid(value, "component id")
        for value in _composition_sequence(facts["components"], "components")
    )
    if raw_component_ids != expected_component_ids:
        raise AgentEvidenceError("agent_composed_component_mismatch")

    expected_component_amounts = tuple(
        _StoredCompositionMoney(component.amount_minor, component.currency)
        for component in stored_components
    )
    component_amounts = tuple(
        _composition_money(value, "component amount")
        for value in _composition_sequence(facts["component_amounts"], "component amounts")
    )
    if component_amounts != expected_component_amounts:
        raise AgentEvidenceError("agent_composed_component_mismatch")

    passenger_mix = _composition_mapping(facts["passenger_mix"], "passenger mix")
    stored_mix = (
        _composition_non_negative_int(passenger_mix["adults"], "passenger adults"),
        _composition_non_negative_int(passenger_mix["children"], "passenger children"),
        _composition_non_negative_int(passenger_mix["infants"], "passenger infants"),
    )
    if stored_mix != expected_mix:
        raise AgentEvidenceError("agent_composed_component_mismatch")
    if PriceBasis(_composition_text(facts["price_basis"], "price basis")) is not expected_basis:
        raise AgentEvidenceError("agent_composed_component_mismatch")

    trip_shape = TripShape(_composition_text(facts["trip_shape"], "trip shape"))
    legs = tuple(
        _stored_composition_leg(value)
        for value in _composition_sequence(facts["ordered_legs"], "ordered legs")
    )
    _validate_composition_legs(trip_shape, legs, stored_components)

    component_by_id = {component.id: component for component in stored_components}
    expected_tickets: list[dict[str, object]] = []
    expected_connections: list[dict[str, object]] = []
    expected_unknown_costs: list[dict[str, object]] = []
    transfer_costs: list[_StoredCompositionMoney] = []
    ticket_index = 0
    for leg in legs:
        for component_id in leg.component_ids:
            component = component_by_id[component_id]
            expected_tickets.append(
                {
                    "ticket_index": ticket_index,
                    "leg_ordinal": leg.ordinal,
                    "component_evidence_id": str(component.id),
                    "segment_refs": [
                        f"{component.id}#{segment.segment_ref}" for segment in component.segments
                    ],
                }
            )
            ticket_index += 1
        for inbound_id, outbound_id in zip(
            leg.component_ids,
            leg.component_ids[1:],
            strict=False,
        ):
            inbound = component_by_id[inbound_id]
            outbound = component_by_id[outbound_id]
            connection = _validated_stored_connection(
                leg.ordinal,
                inbound,
                outbound,
                facts,
                len(expected_connections),
            )
            expected_connections.append(connection)
            transfer_cost = connection["transfer_cost"]
            if isinstance(transfer_cost, _StoredCompositionMoney):
                transfer_costs.append(transfer_cost)
            if connection["airport_change"] is True and transfer_cost is None:
                expected_unknown_costs.append(
                    {
                        "kind": UnknownCostKind.GROUND_TRANSFER.value,
                        "leg_ordinal": leg.ordinal,
                        "description": (
                            f"Ground transfer {connection['arrival_airport']}-"
                            f"{connection['departure_airport']}"
                        ),
                    }
                )

    _validate_composition_tickets(facts, expected_tickets)
    _validate_composition_connections(facts, expected_connections)

    target_currency = _composition_currency(facts["target_currency"], "target currency")
    priced_items = [*expected_component_amounts, *transfer_costs]
    currencies = {item.currency for item in priced_items}
    expected_reasons: tuple[str, ...]
    if currencies != {target_currency}:
        expected_status = PriceComparisonStatus.NON_COMPARABLE
        expected_total = None
        expected_unknown_costs.append(
            {
                "kind": UnknownCostKind.CURRENCY_CONVERSION.value,
                "leg_ordinal": legs[0].ordinal,
                "description": "Fresh deterministic FX is unavailable",
            }
        )
        expected_reasons = ("confirmed_components", "mixed_currency_without_fx")
    else:
        total_minor = sum(item.minor_units for item in priced_items)
        if total_minor > MAX_MONEY_MINOR_UNITS:
            raise AgentEvidenceError("agent_composed_component_mismatch")
        expected_total = _StoredCompositionMoney(total_minor, target_currency)
        if expected_unknown_costs:
            expected_status = PriceComparisonStatus.MANDATORY_COST_UNKNOWN
            expected_reasons = ("confirmed_components", "mandatory_cost_unknown")
        else:
            expected_status = PriceComparisonStatus.FULLY_PRICED
            expected_reasons = ("confirmed_components",)

    actual_total = (
        None
        if facts["known_total"] is None
        else _composition_money(facts["known_total"], "known total")
    )
    candidate_total = (
        None
        if candidate.amount_minor is None
        else _StoredCompositionMoney(
            candidate.amount_minor,
            _composition_currency(candidate.currency, "candidate currency"),
        )
    )
    if actual_total != expected_total or candidate_total != expected_total:
        raise AgentEvidenceError("agent_composed_component_mismatch")
    if (
        PriceComparisonStatus(
            _composition_text(facts["price_comparison_status"], "price comparison status")
        )
        is not expected_status
    ):
        raise AgentEvidenceError("agent_composed_component_mismatch")

    _validate_composition_unknown_costs(facts, expected_unknown_costs)
    expected_protection = (
        ProtectionStatus.SELF_TRANSFER if expected_connections else ProtectionStatus.UNKNOWN
    )
    if (
        candidate.protection_status is not expected_protection
        or ProtectionStatus(_composition_text(facts["protection_status"], "protection status"))
        is not expected_protection
    ):
        raise AgentEvidenceError("agent_composed_component_mismatch")
    ranking_reasons = tuple(
        _composition_text(value, "ranking reason")
        for value in _composition_sequence(facts["ranking_reasons"], "ranking reasons")
    )
    if ranking_reasons != expected_reasons:
        raise AgentEvidenceError("agent_composed_component_mismatch")


def _stored_composition_component(
    record: AgentConfirmedOfferEvidenceRecord,
) -> _StoredCompositionComponent:
    if record.amount_minor is None or record.currency is None:
        raise ValueError("composition components require typed totals")
    itinerary = _composition_mapping(record.itinerary_evidence, "confirmed itinerary")
    origin = _composition_iata(itinerary["origin"], "component origin")
    destination = _composition_iata(itinerary["destination"], "component destination")
    departure_date = _composition_date(itinerary["departure_date"], "component departure date")
    if itinerary.get("return_date") is not None:
        raise ValueError("composition components must be one-way evidence")
    passenger_mix = _composition_mapping(itinerary["passenger_mix"], "component passenger mix")
    mix = (
        _composition_non_negative_int(passenger_mix["adults"], "component adults"),
        _composition_non_negative_int(passenger_mix["children"], "component children"),
        _composition_non_negative_int(passenger_mix["infants"], "component infants"),
    )
    if sum(mix) != record.passengers:
        raise ValueError("component passenger mix mismatch")
    basis = PriceBasis(_composition_text(itinerary["price_basis"], "component price basis"))
    if basis is not record.passenger_basis:
        raise ValueError("component price basis mismatch")
    segments = tuple(
        _stored_composition_segment(value)
        for value in _composition_sequence(itinerary["segments"], "component segments")
    )
    if not segments or len({segment.segment_ref for segment in segments}) != len(segments):
        raise ValueError("composition component segments are invalid")
    if segments[0].origin != origin or segments[-1].destination != destination:
        raise ValueError("composition component route mismatch")
    if any(previous.destination != current.origin for previous, current in pairwise(segments)):
        raise ValueError("composition component segments are discontinuous")
    return _StoredCompositionComponent(
        id=record.id,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        passenger_mix=mix,
        price_basis=basis,
        amount_minor=record.amount_minor,
        currency=_composition_currency(record.currency, "component currency"),
        segments=segments,
    )


def _stored_composition_segment(value: object) -> _StoredCompositionSegment:
    segment = _composition_mapping(value, "component segment")
    depart_at_utc = _composition_optional_datetime(
        segment.get("depart_at_utc"),
        "segment departure UTC",
    )
    arrive_at_utc = _composition_optional_datetime(
        segment.get("arrive_at_utc"),
        "segment arrival UTC",
    )
    if (depart_at_utc is None) != (arrive_at_utc is None):
        raise ValueError("segment UTC instants must be complete")
    if depart_at_utc is not None and arrive_at_utc is not None and arrive_at_utc < depart_at_utc:
        raise ValueError("segment arrival cannot precede departure")
    return _StoredCompositionSegment(
        segment_ref=_composition_text(segment["segment_ref"], "segment ref"),
        origin=_composition_iata(segment["origin"], "segment origin"),
        destination=_composition_iata(segment["destination"], "segment destination"),
        depart_at_utc=depart_at_utc,
        arrive_at_utc=arrive_at_utc,
    )


def _stored_composition_leg(value: object) -> _StoredCompositionLeg:
    leg = _composition_mapping(value, "ordered leg")
    return _StoredCompositionLeg(
        ordinal=_composition_non_negative_int(leg["ordinal"], "leg ordinal"),
        origin=_composition_iata(leg["origin"], "leg origin"),
        destination=_composition_iata(leg["destination"], "leg destination"),
        departure_date=_composition_date(leg["departure_date"], "leg departure date"),
        component_ids=tuple(
            _composition_uuid(component_id, "leg component id")
            for component_id in _composition_sequence(leg["components"], "leg components")
        ),
    )


def _validate_composition_legs(
    trip_shape: TripShape,
    legs: tuple[_StoredCompositionLeg, ...],
    components: tuple[_StoredCompositionComponent, ...],
) -> None:
    required_legs = {
        TripShape.ONE_WAY: 1,
        TripShape.ROUND_TRIP: 2,
        TripShape.OPEN_JAW: 2,
    }.get(trip_shape)
    if (
        not legs
        or (required_legs is not None and len(legs) != required_legs)
        or (trip_shape is TripShape.MULTI_CITY and len(legs) < 2)
        or tuple(leg.ordinal for leg in legs) != tuple(range(len(legs)))
        or any(not leg.component_ids for leg in legs)
    ):
        raise AgentEvidenceError("agent_composed_component_mismatch")
    flattened = tuple(component_id for leg in legs for component_id in leg.component_ids)
    if flattened != tuple(component.id for component in components):
        raise AgentEvidenceError("agent_composed_component_mismatch")
    component_by_id = {component.id: component for component in components}
    for leg in legs:
        first = component_by_id[leg.component_ids[0]]
        last = component_by_id[leg.component_ids[-1]]
        if (
            leg.origin != first.origin
            or leg.destination != last.destination
            or leg.departure_date != first.departure_date
        ):
            raise AgentEvidenceError("agent_composed_component_mismatch")


def _validated_stored_connection(
    leg_ordinal: int,
    inbound: _StoredCompositionComponent,
    outbound: _StoredCompositionComponent,
    facts: Mapping[str, object],
    connection_index: int,
) -> dict[str, object]:
    connections = _composition_sequence(facts["connections"], "connections")
    if connection_index >= len(connections):
        raise ValueError("missing composed connection")
    raw = _composition_mapping(connections[connection_index], "connection")
    arrival_segment = inbound.segments[-1]
    departure_segment = outbound.segments[0]
    if arrival_segment.arrive_at_utc is None or departure_segment.depart_at_utc is None:
        raise ValueError("connection UTC instants are required")
    layover_seconds = int(
        (departure_segment.depart_at_utc - arrival_segment.arrive_at_utc).total_seconds()
    )
    airport_change = arrival_segment.destination != departure_segment.origin
    required_minimum_seconds = 21_600 if airport_change else 10_800
    if layover_seconds < required_minimum_seconds or layover_seconds > 64_800:
        raise ValueError("connection is outside composer policy")
    provenance = raw.get("provenance")
    if airport_change:
        provenance = _composition_text(provenance, "airport change provenance")
    elif provenance is not None:
        raise ValueError("same-airport connection cannot have provenance")
    transfer_cost = (
        None
        if raw.get("transfer_cost") is None
        else _composition_money(raw["transfer_cost"], "connection transfer cost")
    )
    if not airport_change and transfer_cost is not None:
        raise ValueError("same-airport connection cannot have transfer cost")
    expected = {
        "leg_ordinal": leg_ordinal,
        "inbound_component_id": str(inbound.id),
        "outbound_component_id": str(outbound.id),
        "arrival_airport": arrival_segment.destination,
        "departure_airport": departure_segment.origin,
        "layover_seconds": layover_seconds,
        "required_minimum_seconds": required_minimum_seconds,
        "airport_change": airport_change,
        "provenance": provenance,
        "transfer_cost": transfer_cost,
    }
    if (
        _composition_non_negative_int(raw["leg_ordinal"], "connection leg ordinal")
        != expected["leg_ordinal"]
        or str(_composition_uuid(raw["inbound_component_id"], "inbound component id"))
        != expected["inbound_component_id"]
        or str(_composition_uuid(raw["outbound_component_id"], "outbound component id"))
        != expected["outbound_component_id"]
        or _composition_iata(raw["arrival_airport"], "connection arrival airport")
        != expected["arrival_airport"]
        or _composition_iata(raw["departure_airport"], "connection departure airport")
        != expected["departure_airport"]
        or _composition_non_negative_int(raw["layover_seconds"], "layover seconds")
        != expected["layover_seconds"]
        or _composition_non_negative_int(
            raw["required_minimum_seconds"],
            "required minimum seconds",
        )
        != expected["required_minimum_seconds"]
        or _composition_bool(raw["airport_change"], "airport change") != expected["airport_change"]
    ):
        raise ValueError("composed connection mismatch")
    return expected


def _validate_composition_tickets(
    facts: Mapping[str, object],
    expected: Sequence[Mapping[str, object]],
) -> None:
    tickets = _composition_sequence(facts["tickets"], "tickets")
    if len(tickets) != len(expected):
        raise AgentEvidenceError("agent_composed_component_mismatch")
    for raw_value, expected_ticket in zip(tickets, expected, strict=True):
        raw = _composition_mapping(raw_value, "ticket")
        normalized = {
            "ticket_index": _composition_non_negative_int(
                raw["ticket_index"],
                "ticket index",
            ),
            "leg_ordinal": _composition_non_negative_int(
                raw["leg_ordinal"],
                "ticket leg ordinal",
            ),
            "component_evidence_id": str(
                _composition_uuid(raw["component_evidence_id"], "ticket component id")
            ),
            "segment_refs": [
                _composition_text(value, "ticket segment ref")
                for value in _composition_sequence(raw["segment_refs"], "ticket segment refs")
            ],
        }
        if normalized != expected_ticket:
            raise AgentEvidenceError("agent_composed_component_mismatch")


def _validate_composition_connections(
    facts: Mapping[str, object],
    expected: Sequence[Mapping[str, object]],
) -> None:
    connections = _composition_sequence(facts["connections"], "connections")
    if len(connections) != len(expected):
        raise AgentEvidenceError("agent_composed_component_mismatch")
    for raw_value, expected_connection in zip(connections, expected, strict=True):
        raw = _composition_mapping(raw_value, "connection")
        actual_transfer = (
            None
            if raw.get("transfer_cost") is None
            else _composition_money(raw["transfer_cost"], "connection transfer cost")
        )
        if (
            raw.get("provenance") != expected_connection["provenance"]
            or actual_transfer != expected_connection["transfer_cost"]
        ):
            raise AgentEvidenceError("agent_composed_component_mismatch")


def _validate_composition_unknown_costs(
    facts: Mapping[str, object],
    expected: Sequence[Mapping[str, object]],
) -> None:
    unknown_costs = _composition_sequence(facts["unknown_costs"], "unknown costs")
    normalized: list[dict[str, object]] = []
    for raw_value in unknown_costs:
        raw = _composition_mapping(raw_value, "unknown cost")
        normalized.append(
            {
                "kind": UnknownCostKind(_composition_text(raw["kind"], "unknown cost kind")).value,
                "leg_ordinal": _composition_non_negative_int(
                    raw["leg_ordinal"],
                    "unknown cost leg ordinal",
                ),
                "description": _composition_text(
                    raw["description"],
                    "unknown cost description",
                ),
            }
        )
    if normalized != list(expected):
        raise AgentEvidenceError("agent_composed_component_mismatch")


def _composition_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be an object")
    return value


def _composition_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an ordered collection")
    return value


def _composition_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _composition_iata(value: object, field_name: str) -> str:
    text = _composition_text(value, field_name)
    if not re.fullmatch(r"[A-Z0-9]{3}", text):
        raise ValueError(f"{field_name} must be a normalized IATA code")
    return text


def _composition_currency(value: object, field_name: str) -> str:
    text = _composition_text(value, field_name)
    if not re.fullmatch(r"[A-Z]{3}", text):
        raise ValueError(f"{field_name} must be an uppercase ISO code")
    return text


def _composition_non_negative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _composition_bool(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be bool")
    return value


def _composition_uuid(value: object, field_name: str) -> UUID:
    text = _composition_text(value, field_name)
    parsed = UUID(text)
    if str(parsed) != text:
        raise ValueError(f"{field_name} must be a canonical UUID")
    return parsed


def _composition_date(value: object, field_name: str) -> date:
    text = _composition_text(value, field_name)
    parsed = date.fromisoformat(text)
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name} must be a canonical ISO date")
    return parsed


def _composition_optional_datetime(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    text = _composition_text(value, field_name)
    parsed = datetime.fromisoformat(text)
    _require_aware(parsed, field_name)
    if parsed.isoformat() != text:
        raise ValueError(f"{field_name} must be a canonical ISO datetime")
    return parsed


def _composition_money(value: object, field_name: str) -> _StoredCompositionMoney:
    money = _composition_mapping(value, field_name)
    minor_units = _composition_non_negative_int(money["minor_units"], f"{field_name} amount")
    if minor_units > MAX_MONEY_MINOR_UNITS:
        raise ValueError(f"{field_name} amount is too large")
    return _StoredCompositionMoney(
        minor_units=minor_units,
        currency=_composition_currency(money["currency"], f"{field_name} currency"),
    )


def _validate_ranking_snapshot(snapshot: NewAgentRankingSnapshot) -> str:
    _validate_evidence_ownership(
        snapshot.id,
        snapshot.household_id,
        snapshot.run_id,
        None,
    )
    _validate_uuid_references(
        snapshot.confirmed_evidence_ids,
        "confirmed_evidence_ids",
        allow_empty=True,
    )
    _validate_uuid_references(
        snapshot.composed_candidate_ids,
        "composed_candidate_ids",
        allow_empty=True,
    )
    if not snapshot.confirmed_evidence_ids and not snapshot.composed_candidate_ids:
        raise ValueError("ranking snapshot requires at least one result reference")
    _require_aware(snapshot.created_at, "created_at")
    _validate_fingerprint(snapshot.fingerprint, "fingerprint")
    return _canonical_ranking_json(snapshot.ranking)


def _optional_enum_value(value: object, enum_type: type[StrEnum]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("enum evidence status must be a string enum")
    return enum_type(value).value


def _uuid_tuple_json(values: tuple[UUID, ...]) -> str:
    return json.dumps([str(value) for value in values], separators=(",", ":"))


def _json_uuid_tuple(raw: str) -> tuple[UUID, ...]:
    payload: object = json.loads(raw)
    if not isinstance(payload, list) or not all(isinstance(value, str) for value in payload):
        raise RuntimeError("stored evidence references must be a UUID string array")
    try:
        return tuple(UUID(value) for value in payload)
    except ValueError as error:
        raise RuntimeError("stored evidence reference is not a UUID") from error


def _discovery_signal_record(row: RowMapping) -> AgentDiscoverySignalRecord:
    currency = row["currency"]
    return_date = row["return_date"]
    return AgentDiscoverySignalRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        stage_id=UUID(str(row["stage_id"])),
        provider_id=str(row["provider_id"]),
        origin=str(row["origin"]),
        destination=str(row["destination"]),
        departure_date=cast(date, row["departure_date"]),
        return_date=cast(date, return_date) if return_date is not None else None,
        amount_minor=(int(row["amount_minor"]) if row["amount_minor"] is not None else None),
        currency=str(currency) if currency is not None else None,
        passengers=int(row["passengers"]),
        passenger_basis=PriceBasis(str(row["passenger_basis"])),
        source_kind=DiscoverySource(str(row["source_kind"])),
        freshness=Freshness(str(row["freshness"])),
        observed_at=_aware_datetime(row["observed_at"]),
        signal_evidence=_json_object(str(row["signal_evidence_json"])),
        fingerprint=str(row["fingerprint"]),
        created_at=_aware_datetime(row["created_at"]),
    )


def _confirmed_evidence_record(row: RowMapping) -> AgentConfirmedOfferEvidenceRecord:
    currency = row["currency"]
    return AgentConfirmedOfferEvidenceRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        stage_id=UUID(str(row["stage_id"])),
        provider_id=str(row["provider_id"]),
        source=str(row["source"]),
        observed_at=_aware_datetime(row["observed_at"]),
        freshness=Freshness(str(row["freshness"])),
        passengers=int(row["passengers"]),
        passenger_basis=PriceBasis(str(row["passenger_basis"])),
        amount_minor=(int(row["amount_minor"]) if row["amount_minor"] is not None else None),
        currency=str(currency) if currency is not None else None,
        itinerary_evidence=_json_object(str(row["itinerary_evidence_json"])),
        protection_status=ProtectionStatus(str(row["protection_status"])),
        baggage_status=_optional_baggage_status(row["baggage_status"]),
        transfer_status=_optional_transfer_status(row["transfer_status"]),
        visa_status=_optional_visa_status(row["visa_status"]),
        fingerprint=str(row["fingerprint"]),
        created_at=_aware_datetime(row["created_at"]),
    )


def _booking_action_descriptor_record(
    row: RowMapping,
) -> AgentBookingActionDescriptorRecord:
    return AgentBookingActionDescriptorRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        confirmed_evidence_id=UUID(str(row["confirmed_evidence_id"])),
        provider_id=str(row["provider_id"]),
        private_descriptor=_json_object(str(row["private_descriptor_json"])),
        fingerprint=str(row["fingerprint"]),
        created_at=_aware_datetime(row["created_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
    )


def _composed_candidate_record(row: RowMapping) -> AgentComposedRouteCandidateRecord:
    currency = row["currency"]
    return AgentComposedRouteCandidateRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        stage_id=UUID(str(row["stage_id"])),
        component_evidence_ids=_json_uuid_tuple(str(row["component_evidence_ids_json"])),
        observed_at=_aware_datetime(row["observed_at"]),
        passengers=int(row["passengers"]),
        passenger_basis=PriceBasis(str(row["passenger_basis"])),
        amount_minor=(int(row["amount_minor"]) if row["amount_minor"] is not None else None),
        currency=str(currency) if currency is not None else None,
        itinerary_evidence=_json_object(str(row["itinerary_evidence_json"])),
        protection_status=ProtectionStatus(str(row["protection_status"])),
        baggage_status=_optional_baggage_status(row["baggage_status"]),
        transfer_status=_optional_transfer_status(row["transfer_status"]),
        visa_status=_optional_visa_status(row["visa_status"]),
        fingerprint=str(row["fingerprint"]),
        created_at=_aware_datetime(row["created_at"]),
    )


def _ranking_snapshot_record(row: RowMapping) -> AgentRankingSnapshotRecord:
    return AgentRankingSnapshotRecord(
        id=UUID(str(row["id"])),
        household_id=UUID(str(row["household_id"])),
        run_id=UUID(str(row["run_id"])),
        confirmed_evidence_ids=_json_uuid_tuple(str(row["confirmed_evidence_ids_json"])),
        composed_candidate_ids=_json_uuid_tuple(str(row["composed_candidate_ids_json"])),
        ranking=_json_object(str(row["ranking_json"])),
        fingerprint=str(row["fingerprint"]),
        created_at=_aware_datetime(row["created_at"]),
    )


def _optional_baggage_status(value: object) -> BaggageEvidenceStatus | None:
    return BaggageEvidenceStatus(str(value)) if value is not None else None


def _optional_transfer_status(value: object) -> TransferEvidenceStatus | None:
    return TransferEvidenceStatus(str(value)) if value is not None else None


def _optional_visa_status(value: object) -> VisaEvidenceStatus | None:
    return VisaEvidenceStatus(str(value)) if value is not None else None
