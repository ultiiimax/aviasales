from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from flight_hunter.application.agent_lifecycle import CreateAgentPlan, PlanView, RunView
from flight_hunter.application.agent_tools import (
    AgentActionGrant,
    AgentPlanBinding,
    AgentToolGateway,
    AgentWatchCreationError,
)


@dataclass(frozen=True, slots=True)
class AgentTurnRequest:
    message: str
    household_id: UUID | None = None
    user_id: UUID | None = None
    selected_origin: str | None = None
    selected_destination: str | None = None
    departure_date: str | None = None
    return_date: str | None = None
    date_mode: str | None = None
    passengers: int = 1
    adults: int | None = None
    children: int = 0
    infants: int = 0
    currency: str = "RUB"
    session_id: UUID | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AirportOption:
    iata_code: str
    label: str
    name: str
    municipality: str
    country_code: str


@dataclass(frozen=True, slots=True)
class AgentAction:
    kind: str
    title_ru: str
    parameters: dict[str, object]
    requires_user_action: bool
    policy_decision: str
    related_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentAuditEvent:
    event_type: str
    tool_name: str
    summary: str
    policy_decision: str
    related_id: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRuntimeInfo:
    backend: str
    agentic_loop: str
    model: str | None
    fallback_backend: str | None
    live_calls_allowed: bool
    cloudflare_ready: bool


@dataclass(frozen=True, slots=True)
class AgentTurnResponse:
    reply_ru: str
    proposed_plan: PlanView
    extracted: dict[str, object]
    missing_slots: tuple[str, ...]
    airport_options: dict[str, tuple[AirportOption, ...]]
    actions: tuple[AgentAction, ...]
    audit_events: tuple[AgentAuditEvent, ...]
    runtime: AgentRuntimeInfo
    outcome: Literal["clarification", "run_started", "watch_created", "failure"]
    run: RunView | None = None
    idempotent_replay: bool = False
    warnings: tuple[str, ...] = ()
    watch_id: UUID | None = None


@dataclass(slots=True)
class IntentDraft:
    origin_query: str | None = None
    destination_query: str | None = None
    origin: str | None = None
    destination: str | None = None
    departure_date: str | None = None
    return_date: str | None = None
    date_hint: str | None = None
    trip_shape: str | None = None
    date_mode: str | None = None
    adults: int | None = None
    children: int | None = None
    infants: int | None = None
    currency: str | None = None
    nearby_radius_km: int | None = None
    requested_strategies: tuple[str, ...] = ()
    baggage_preference: str = "unspecified"
    wants_watch: bool = False


class AgentIntentAdapter(Protocol):
    @property
    def model(self) -> str: ...

    def extract_intent(self, message: str) -> IntentDraft | None: ...


class AgentPlanCreator(Protocol):
    async def create_plan(self, command: CreateAgentPlan) -> PlanView: ...


