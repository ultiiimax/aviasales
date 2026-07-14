from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from flight_hunter.application.agent_lifecycle import CreateAgentPlan, PlanView


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


@dataclass(slots=True)
class IntentDraft:
    origin_query: str | None = None
    destination_query: str | None = None
    origin: str | None = None
    destination: str | None = None
    departure_date: str | None = None
    return_date: str | None = None
    date_hint: str | None = None
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
    ) -> None:
        self._plan_creator = plan_creator

    async def handle_turn(self, request: AgentTurnRequest) -> AgentTurnResponse:
        if request.household_id is None or request.user_id is None:
            raise ValueError("authenticated household and user are required")
        selections = _selections(request)
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
        return AgentTurnResponse(
            reply_ru=_reply(plan),
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
                        f"state={plan.state} coverage={plan.coverage}"
                    ),
                    policy_decision="approval_required_before_provider_calls",
                    related_id=str(plan.plan_id),
                ),
            ),
            runtime=_runtime_info(),
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


def _runtime_info() -> AgentRuntimeInfo:
    return AgentRuntimeInfo(
        backend="deterministic_harness",
        agentic_loop="approval_gated_plan_lifecycle",
        model=None,
        fallback_backend=None,
        live_calls_allowed=False,
        cloudflare_ready=True,
    )
