from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid5

from flight_hunter.application.agent_lifecycle import (
    CreateAgentPlan,
    ExecuteAgentPlan,
    PlanView,
    RunView,
)
from flight_hunter.application.watch_service import CreateWatchCommand, WatchService
from flight_hunter.domain.places import PlaceKind
from flight_hunter.persistence.repositories import WatchRecord

AgentActionKind = Literal["search_execute", "watch_create"]
_WATCH_NAMESPACE = UUID("23cc31fc-60c7-4e83-9b9f-f4d4cdf9e4a5")


class AgentWatchCreationError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class AgentPlanBinding:
    plan_id: UUID
    revision_id: UUID
    expected_revision: int
    content_hash: str

    @classmethod
    def from_plan(cls, plan: PlanView) -> AgentPlanBinding:
        return cls(
            plan_id=plan.plan_id,
            revision_id=plan.revision_id,
            expected_revision=plan.revision,
            content_hash=plan.content_hash,
        )


@dataclass(frozen=True, slots=True)
class AgentActionGrant:
    kind: AgentActionKind
    household_id: UUID
    user_id: UUID
    session_id: UUID
    binding: AgentPlanBinding
    idempotency_key: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        if self.kind not in {"search_execute", "watch_create"}:
            raise ValueError("unsupported agent action grant")
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 200:
            raise ValueError("agent action idempotency key is invalid")
        if not self.request_fingerprint.startswith("sha256:"):
            raise ValueError("agent request fingerprint is invalid")


class AgentLifecyclePort(Protocol):
    async def create_plan(self, command: CreateAgentPlan) -> PlanView: ...

    async def execute_plan(self, command: ExecuteAgentPlan) -> RunView: ...

    async def get_chat_replay(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        session_id: UUID,
        execute_idempotency_prefix: str,
        execute_idempotency_key: str,
    ) -> tuple[PlanView, RunView] | None: ...


class AgentToolGateway:
    """Narrow typed facade over the durable plan lifecycle."""

    def __init__(
        self,
        lifecycle: AgentLifecyclePort,
        *,
        watch_service: WatchService | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._watch_service = watch_service

    async def create_plan(self, command: CreateAgentPlan) -> PlanView:
        return await self._lifecycle.create_plan(command)

    async def replay_search(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        session_id: UUID,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> tuple[PlanView, RunView] | None:
        prefix, execute_key = _execute_idempotency_binding(
            idempotency_key,
            request_fingerprint,
        )
        return await self._lifecycle.get_chat_replay(
            household_id=household_id,
            user_id=user_id,
            session_id=session_id,
            execute_idempotency_prefix=prefix,
            execute_idempotency_key=execute_key,
        )

    async def start_search(self, plan: PlanView, grant: AgentActionGrant) -> RunView:
        if grant.kind != "search_execute":
            raise ValueError("search execution requires a search grant")
        if not plan.executable or plan.clarifications:
            raise ValueError("only a complete plan can be executed")
        if grant.binding != AgentPlanBinding.from_plan(plan):
            raise ValueError("agent action grant does not match the plan")
        _prefix, execute_key = _execute_idempotency_binding(
            grant.idempotency_key,
            grant.request_fingerprint,
        )
        return await self._lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=grant.household_id,
                user_id=grant.user_id,
                approved_by_session_id=grant.session_id,
                plan_id=grant.binding.plan_id,
                revision_id=grant.binding.revision_id,
                expected_revision=grant.binding.expected_revision,
                content_hash=grant.binding.content_hash,
                idempotency_key=execute_key,
            )
        )

    async def create_watch(self, plan: PlanView, grant: AgentActionGrant) -> WatchRecord:
        if grant.kind != "watch_create" or self._watch_service is None:
            raise AgentWatchCreationError("watch_create_unavailable")
        if grant.binding != AgentPlanBinding.from_plan(plan):
            raise AgentWatchCreationError("watch_binding_invalid")
        command = _watch_command(plan, grant)
        assert command.watch_id is not None
        existing = await self._watch_service.get_watch(grant.household_id, command.watch_id)
        if existing is not None:
            if _watch_matches(existing, command):
                return existing
            raise AgentWatchCreationError("watch_idempotency_conflict")
        return await self._watch_service.create_watch(command)


def _execute_idempotency_binding(
    idempotency_key: str,
    request_fingerprint: str,
) -> tuple[str, str]:
    raw_key_hash = hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()
    fingerprint_hash = request_fingerprint.removeprefix("sha256:")
    invalid_hex = any(char not in "0123456789abcdef" for char in fingerprint_hash)
    if len(fingerprint_hash) != 64 or invalid_hex:
        raise ValueError("agent request fingerprint is invalid")
    prefix = f"chat:{raw_key_hash}:"
    return prefix, f"{prefix}{fingerprint_hash}"


def _watch_command(plan: PlanView, grant: AgentActionGrant) -> CreateWatchCommand:
    if not plan.summary.scope:
        raise AgentWatchCreationError("watch_scope_unsupported")
    outbound = plan.summary.scope[0]
    if (
        outbound.date_mode != "exact"
        or outbound.date_start is None
        or outbound.origin_value is None
        or outbound.destination_value is None
        or len(outbound.origin_value) != 3
        or len(outbound.destination_value) != 3
        or outbound.origin_kind not in {"city", "airport"}
        or outbound.destination_kind not in {"city", "airport"}
    ):
        raise AgentWatchCreationError("watch_scope_unsupported")
    return_date = None
    if plan.summary.trip_shape == "round_trip":
        if len(plan.summary.scope) < 2 or plan.summary.scope[1].date_start is None:
            raise AgentWatchCreationError("watch_scope_unsupported")
        return_date = plan.summary.scope[1].date_start
    key_hash = hashlib.sha256(grant.idempotency_key.encode("utf-8")).hexdigest()
    watch_id = uuid5(_WATCH_NAMESPACE, f"{grant.household_id}:{key_hash}")
    return CreateWatchCommand(
        household_id=grant.household_id,
        owner_user_id=grant.user_id,
        origin=outbound.origin_value,
        destination=outbound.destination_value,
        origin_kind=PlaceKind(outbound.origin_kind),
        destination_kind=PlaceKind(outbound.destination_kind),
        origin_airport_codes=outbound.origin_airports,
        destination_airport_codes=outbound.destination_airports,
        directory_version="agent-plan-scope-v1",
        departure_date=outbound.date_start,
        return_date=return_date,
        passengers=plan.summary.passengers.total,
        currency=plan.summary.passengers.currency,
        allowed_provider_ids=(plan.summary.provider.source_id,),
        watch_id=watch_id,
    )


def _watch_matches(existing: WatchRecord, command: CreateWatchCommand) -> bool:
    return (
        existing.household_id == command.household_id
        and existing.owner_user_id == command.owner_user_id
        and existing.origin == command.origin
        and existing.destination == command.destination
        and existing.departure_date == command.departure_date
        and existing.return_date == command.return_date
        and existing.passengers == command.passengers
        and existing.currency == command.currency
    )