class AgentChatService:
    def __init__(
        self,
        *,
        plan_creator: AgentPlanCreator,
        search_gateway: AgentToolGateway | None = None,
    ) -> None:
        self._plan_creator = plan_creator
        self._search_gateway = search_gateway

    async def handle_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        if request.household_id is None or request.user_id is None:
            raise ValueError("authenticated household and user are required")
        selections = _selections(request)
        request_fingerprint = _request_fingerprint(request.message, selections)
        run: RunView | None = None
        plan: PlanView
        if (
            self._search_gateway is not None
            and request.session_id is not None
            and request.idempotency_key is not None
        ):
            replay = await self._search_gateway.replay_search(
                household_id=request.household_id,
                user_id=request.user_id,
                session_id=request.session_id,
                idempotency_key=request.idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        else:
            replay = None
        if replay is not None:
            plan, run = replay
        else:
            plan = await self._plan_creator.create_plan(
                CreateAgentPlan(
                    household_id=request.household_id,
                    user_id=request.user_id,
                    text=request.message,
                    selections=selections,
                )
            )
        actions = _clarification_actions(plan.clarifications)
        missing_slots = tuple(
            str(item["field"]) for item in plan.clarifications if isinstance(item.get("field"), str)
        )
        outcome: Literal["clarification", "run_started", "watch_created", "failure"]
        reply = _reply(plan)
        if run is not None:
            outcome = "run_started"
            reply = "Возвращаю уже запущенный поиск."
        elif plan.summary.hidden_city_enabled and not plan.clarifications:
            outcome = "clarification"
            missing_slots = ("hidden_city_warning",)
            reply = "Подтвердите риски скрытого города перед запуском поиска."
        elif plan.executable and not plan.clarifications and self._search_gateway is not None:
            if request.session_id is None or request.idempotency_key is None:
                raise ValueError("session and idempotency key are required for search execution")
            run = await self._search_gateway.start_search(
                plan,
                AgentActionGrant(
                    kind="search_execute",
                    household_id=request.household_id,
                    user_id=request.user_id,
                    session_id=request.session_id,
                    binding=AgentPlanBinding.from_plan(plan),
                    idempotency_key=request.idempotency_key,
                    request_fingerprint=request_fingerprint,
                ),
            )
            outcome = "run_started"
            reply = "Поиск запущен. Уже проверяю живые варианты."
        else:
            outcome = "clarification"
        warnings: tuple[str, ...] = ()
        watch_id: UUID | None = None
        if run is not None and plan.summary.wants_watch and self._search_gateway is not None:
            assert request.session_id is not None
            assert request.idempotency_key is not None
            try:
                watch = await self._search_gateway.create_watch(
                    plan,
                    AgentActionGrant(
                        kind="watch_create",
                        household_id=request.household_id,
                        user_id=request.user_id,
                        session_id=request.session_id,
                        binding=AgentPlanBinding.from_plan(plan),
                        idempotency_key=f"{request.idempotency_key}:watch",
                        request_fingerprint=request_fingerprint,
                    ),
                )
            except AgentWatchCreationError as error:
                warnings = (error.code,)
            else:
                watch_id = watch.id
                outcome = "watch_created"
                reply = "Поиск запущен, отслеживание цены создано."
        return AgentTurnResponse(
            reply_ru=reply,
            proposed_plan=plan,
            extracted=dict(selections),
            missing_slots=missing_slots,
            airport_options={"origin": (), "destination": ()},
            actions=actions,
            audit_events=(
                AgentAuditEvent(
                    event_type="agent_plan_proposed",
                    tool_name="create_agent_plan",
                    summary=(
                        f"plan_id={plan.plan_id} revision={plan.revision} "
                        f"state={plan.state} coverage={plan.coverage} outcome={outcome}"
                    ),
                    policy_decision=(
                        "user_message_authorized_search"
                        if run is not None
                        else "clarification_required"
                    ),
                    related_id=str(run.run_id if run is not None else plan.plan_id),
                ),
            ),
            runtime=_runtime_info(search_started=run is not None),
            outcome=outcome,
            run=run,
            idempotent_replay=run.idempotent_replay if run is not None else False,
            warnings=warnings,
            watch_id=watch_id,
        )


def _selections(request: AgentTurnRequest) -> dict[str, object]:
    selected: dict[str, object] = {}
    optional_values: tuple[tuple[str, object | None], ...] = (
        ("origin", request.selected_origin),
        ("destination", request.selected_destination),
        ("departure_date", request.departure_date),
        ("return_date", request.return_date),
        ("date_mode", request.date_mode),
    )
    for key, value in optional_values:
        if value is not None:
            selected[key] = value
    if request.adults is not None or request.passengers != 1:
        selected["adults"] = request.adults or request.passengers
    if request.children:
        selected["children"] = request.children
    if request.infants:
        selected["infants"] = request.infants
    if request.currency != "RUB":
        selected["currency"] = request.currency
    return selected


def _request_fingerprint(message: str, selections: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {"message": message.strip(), "selections": dict(selections)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _clarification_actions(
    clarifications: tuple[Mapping[str, object], ...],
) -> tuple[AgentAction, ...]:
    actions: list[AgentAction] = []
    for clarification in clarifications:
        raw_actions = clarification.get("actions", ())
        if not isinstance(raw_actions, (tuple, list)):
            continue
        for raw in raw_actions:
            if not isinstance(raw, Mapping):
                continue
            action_id = raw.get("action_id")
            label = raw.get("label_ru")
            if not isinstance(action_id, str) or not isinstance(label, str):
                continue
            parameters = _action_parameters(raw)
            actions.append(
                AgentAction(
                    kind=action_id,
                    title_ru=label,
                    parameters=parameters,
                    requires_user_action=True,
                    policy_decision="plan_revision_required",
                )
            )
    return tuple(actions)


def _action_parameters(action: Mapping[str, object]) -> dict[str, object]:
    selections = action.get("selections", {})
    result = dict(selections) if isinstance(selections, Mapping) else {}
    date_mode = action.get("date_mode")
    if isinstance(date_mode, str):
        result["date_mode"] = date_mode
    return result


def _reply(plan: PlanView) -> str:
    if plan.clarifications:
        message = plan.clarifications[0].get("message_ru")
        if isinstance(message, str):
            return message
    return "План сохранён. Проверьте объём и подтвердите запуск."


def _runtime_info(*, search_started: bool = False) -> AgentRuntimeInfo:
    return AgentRuntimeInfo(
        backend="deterministic_gateway",
        agentic_loop="immediate_durable_search",
        model=None,
        fallback_backend=None,
        live_calls_allowed=search_started,
        cloudflare_ready=True,
    )
