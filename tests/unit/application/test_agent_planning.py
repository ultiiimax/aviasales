from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import product

import pytest

from flight_hunter.application.agent_intent import IntentOverlay, IntentParser, merge_overlay
from flight_hunter.application.agent_planning import (
    AgentPlanBuilder,
    PlanBudgetExceededError,
    PlanEstimator,
    PlanRevisionStatus,
    SearchSurface,
)
from flight_hunter.application.agent_scope import CoverageMode, ScopeResolver
from flight_hunter.domain.agent_search import DateMode, ProviderHttpCostModel
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportType,
    freeze_airport_catalog,
)

NOW = datetime(2026, 7, 14, 8, 30, tzinfo=UTC)


class StaticAirportCatalog:
    def __init__(self, airports: tuple[Airport, ...]) -> None:
        self._snapshot = freeze_airport_catalog(airports)

    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        return self._snapshot


def _airport(code: str, country: str, municipality: str) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} {code} Airport",
        municipality=municipality,
        country_code=country,
        latitude=48.0,
        longitude=2.0,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance="review.test_catalog",
    )


def _base_catalog() -> tuple[Airport, ...]:
    return (
        _airport("LED", "RU", "Saint Petersburg"),
        _airport("CDG", "FR", "Paris"),
        _airport("ORY", "FR", "Paris"),
        _airport("LYS", "FR", "Lyon"),
        _airport("NCE", "FR", "Nice"),
    )


def _builder(airports: tuple[Airport, ...] | None = None) -> AgentPlanBuilder:
    resolver = ScopeResolver(repository=StaticAirportCatalog(airports or _base_catalog()))
    return AgentPlanBuilder(clock=lambda: NOW, scope_resolver=resolver)


def _generated_airports(count: int, *, country: str) -> tuple[Airport, ...]:
    codes = (
        "".join(letters)
        for letters in product("ABCDEFGHIJKLMNOPQRSTUVWXYZ", repeat=3)
        if "".join(letters) != "LED"
    )
    return tuple(_airport(next(codes), country, f"City {index}") for index in range(count))


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


