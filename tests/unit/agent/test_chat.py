from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from flight_hunter.agent.chat import AgentChatService, AgentTurnRequest
from flight_hunter.application.agent_lifecycle import (
    CreateAgentPlan,
    PlanPassengerView,
    PlanProviderView,
    PlanSummaryView,
    PlanView,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
PLAN_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
REVISION_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_agent_chat_delegates_free_text_to_durable_plan_creator() -> None:
    creator = RecordingPlanCreator(_draft_plan())
    service = AgentChatService(plan_creator=creator)

    response = await service.handle_turn(
        AgentTurnRequest(
            message="Найди самый дешёвый вариант из СПб во Францию",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
    )

    assert creator.commands == [
        CreateAgentPlan(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            text="Найди самый дешёвый вариант из СПб во Францию",
            selections={},
        )
    ]
    assert response.proposed_plan == _draft_plan()
    assert response.missing_slots == ("date_constraint",)
    assert [action.kind for action in response.actions] == ["use_rolling_90_days"]
    assert response.actions[0].parameters == {"date_mode": "rolling_90_days"}
    assert all(action.kind != "search_cached_offers" for action in response.actions)
    assert response.outcome == "clarification"
    assert response.runtime.backend == "deterministic_gateway"
    assert response.runtime.model is None
    assert response.runtime.agentic_loop == "immediate_durable_search"


@pytest.mark.anyio
async def test_agent_chat_forwards_rolling_90_day_selection_without_execution() -> None:
    creator = RecordingPlanCreator(_budget_limited_plan())
    service = AgentChatService(plan_creator=creator)

    response = await service.handle_turn(
        AgentTurnRequest(
            message="Найди самый дешёвый вариант из СПб во Францию",
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            date_mode="rolling_90_days",
        )
    )

    assert creator.commands[0].selections == {"date_mode": "rolling_90_days"}
    assert response.proposed_plan.executable is False
    assert response.proposed_plan.estimate is None
    assert response.proposed_plan.clarifications[0]["code"] == "quick_budget_too_large"
    assert response.runtime.live_calls_allowed is False


class RecordingPlanCreator:
    def __init__(self, result: PlanView) -> None:
        self.result = result
        self.commands: list[CreateAgentPlan] = []

    async def create_plan(self, command: CreateAgentPlan) -> PlanView:
        self.commands.append(command)
        return self.result


def _draft_plan() -> PlanView:
    return PlanView(
        plan_id=PLAN_ID,
        revision_id=REVISION_ID,
        revision=1,
        state="draft",
        content_hash="sha256:" + "1" * 64,
        coverage="quick",
        executable=False,
        enabled_strategies=(),
        estimate=None,
        summary=_summary("exact"),
        clarifications=(
            {
                "field": "date_constraint",
                "code": "date_required",
                "message_ru": "Укажите дату или период поездки.",
                "actions": (
                    {
                        "action_id": "use_rolling_90_days",
                        "label_ru": "Проверить ближайшие 90 дней",
                        "selections": {},
                        "date_mode": "rolling_90_days",
                    },
                ),
                "details": {},
            },
        ),
        created_at=NOW,
        expires_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )


def _budget_limited_plan() -> PlanView:
    return PlanView(
        plan_id=PLAN_ID,
        revision_id=REVISION_ID,
        revision=1,
        state="draft",
        content_hash="sha256:" + "2" * 64,
        coverage="quick",
        executable=False,
        enabled_strategies=("direct", "through_ticket"),
        estimate=None,
        summary=_summary("rolling_90_days"),
        clarifications=(
            {
                "field": "coverage",
                "code": "quick_budget_too_large",
                "message_ru": "Быстрый план превышает лимит.",
                "actions": (),
                "details": {
                    "calendar_searches": 90,
                    "exact_searches": 90,
                    "logical_operations": 180,
                    "limit": 60,
                },
            },
        ),
        created_at=NOW,
        expires_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )


def _summary(date_mode: str) -> PlanSummaryView:
    return PlanSummaryView(
        trip_shape="one_way",
        date_mode=date_mode,
        preset_id=None,
        analysis_modes=(),
        passengers=PlanPassengerView(
            adults=1,
            children=0,
            infants=0,
            total=1,
            currency="RUB",
        ),
        scope=(),
        provider=PlanProviderView(
            source_id="aviasales_search",
            capability_version="mobile-contract-2026-07-13",
            cost_model_version="aviasales-v1",
            requests_per_minute=20,
        ),
        hidden_city_enabled=False,
    )
