from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from flight_hunter.application.agent_intent import IntentOverlay, IntentParser, merge_overlay
from flight_hunter.application.agent_planning import (
    AgentPlanBuilder,
    PlanBudgetExceededError,
    PlanEstimator,
    PlanRevisionStatus,
    SearchSurface,
)
from flight_hunter.application.agent_scope import CoverageMode
from flight_hunter.domain.agent_search import DateMode, ProviderHttpCostModel

NOW = datetime(2026, 7, 14, 8, 30, tzinfo=UTC)


def test_http_attempt_estimate_includes_every_start_poll_and_retry() -> None:
    cost = ProviderHttpCostModel(
        version="aviasales-v1",
        start_attempts=3,
        poll_rounds=8,
        attempts_per_poll=3,
    )
    estimator = PlanEstimator()

    assert cost.worst_case_exact_http_attempts == 27
    assert estimator.estimate_http_attempts(exact_searches=2, calendar_searches=1) == 57


def test_quick_budget_accepts_exact_boundary_and_rejects_61_operations() -> None:
    estimator = PlanEstimator()
    accepted = estimator.estimate(
        SearchSurface(CoverageMode.QUICK, calendar_searches=40, exact_searches=20),
        cost_model=estimator.cost_model,
    )

    assert accepted.logical_operations == 60
    assert accepted.calendar_searches == 40
    assert accepted.exact_searches == 20
    assert accepted.requires_budget_revision is False
    with pytest.raises(PlanBudgetExceededError, match="quick_logical_limit"):
        estimator.estimate(
            SearchSurface(CoverageMode.QUICK, calendar_searches=40, exact_searches=21),
            cost_model=estimator.cost_model,
        )


def test_full_budget_above_default_requires_revision_and_absolute_ceiling_rejects() -> None:
    estimator = PlanEstimator()
    estimate = estimator.estimate(
        SearchSurface(CoverageMode.FULL, calendar_searches=221, exact_searches=20),
        cost_model=estimator.cost_model,
    )

    assert estimate.logical_operations == 241
    assert estimate.requires_budget_revision is True
    assert estimate.requested_logical_limit == 241
    with pytest.raises(PlanBudgetExceededError, match="absolute_logical_limit"):
        estimator.estimate(
            SearchSurface(CoverageMode.FULL, calendar_searches=981, exact_searches=20),
            cost_model=estimator.cost_model,
        )


def test_complete_plan_auto_finalizes_and_rolling_window_uses_injected_clock() -> None:
    parsed = IntentParser().parse(
        "СПб → Франция",
        preset=None,
        selections={"date_mode": "rolling_90_days"},
    )

    revision = AgentPlanBuilder(clock=lambda: NOW).build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert revision.travel_intent is not None
    constraint = revision.travel_intent.legs[0].date_constraint
    assert constraint.mode is DateMode.ROLLING_90_DAYS
    assert constraint.start_date == date(2026, 7, 14)
    assert constraint.end_date == date(2026, 10, 11)
    assert revision.estimate is not None
    assert revision.capability_snapshot is not None
    assert revision.clarifications == ()


def test_incomplete_plan_stays_draft_with_structured_clarification() -> None:
    parsed = IntentParser().parse("СПб → Франция", preset=None, selections={})

    revision = AgentPlanBuilder(clock=lambda: NOW).build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.travel_intent is None
    assert revision.estimate is None
    assert tuple(item.field for item in revision.clarifications) == ("date_constraint",)


def test_validated_date_overlay_is_applied_by_plan_builder_clock() -> None:
    base = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )
    parsed = merge_overlay(
        base,
        IntentOverlay(date_mode=DateMode.ROLLING_90_DAYS),
    )

    revision = AgentPlanBuilder(clock=lambda: NOW).build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert revision.travel_intent is not None
    constraint = revision.travel_intent.legs[0].date_constraint
    assert constraint.mode is DateMode.ROLLING_90_DAYS
    assert constraint.start_date == date(2026, 7, 14)
    assert constraint.end_date == date(2026, 10, 11)
