from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.agent.presets import AgentPresetId
from flight_hunter.application.agent_intent import (
    ClarificationAction,
    IntentClarification,
    IntentParser,
    ParsedDateConstraint,
    ParsedIntent,
    ParsedLeg,
)
from flight_hunter.application.agent_planning import (
    AgentPlanBuilder,
    PlanBudgetExceededError,
    ProposedPlanRevision,
)
from flight_hunter.application.agent_scope import CoverageMode, FrozenAirportScope
from flight_hunter.domain.agent_search import (
    DateConstraint,
    DateMode,
    LocationScope,
    LocationScopeKind,
    RouteStrategy,
    TripShape,
)
from flight_hunter.persistence.agent_repositories import (
    AgentPlanApprovalSnapshot,
    AgentPlanConflict,
    AgentPlanError,
    AgentPlanNotFound,
    AgentPlanRecord,
    AgentPlanRepository,
    AgentPlanRevisionRecord,
    AgentPlanRunRecord,
    AgentRunRepository,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
)

HIDDEN_CITY_WARNING_VERSION = "hidden-city-v1"
PARSER_VERSION = "intent-parser-v1"
_PUBLIC_RUN_ERRORS: dict[str, str] = {
    "deadline_exceeded": "Search deadline exceeded.",
    "provider_unavailable": "Flight provider is temporarily unavailable.",
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
    clarifications: tuple[Mapping[str, object], ...]
    created_at: datetime
    expires_at: datetime


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


@dataclass(frozen=True, slots=True)
class RunResultsView:
    run_id: UUID
    state: Literal["not_ready"] = "not_ready"
    evidence_available: bool = False


class AgentLifecycleService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        parser: IntentParser,
        builder: AgentPlanBuilder,
        clock: Callable[[], datetime] | None = None,
        provider_gateway: object | None = None,
    ) -> None:
        self._session = session
        self._parser = parser
        self._builder = builder
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider_gateway = provider_gateway
        self._plans = AgentPlanRepository(session)
        self._runs = AgentRunRepository(session)

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
            except (TypeError, ValueError) as error:
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
            except (TypeError, ValueError) as error:
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
            except (TypeError, ValueError) as error:
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
                return _bound_idempotent_run(existing, command)
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
                return _bound_idempotent_run(existing, command)
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
            return _bound_idempotent_run(stored, command)

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

    async def list_runs(self, household_id: UUID, plan_id: UUID) -> tuple[RunView, ...]:
        await self._require_plan(household_id, plan_id)
        return tuple(_run_view(run) for run in await self._runs.list_runs(household_id, plan_id))

    async def get_run(self, household_id: UUID, plan_id: UUID, run_id: UUID) -> RunView:
        await self._require_plan(household_id, plan_id)
        run = await self._runs.get_run(household_id, run_id)
        if run is None or run.plan_id != plan_id:
            raise AgentLifecycleError("agent_plan_not_found")
        return _run_view(run)

    async def get_latest_run(self, household_id: UUID, plan_id: UUID) -> RunView:
        await self._require_plan(household_id, plan_id)
        run = await self._runs.get_latest_run(household_id, plan_id)
        if run is None:
            raise AgentLifecycleError("agent_run_not_found")
        return _run_view(run)

    async def cancel_run(self, command: CancelAgentRun) -> RunView:
        async with self._owned_transaction():
            run = await self._runs.get_run(command.household_id, command.run_id)
            if run is None or run.plan_id != command.plan_id:
                raise AgentLifecycleError("agent_plan_not_found")
            if run.status == "cancel_requested":
                return _run_view(run)
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
        return _run_view(stored)

    async def get_run_results(
        self,
        household_id: UUID,
        plan_id: UUID,
        run_id: UUID,
    ) -> RunResultsView:
        run = await self._runs.get_run(household_id, run_id)
        if run is None or run.plan_id != plan_id:
            raise AgentLifecycleError("agent_plan_not_found")
        return RunResultsView(run_id=run.id)

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
        "clarifications": [
            _clarification_payload(clarification) for clarification in proposed.clarifications
        ],
    }


def _intent_payload(parsed: ParsedIntent) -> dict[str, object]:
    return {
        "origin_text": parsed.origin_text,
        "destination_text": parsed.destination_text,
        "trip_shape": parsed.trip_shape.value,
        "date_mode": parsed.date_mode.value,
        "adults": parsed.adults,
        "children": parsed.children,
        "infants": parsed.infants,
        "currency": parsed.currency,
        "requested_strategies": [strategy.value for strategy in parsed.requested_strategies],
        "preset_id": parsed.preset_id.value if parsed.preset_id is not None else None,
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
                "origin": _frozen_scope_payload(leg.origin_scope),
                "destination": (
                    _frozen_scope_payload(leg.destination_scope)
                    if leg.destination_scope is not None
                    else None
                ),
                "anywhere": (
                    {
                        "origin_airports": list(leg.anywhere_rule.origin_airports),
                        "date_start": leg.anywhere_rule.date_start.isoformat(),
                        "date_end": leg.anywhere_rule.date_end.isoformat(),
                        "allowed_country_codes": list(leg.anywhere_rule.allowed_country_codes),
                        "excluded_country_codes": list(leg.anywhere_rule.excluded_country_codes),
                        "discovery_source_ids": list(leg.anywhere_rule.discovery_source_ids),
                        "max_destination_seeds": leg.anywhere_rule.max_destination_seeds,
                        "exact_verification_limit": leg.anywhere_rule.exact_verification_limit,
                        "catalog_checksum": leg.anywhere_rule.catalog_checksum,
                        "taxonomy_version": leg.anywhere_rule.taxonomy_version,
                    }
                    if leg.anywhere_rule is not None
                    else None
                ),
                "date_constraint": _date_constraint_payload(leg.date_constraint),
            }
            for leg in proposed.frozen_legs
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
        clarifications=tuple(_mapping(value) for value in clarification_values),
        created_at=revision.created_at,
        expires_at=revision.expires_at,
    )


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


def _run_view(run: AgentPlanRunRecord) -> RunView:
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
    )


def _public_run_error(error_code: str | None) -> tuple[str | None, str | None]:
    if error_code is None:
        return None, None
    if error_code in _PUBLIC_RUN_ERRORS:
        return error_code, _PUBLIC_RUN_ERRORS[error_code]
    return "agent_run_failed", None


def _bound_idempotent_run(
    run: AgentPlanRunRecord,
    command: ExecuteAgentPlan,
) -> RunView:
    if command.revision_id is None or (
        run.plan_id != command.plan_id or run.revision_id != command.revision_id
    ):
        raise AgentLifecycleError("agent_run_idempotency_conflict")
    return _run_view(run)


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
