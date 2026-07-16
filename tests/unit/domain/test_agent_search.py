from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from flight_hunter.domain.agent_search import (
    CapabilityState,
    DateConstraint,
    DateMode,
    LocationScope,
    LocationScopeKind,
    PlanBudget,
    ProviderCapabilitySnapshot,
    ProviderHttpCostModel,
    RouteStrategy,
    TravelIntent,
    TravelLeg,
    TripShape,
    inclusive_month_count,
)


def _leg(origin: str, destination: str, departure_date: date) -> TravelLeg:
    return TravelLeg(
        origin=LocationScope(LocationScopeKind.AIRPORT, origin),
        destination=LocationScope(LocationScopeKind.AIRPORT, destination),
        date_constraint=DateConstraint(DateMode.EXACT, departure_date),
    )


def test_all_location_scope_kinds_have_provider_neutral_values() -> None:
    scopes = (
        LocationScope(LocationScopeKind.AIRPORT, "led"),
        LocationScope(LocationScopeKind.CITY, "par"),
        LocationScope(LocationScopeKind.COUNTRY, "fr"),
        LocationScope(LocationScopeKind.REGION, "western-europe"),
        LocationScope(LocationScopeKind.ANYWHERE, None),
    )

    assert tuple(scope.kind for scope in scopes) == tuple(LocationScopeKind)
    assert tuple(scope.value for scope in scopes) == (
        "LED",
        "PAR",
        "FR",
        "western-europe",
        None,
    )


def test_all_date_modes_preserve_their_bounds() -> None:
    constraints = (
        DateConstraint(DateMode.EXACT, date(2026, 9, 10)),
        DateConstraint(DateMode.FLEXIBLE, date(2026, 9, 10), flex_days=3),
        DateConstraint(DateMode.RANGE, date(2026, 9, 1), date(2026, 9, 30)),
        DateConstraint(
            DateMode.ROLLING_90_DAYS,
            date(2026, 7, 13),
            date(2026, 10, 10),
        ),
    )

    assert tuple(constraint.mode for constraint in constraints) == tuple(DateMode)
    assert constraints[1].flex_days == 3
    assert constraints[2].end_date == date(2026, 9, 30)


def test_rolling_90_days_counts_both_boundary_dates() -> None:
    constraint = DateConstraint(
        DateMode.ROLLING_90_DAYS,
        date(2026, 9, 1),
        date(2026, 11, 29),
    )

    assert constraint.end_date is not None
    assert (constraint.end_date - constraint.start_date).days == 89
    with pytest.raises(ValueError, match="90 inclusive dates"):
        DateConstraint(
            DateMode.ROLLING_90_DAYS,
            date(2026, 9, 1),
            date(2026, 11, 30),
        )


def test_inclusive_month_count_handles_boundary_and_rejects_reverse_range() -> None:
    assert inclusive_month_count(date(2026, 1, 31), date(2026, 12, 1)) == 12
    assert inclusive_month_count(date(9999, 12, 1), date(9999, 12, 31)) == 1
    with pytest.raises(ValueError, match="before"):
        inclusive_month_count(date(2026, 2, 1), date(2026, 1, 31))