@pytest.mark.anyio
async def test_finite_scope_is_frozen_before_approval_and_estimate_uses_cartesian_pairs() -> None:
    parsed = IntentParser().parse(
        "LED → France",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await _builder().build(parsed, CoverageMode.FULL)

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert len(revision.frozen_legs) == 1
    frozen = revision.frozen_legs[0]
    assert frozen.origin_scope.airport_codes == ("LED",)
    assert frozen.destination_scope is not None
    assert frozen.destination_scope.airport_codes == ("CDG", "LYS", "NCE", "ORY")
    assert frozen.origin_scope.catalog_checksum == frozen.destination_scope.catalog_checksum
    assert frozen.destination_scope.taxonomy_version.startswith("countries-v1-")
    assert frozen.destination_scope.commercial_provenance == "review.test_catalog"
    assert revision.estimate is not None
    assert revision.estimate.calendar_searches == 0
    assert revision.estimate.exact_searches == 4


@pytest.mark.anyio
@pytest.mark.parametrize(
    "route",
    (
        "ZZZ → France",
        "LED → country:XK",
        "LED → region:Atlantis",
        "LED → Congo",
    ),
)
async def test_unknown_or_invalid_geography_cannot_reach_approval(route: str) -> None:
    parsed = IntentParser().parse(
        route,
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await _builder().build(parsed, CoverageMode.FULL)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.frozen_legs == ()
    assert any(item.field.endswith("scope") for item in revision.clarifications)
    assert any(
        item.code in {"unknown_geography", "ambiguous_geography", "no_searchable_airports"}
        for item in revision.clarifications
    )


@pytest.mark.anyio
async def test_raw_location_syntax_without_catalog_never_reaches_approval() -> None:
    parsed = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await AgentPlanBuilder(clock=lambda: NOW).build(parsed, CoverageMode.FULL)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.frozen_legs == ()
    assert tuple(item.field for item in revision.clarifications) == ("geography_catalog",)


@pytest.mark.anyio
async def test_quick_anywhere_freezes_rule_and_estimates_seed_worst_case() -> None:
    parsed = IntentParser().parse(
        "LED → anywhere",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    frozen = revision.frozen_legs[0]
    assert frozen.destination_scope is None
    assert frozen.anywhere_rule is not None
    assert frozen.anywhere_rule.origin_airports == ("LED",)
    assert frozen.anywhere_rule.date_start == date(2026, 9, 10)
    assert frozen.anywhere_rule.date_end == date(2026, 9, 10)
    assert frozen.anywhere_rule.max_destination_seeds == 40
    assert frozen.anywhere_rule.exact_verification_limit == 20
    assert frozen.anywhere_rule.catalog_checksum == frozen.origin_scope.catalog_checksum
    assert revision.estimate is not None
    assert revision.estimate.calendar_searches == 40
    assert revision.estimate.exact_searches == 20
    assert revision.estimate.logical_operations == 60


@pytest.mark.anyio
async def test_full_anywhere_uses_full_bounds_and_requires_budget_revision() -> None:
    parsed = IntentParser().parse(
        "LED → anywhere",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await _builder().build(parsed, CoverageMode.FULL)

    assert revision.status is PlanRevisionStatus.DRAFT
    frozen = revision.frozen_legs[0]
    assert frozen.anywhere_rule is not None
    assert frozen.anywhere_rule.max_destination_seeds == 240
    assert frozen.anywhere_rule.exact_verification_limit == 240
    assert revision.estimate is not None
    assert revision.estimate.calendar_searches == 240
    assert revision.estimate.exact_searches == 240
    assert revision.estimate.logical_operations == 480
    assert revision.estimate.requested_logical_limit == 480
    assert tuple(item.code for item in revision.clarifications) == ("budget_revision_required",)


@pytest.mark.anyio
async def test_full_frozen_surface_is_not_truncated_to_quick_exact_limit() -> None:
    airports = (
        _airport("LED", "RU", "Saint Petersburg"),
        *_generated_airports(241, country="FR"),
    )
    parsed = IntentParser().parse(
        "LED → France",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    revision = await _builder(airports).build(parsed, CoverageMode.FULL)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.estimate is not None
    assert revision.estimate.exact_searches == 241
    assert revision.estimate.logical_operations == 241
    assert revision.estimate.requested_logical_limit == 241
    assert revision.estimate.requires_budget_revision is True
    assert tuple(item.code for item in revision.clarifications) == ("budget_revision_required",)


@pytest.mark.anyio
async def test_full_frozen_surface_above_absolute_limit_is_rejected() -> None:
    airports = (
        _airport("LED", "RU", "Saint Petersburg"),
        *_generated_airports(1_001, country="FR"),
    )
    parsed = IntentParser().parse(
        "LED → France",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )

    with pytest.raises(PlanBudgetExceededError, match="absolute_logical_limit"):
        await _builder(airports).build(parsed, CoverageMode.FULL)


@pytest.mark.anyio
async def test_complete_plan_auto_finalizes_and_rolling_window_uses_injected_clock() -> None:
    parsed = IntentParser().parse(
        "СПб → Франция",
        preset=None,
        selections={"date_mode": "rolling_90_days"},
    )

    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.AWAITING_APPROVAL
    assert revision.travel_intent is not None
    constraint = revision.travel_intent.legs[0].date_constraint
    assert constraint.mode is DateMode.ROLLING_90_DAYS
    assert constraint.start_date == date(2026, 7, 14)
    assert constraint.end_date == date(2026, 10, 11)
    assert revision.estimate is not None
    assert revision.estimate.calendar_searches == 40
    assert revision.estimate.exact_searches == 20
    assert revision.capability_snapshot is not None
    assert revision.clarifications == ()


@pytest.mark.anyio
async def test_incomplete_plan_stays_draft_with_structured_clarification() -> None:
    parsed = IntentParser().parse("СПб → Франция", preset=None, selections={})

    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.travel_intent is None
    assert revision.estimate is None
    assert revision.frozen_legs == ()
    assert tuple(item.field for item in revision.clarifications) == ("date_constraint",)


@pytest.mark.anyio
async def test_round_trip_overlay_missing_return_date_stays_structured_draft() -> None:
    base = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )
    parsed = merge_overlay(base, IntentOverlay(trip_shape="round_trip"))

    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.travel_intent is None
    assert tuple(item.field for item in revision.clarifications) == ("return_date_constraint",)


@pytest.mark.anyio
async def test_range_overlay_missing_end_date_stays_structured_draft() -> None:
    base = IntentParser().parse(
        "LED → CDG",
        preset=None,
        selections={"departure_date": "2026-09-10"},
    )
    parsed = merge_overlay(base, IntentOverlay(date_mode="range"))

    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert revision.travel_intent is None
    assert tuple(item.code for item in revision.clarifications) == ("date_range_end_required",)


@pytest.mark.anyio
async def test_rolling_overlay_clears_only_resolved_date_clarification() -> None:
    base = IntentParser().parse("unknown origin → France", preset=None, selections={})
    parsed = merge_overlay(base, IntentOverlay(date_mode="rolling_90_days"))

    assert "date_constraint" not in {item.field for item in parsed.clarifications}
    assert "origin" in {item.field for item in parsed.clarifications}
    revision = await _builder().build(parsed, CoverageMode.QUICK)

    assert revision.status is PlanRevisionStatus.DRAFT
    assert tuple(item.field for item in revision.clarifications) == ("origin",)
