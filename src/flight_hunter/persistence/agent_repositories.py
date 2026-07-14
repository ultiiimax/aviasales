from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.persistence.models import (
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
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
                        superseded_at=_utc_datetime(revision.created_at),
                    )
                )
                await self._session.execute(
                    insert(agent_search_plan_revisions_table).values(
                        **_revision_values(
                            plan_id=plan_id,
                            household_id=household_id,
                            source_revision_id=source_revision_id,
                            revision_number=int(latest_row["revision_number"]) + 1,
                            revision=revision,
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
