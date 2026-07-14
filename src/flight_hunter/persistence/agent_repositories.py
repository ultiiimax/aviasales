from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import case, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.domain.agent_evidence import DiscoverySource, ProtectionStatus
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.models import (
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

    def __post_init__(self) -> None:
        status = AttemptReservationStatus(self.status)
        if status is AttemptReservationStatus.RATE_LIMITED:
            if self.retry_at is None:
                raise ValueError("rate_limited reservation requires retry_at")
            _require_aware(self.retry_at, "retry_at")
        elif self.retry_at is not None:
            raise ValueError("retry_at is only valid for rate_limited reservations")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class CircuitPermitResult:
    status: CircuitPermitStatus
    retry_at: datetime | None = None

    def __post_init__(self) -> None:
        status = CircuitPermitStatus(self.status)
        if status is CircuitPermitStatus.OPEN:
            if self.retry_at is None:
                raise ValueError("open circuit permit requires retry_at")
            _require_aware(self.retry_at, "retry_at")
        elif self.retry_at is not None:
            raise ValueError("retry_at is only valid for an open circuit permit")
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
    private_continuation: Mapping[str, object] | None
    max_attempts: int
    created_at: datetime


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
    private_continuation: Mapping[str, object] | None

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
    half_open_probe_owner: str | None
    half_open_probe_expires_at: datetime | None
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
    ) -> tuple[AgentPlanRunRecord, ...]:
        rows = (
            await self._session.execute(
                select(agent_plan_runs_table)
                .where(agent_plan_runs_table.c.household_id == str(household_id))
                .where(agent_plan_runs_table.c.plan_id == str(plan_id))
                .order_by(
                    agent_plan_runs_table.c.created_at.asc(),
                    agent_plan_runs_table.c.id.asc(),
                )
            )
        ).mappings()
        return tuple(_run_record(row) for row in rows)

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

    async def materialize_operation(
        self,
        operation: NewAgentRunOperation,
    ) -> AgentRunOperationRecord:
        immutable_input_json, private_continuation_json = _validate_new_operation(operation)
        await self._acquire_write_transaction()
        existing = await self._get_operation_by_fingerprint(
            operation.household_id,
            operation.run_id,
            operation.operation_fingerprint,
        )
        if existing is not None:
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
        logical_root = await self._get_logical_root(
            operation.household_id,
            operation.run_id,
            operation.logical_operation_fingerprint,
        )
        if operation.consumes_logical_unit:
            if logical_root is not None:
                if logical_root.operation_fingerprint == operation.operation_fingerprint:
                    return logical_root
                raise AgentOperationConflict("agent_logical_operation_exists")
        elif logical_root is None:
            raise AgentOperationConflict("agent_logical_operation_root_missing")

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
                        result_type=None,
                        result_id=None,
                        error_code=None,
                        created_at=_utc_datetime(operation.created_at),
                        updated_at=_utc_datetime(operation.created_at),
                        completed_at=None,
                    )
                )
        except IntegrityError:
            existing = await self._get_operation_by_fingerprint(
                operation.household_id,
                operation.run_id,
                operation.operation_fingerprint,
            )
            if existing is not None:
                return existing
            logical_root = await self._get_logical_root(
                operation.household_id,
                operation.run_id,
                operation.logical_operation_fingerprint,
            )
            if operation.consumes_logical_unit and logical_root is not None:
                raise AgentOperationConflict("agent_logical_operation_exists") from None
            raise

        stored = await self.get_operation(operation.household_id, operation.id)
        if stored is None:
            raise RuntimeError("created agent operation is missing")
        return stored

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
        if not await self._run_allows_io(household_id, run_id, normalized_now):
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
        result = await self._session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation_id))
            .where(agent_run_operations_table.c.household_id == str(household_id))
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at >= _utc_datetime(now))
            .values(
                status=AgentOperationStatus.SUCCEEDED.value,
                lease_owner=None,
                lease_expires_at=None,
                next_retry_at=None,
                result_type=normalized_result_type.value,
                result_id=str(result_id),
                error_code=None,
                updated_at=_utc_datetime(now),
                completed_at=_utc_datetime(now),
            )
        )
        await self._require_operation_transition(result, household_id, operation_id)
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
    ) -> AttemptReservationResult:
        _require_aware(now, "now")
        if type(provider_rpm) is not int or provider_rpm <= 0:
            raise ValueError("provider_rpm must be a positive integer")
        if not provider_id.strip() or not worker_id.strip():
            raise ValueError("provider_id and worker_id must not be blank")
        normalized_kind = AttemptKind(attempt_kind)
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        await self._require_reservable_operation(
            household_id,
            run_id,
            operation_id,
            provider_id,
            worker_id,
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
                .values(http_attempts_consumed=agent_plan_runs_table.c.http_attempts_consumed + 1)
            )
            if cast(CursorResult[Any], budget_result).rowcount != 1:
                return AttemptReservationResult(status=AttemptReservationStatus.BUDGET_EXHAUSTED)
            await self._session.execute(
                insert(agent_provider_http_attempts_table).values(
                    id=str(uuid4()),
                    household_id=str(household_id),
                    provider_id=provider_id,
                    run_id=str(run_id),
                    operation_id=str(operation_id),
                    attempt_kind=normalized_kind.value,
                    reserved_at=normalized_now,
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
                .values(
                    http_attempts_consumed=(
                        agent_run_operations_table.c.http_attempts_consumed + 1
                    ),
                    updated_at=normalized_now,
                )
            )
            if cast(CursorResult[Any], operation_result).rowcount != 1:
                raise AgentOperationConflict("agent_operation_not_found")
        return AttemptReservationResult(status=AttemptReservationStatus.RESERVED)

    async def append_scope_snapshot(
        self,
        snapshot: NewAgentRunScopeSnapshot,
    ) -> AgentRunScopeSnapshotRecord:
        _require_aware(snapshot.created_at, "created_at")
        _validate_fingerprint(snapshot.fingerprint, "fingerprint")
        snapshot_json = canonical_sanitized_json(snapshot.snapshot)
        await self._acquire_write_transaction()
        await self._require_run(snapshot.household_id, snapshot.run_id)
        existing = await self._get_scope_snapshot_by_fingerprint(
            snapshot.household_id,
            snapshot.run_id,
            snapshot.fingerprint,
        )
        if existing is not None:
            return existing
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
            existing = await self._get_scope_snapshot_by_fingerprint(
                snapshot.household_id,
                snapshot.run_id,
                snapshot.fingerprint,
            )
            if existing is not None:
                return existing
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
        await self._ensure_circuit_row(provider_id, normalized_now)
        state = await self._locked_circuit_state(provider_id)
        if state.state is AgentCircuitState.CLOSED:
            return CircuitPermitResult(CircuitPermitStatus.ALLOWED)
        if state.state is AgentCircuitState.OPEN:
            assert state.cooldown_until is not None
            if normalized_now < state.cooldown_until:
                return CircuitPermitResult(
                    CircuitPermitStatus.OPEN,
                    retry_at=state.cooldown_until,
                )
        elif state.state is AgentCircuitState.HALF_OPEN:
            assert state.half_open_probe_expires_at is not None
            if (
                state.half_open_probe_owner == worker_id
                and normalized_now < state.half_open_probe_expires_at
            ):
                return CircuitPermitResult(CircuitPermitStatus.HALF_OPEN_PROBE)
            if normalized_now < state.half_open_probe_expires_at:
                return CircuitPermitResult(
                    CircuitPermitStatus.OPEN,
                    retry_at=state.half_open_probe_expires_at,
                )

        probe_expires_at = normalized_now + timedelta(seconds=probe_lease_seconds)
        result = await self._session.execute(
            update(agent_provider_circuit_state_table)
            .where(agent_provider_circuit_state_table.c.provider_id == provider_id)
            .where(agent_provider_circuit_state_table.c.version == state.version)
            .values(
                state=AgentCircuitState.HALF_OPEN.value,
                half_open_probe_owner=worker_id,
                half_open_probe_expires_at=probe_expires_at,
                version=agent_provider_circuit_state_table.c.version + 1,
                updated_at=normalized_now,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            refreshed = await self._locked_circuit_state(provider_id)
            retry_at = refreshed.half_open_probe_expires_at or refreshed.cooldown_until
            if retry_at is None:
                retry_at = normalized_now + timedelta(seconds=probe_lease_seconds)
            return CircuitPermitResult(CircuitPermitStatus.OPEN, retry_at=retry_at)
        return CircuitPermitResult(CircuitPermitStatus.HALF_OPEN_PROBE)

    async def record_circuit_failure(
        self,
        *,
        provider_id: str,
        transient: bool,
        failure_threshold: int,
        cooldown_seconds: int,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        _require_aware(now, "now")
        if not provider_id.strip():
            raise ValueError("provider_id must not be blank")
        if type(failure_threshold) is not int or failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if type(cooldown_seconds) is not int or cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        await self._ensure_circuit_row(provider_id, normalized_now)
        state = await self._locked_circuit_state(provider_id)
        if not transient:
            return state
        failures = state.consecutive_transient_failures + 1
        should_open = state.state is not AgentCircuitState.CLOSED or failures >= failure_threshold
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
                half_open_probe_owner=None,
                half_open_probe_expires_at=None,
            )
        await self._session.execute(
            update(agent_provider_circuit_state_table)
            .where(agent_provider_circuit_state_table.c.provider_id == provider_id)
            .where(agent_provider_circuit_state_table.c.version == state.version)
            .values(**values)
        )
        return await self._locked_circuit_state(provider_id)

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
        row = (await self._session.execute(statement)).mappings().one_or_none()
        if row is None:
            return False
        return (
            str(row["status"]) in {"queued", "running"}
            and _aware_datetime(row["created_at"]) <= now
            and _aware_datetime(row["deadline_at"]) > now
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
        provider_id: str,
        worker_id: str,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        _require_aware(now, "now")
        if not provider_id.strip() or not worker_id.strip():
            raise ValueError("provider_id and worker_id must not be blank")
        normalized_now = _utc_datetime(now)
        await self._acquire_write_transaction()
        await self._ensure_circuit_row(provider_id, normalized_now)
        state = await self._locked_circuit_state(provider_id)
        if state.state is AgentCircuitState.HALF_OPEN and state.half_open_probe_owner != worker_id:
            raise AgentOperationConflict("agent_circuit_probe_not_owned")
        if state.state is AgentCircuitState.OPEN:
            raise AgentOperationConflict("agent_circuit_open")
        await self._session.execute(
            update(agent_provider_circuit_state_table)
            .where(agent_provider_circuit_state_table.c.provider_id == provider_id)
            .where(agent_provider_circuit_state_table.c.version == state.version)
            .values(
                state=AgentCircuitState.CLOSED.value,
                consecutive_transient_failures=0,
                opened_at=None,
                cooldown_until=None,
                half_open_probe_owner=None,
                half_open_probe_expires_at=None,
                version=agent_provider_circuit_state_table.c.version + 1,
                updated_at=normalized_now,
            )
        )
        return await self._locked_circuit_state(provider_id)

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
    ) -> None:
        statement = (
            select(agent_run_operations_table.c.id)
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
            .where(agent_run_operations_table.c.provider_id == provider_id)
            .where(agent_run_operations_table.c.status == AgentOperationStatus.LEASED.value)
            .where(agent_run_operations_table.c.lease_owner == worker_id)
            .where(agent_run_operations_table.c.lease_expires_at > now)
            .where(agent_plan_stages_table.c.household_id == str(household_id))
            .where(agent_plan_runs_table.c.household_id == str(household_id))
            .where(agent_plan_runs_table.c.status.in_(("queued", "running")))
            .where(agent_plan_runs_table.c.deadline_at > now)
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        exists = (await self._session.execute(statement)).scalar_one_or_none()
        if exists is None:
            raise AgentOperationConflict("agent_operation_not_reservable")

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
    ) -> AgentRunOperationRecord | None:
        row = (
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
        return _operation_record(row) if row is not None else None

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

    async def _get_scope_snapshot_by_fingerprint(
        self,
        household_id: UUID,
        run_id: UUID,
        fingerprint: str,
    ) -> AgentRunScopeSnapshotRecord | None:
        row = (
            (
                await self._session.execute(
                    select(agent_run_scope_snapshots_table)
                    .where(agent_run_scope_snapshots_table.c.household_id == str(household_id))
                    .where(agent_run_scope_snapshots_table.c.run_id == str(run_id))
                    .where(agent_run_scope_snapshots_table.c.fingerprint == fingerprint)
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
            "half_open_probe_owner": None,
            "half_open_probe_expires_at": None,
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
        statement = select(agent_provider_circuit_state_table).where(
            agent_provider_circuit_state_table.c.provider_id == provider_id
        )
        if self._session.get_bind().dialect.name != "sqlite":
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one()
        return _circuit_record(row)


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
        await self._require_confirmed_references(
            candidate.household_id,
            candidate.run_id,
            candidate.component_evidence_ids,
        )
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
    ) -> None:
        stored = set(
            (
                await self._session.execute(
                    select(agent_confirmed_offer_evidence_table.c.id)
                    .where(agent_confirmed_offer_evidence_table.c.household_id == str(household_id))
                    .where(agent_confirmed_offer_evidence_table.c.run_id == str(run_id))
                    .where(
                        agent_confirmed_offer_evidence_table.c.id.in_(
                            [str(value) for value in evidence_ids]
                        )
                    )
                )
            ).scalars()
        )
        if stored != {str(value) for value in evidence_ids}:
            raise AgentEvidenceError("agent_evidence_reference_not_found")

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
    canonical = _canonical_json(
        {
            "plan": revision.plan,
            "scope_snapshot": revision.scope_snapshot,
            "capability_snapshot": revision.capability_snapshot,
            "cost_model_snapshot": revision.cost_model_snapshot,
            "parser_version": revision.parser_version,
            "planner_version": revision.planner_version,
            "estimates": {
                "calendar_searches": revision.estimated_calendar_searches,
                "exact_searches": revision.estimated_exact_searches,
                "logical_operations": revision.estimated_logical_operations,
                "http_attempts": revision.estimated_http_attempts,
                "deadline_seconds": revision.estimated_deadline_seconds,
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
)
_PROVIDER_BOUND_OPERATION_KINDS = frozenset(
    {
        AgentOperationKind.CALENDAR_SEARCH,
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
        AgentOperationKind.SUGGEST_DISCOVERY,
    }
)


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
        if re.match(r"^[a-z][a-z0-9+.-]*://", value.strip(), flags=re.IGNORECASE):
            raise ValueError(f"unsafe field at {path}: URL values are not allowed")
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
            if inspect_keys and any(part in normalized_key for part in _UNSAFE_JSON_KEY_PARTS):
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
    if operation.provider_id is not None and not operation.provider_id.strip():
        raise ValueError("provider_id must not be blank")
    if kind in _PROVIDER_BOUND_OPERATION_KINDS and operation.provider_id is None:
        raise ValueError("provider-bound operation requires provider_id")
    if type(operation.consumes_logical_unit) is not bool:
        raise TypeError("consumes_logical_unit must be bool")
    if type(operation.max_attempts) is not int or operation.max_attempts <= 0:
        raise ValueError("max_attempts must be a positive integer")
    _validate_fingerprint(operation.operation_fingerprint, "operation_fingerprint")
    _validate_fingerprint(
        operation.logical_operation_fingerprint,
        "logical_operation_fingerprint",
    )
    _require_aware(operation.created_at, "created_at")
    immutable_input_json = canonical_sanitized_json(operation.immutable_input)
    private_continuation_json = (
        canonical_sanitized_json(operation.private_continuation)
        if operation.private_continuation is not None
        else None
    )
    return immutable_input_json, private_continuation_json


def _validate_fingerprint(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase sha256 fingerprint")


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
    return or_(
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
        half_open_probe_owner=(
            str(row["half_open_probe_owner"]) if row["half_open_probe_owner"] is not None else None
        ),
        half_open_probe_expires_at=(
            _aware_datetime(probe_expires_at) if probe_expires_at is not None else None
        ),
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
    if type(amount_minor) is not int or amount_minor < 0:
        raise ValueError("amount_minor must be a non-negative integer or None")
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
    return canonical_sanitized_json(signal.signal_evidence)


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
    return canonical_sanitized_json(evidence.itinerary_evidence)


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
    return canonical_sanitized_json(candidate.itinerary_evidence)


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
    return canonical_sanitized_json(snapshot.ranking)


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