def test_all_trip_shapes_and_route_strategies_are_closed_domain_enums() -> None:
    one_way = TravelIntent(
        trip_shape=TripShape.ONE_WAY,
        legs=(_leg("LED", "CDG", date(2026, 9, 10)),),
        adults=1,
        currency="RUB",
    )
    round_trip = TravelIntent(
        trip_shape=TripShape.ROUND_TRIP,
        legs=(
            _leg("LED", "CDG", date(2026, 9, 10)),
            _leg("CDG", "LED", date(2026, 9, 20)),
        ),
        adults=1,
        currency="RUB",
    )
    open_jaw = TravelIntent(
        trip_shape=TripShape.OPEN_JAW,
        legs=(
            _leg("LED", "CDG", date(2026, 9, 10)),
            _leg("NCE", "LED", date(2026, 9, 20)),
        ),
        adults=1,
        currency="RUB",
    )
    multi_city = TravelIntent(
        trip_shape=TripShape.MULTI_CITY,
        legs=(
            _leg("LED", "CDG", date(2026, 9, 10)),
            _leg("CDG", "FCO", date(2026, 9, 15)),
            _leg("FCO", "LED", date(2026, 9, 20)),
        ),
        adults=1,
        currency="RUB",
        requested_strategies=tuple(RouteStrategy),
    )

    assert tuple(intent.trip_shape for intent in (one_way, round_trip, open_jaw, multi_city)) == (
        TripShape.ONE_WAY,
        TripShape.ROUND_TRIP,
        TripShape.OPEN_JAW,
        TripShape.MULTI_CITY,
    )
    assert multi_city.requested_strategies == tuple(RouteStrategy)
    with pytest.raises(ValueError):
        RouteStrategy("invented")


def test_complete_travel_intent_preserves_ordered_multi_city_legs_and_passengers() -> None:
    legs = (
        _leg("LED", "CDG", date(2026, 9, 10)),
        _leg("CDG", "FCO", date(2026, 9, 15)),
        _leg("FCO", "LED", date(2026, 9, 20)),
    )

    intent = TravelIntent(
        trip_shape=TripShape.MULTI_CITY,
        legs=legs,
        adults=2,
        children=1,
        infants=1,
        currency="rub",
        requested_strategies=(RouteStrategy.THROUGH_TICKET, RouteStrategy.SELF_TRANSFER),
    )

    assert intent.legs == legs
    assert tuple(leg.origin.value for leg in intent.legs) == ("LED", "CDG", "FCO")
    assert (intent.adults, intent.children, intent.infants, intent.passengers) == (2, 1, 1, 4)
    assert intent.currency == "RUB"
    with pytest.raises(FrozenInstanceError):
        intent.adults = 3  # type: ignore[misc]


def test_plan_budget_rejects_non_positive_or_non_integer_units() -> None:
    assert PlanBudget(logical_operations=60, http_attempts=180, deadline_seconds=600) == (
        PlanBudget(logical_operations=60, http_attempts=180, deadline_seconds=600)
    )

    with pytest.raises(ValueError, match="plan budgets must be positive"):
        PlanBudget(logical_operations=-1, http_attempts=180, deadline_seconds=600)
    with pytest.raises(ValueError, match="plan budgets must be positive"):
        PlanBudget(logical_operations=60, http_attempts=0, deadline_seconds=600)
    with pytest.raises(TypeError, match="plan budgets must be integers"):
        PlanBudget(logical_operations=True, http_attempts=180, deadline_seconds=600)


def test_provider_capability_snapshot_keeps_tri_state_contract_and_cost_model() -> None:
    cost_model = ProviderHttpCostModel(
        version="aviasales-v1",
        start_attempts=3,
        poll_rounds=8,
        attempts_per_poll=3,
    )

    snapshot = ProviderCapabilitySnapshot(
        provider_id="aviasales_search",
        version="mobile-contract-2026-07-13",
        one_way=CapabilityState.SUPPORTED,
        round_trip=CapabilityState.SUPPORTED,
        native_open_jaw=CapabilityState.UNKNOWN,
        native_multi_city=CapabilityState.UNKNOWN,
        explicit_connection_protection=CapabilityState.UNKNOWN,
        airport_location_semantics=CapabilityState.SUPPORTED,
        city_location_semantics=CapabilityState.UNSUPPORTED,
        cost_model=cost_model,
    )

    assert tuple(CapabilityState) == (
        CapabilityState.SUPPORTED,
        CapabilityState.UNSUPPORTED,
        CapabilityState.UNKNOWN,
    )
    assert snapshot.native_multi_city is CapabilityState.UNKNOWN
    assert snapshot.city_location_semantics is CapabilityState.UNSUPPORTED
    assert snapshot.cost_model.worst_case_exact_http_attempts == 27
