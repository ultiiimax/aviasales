from __future__ import annotations

from flight_hunter.domain.offers import SearchIntent, TripType
from flight_hunter.providers.aviasales_data.query_planner import (
    AviasalesDataEndpoint,
    AviasalesDataPlanCode,
    AviasalesDataQueryPlanner,
)


def test_query_planner_builds_prices_for_dates_one_way_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan(
        SearchIntent(
            origin="waw",
            destination="bcn",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="rub",
            trip_type=TripType.ONE_WAY,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.PRICES_FOR_DATES
    assert plan.query is not None
    assert plan.query.origin == "WAW"
    assert plan.query.destination == "BCN"
    assert plan.query.one_way is True
    assert plan.query.return_at is None
    assert plan.degraded is False
    assert plan.degraded_reason is None


def test_query_planner_builds_prices_for_dates_round_trip_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan(
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.query is not None
    assert plan.query.one_way is False
    assert plan.query.return_at == "2026-10-19"


def test_query_planner_builds_grouped_prices_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_grouped_prices(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09",
            return_date=None,
            passengers=1,
            currency="RUB",
            trip_type=TripType.ONE_WAY,
        ),
        market="ru",
        group_by="departure_at",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.GROUPED_PRICES
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.departure_at == "2026-09"


def test_query_planner_builds_latest_prices_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_latest_prices(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-01",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        market="ru",
        period_type="month",
        group_by="dates",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.LATEST_PRICES
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.beginning_of_period == "2026-09-01"
    assert plan.query.one_way is False


def test_query_planner_builds_week_matrix_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_week_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.WEEK_MATRIX
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.depart_date == "2026-09-10"
    assert plan.query.return_date == "2026-09-20"
    assert plan.query.show_to_affiliates is True


def test_query_planner_builds_month_matrix_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_month_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.MONTH_MATRIX
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.month == "2026-09-01"
    assert plan.query.one_way is False
    assert plan.query.trip_duration_weeks == 1


def test_query_planner_builds_nearest_places_matrix_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_nearest_places_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        distance_km=300,
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.NEAREST_PLACES_MATRIX
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.currency == "RUB"
    assert plan.query.show_to_affiliates is True
    assert plan.query.distance_km == 300
    assert plan.query.limit == 30


def test_query_planner_builds_search_by_price_range_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_search_by_price_range(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date=None,
            passengers=1,
            currency="RUB",
            trip_type=TripType.ONE_WAY,
        ),
        value_min=10_000,
        value_max=20_000,
        market="ru",
        locale="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.SEARCH_BY_PRICE_RANGE
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.value_min == 10_000
    assert plan.query.value_max == 20_000
    assert plan.query.one_way is True
    assert plan.query.locale == "ru"


def test_query_planner_builds_popular_directions_query() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_popular_directions(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date=None,
            passengers=1,
            currency="RUB",
            trip_type=TripType.ONE_WAY,
        ),
        locale="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.POPULAR_DIRECTIONS
    assert plan.query is not None
    assert plan.query.destination == "IST"
    assert plan.query.currency == "RUB"
    assert plan.query.locale == "ru"
    assert plan.query.limit == 30


def test_query_planner_builds_special_offers_query_with_explicit_origin() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_special_offers(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
            trip_type=TripType.ROUND_TRIP,
        ),
        locale="ru",
    )

    assert plan.code == AviasalesDataPlanCode.PLANNED
    assert plan.endpoint == AviasalesDataEndpoint.SPECIAL_OFFERS
    assert plan.query is not None
    assert plan.query.origin == "MOW"
    assert plan.query.destination == "IST"
    assert plan.query.currency == "RUB"
    assert plan.query.locale == "ru"


def test_query_planner_rejects_invalid_search_by_price_range() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan_search_by_price_range(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date=None,
            passengers=1,
            currency="RUB",
            trip_type=TripType.ONE_WAY,
        ),
        value_min=20_000,
        value_max=10_000,
        market="ru",
        locale="ru",
    )

    assert plan.code == AviasalesDataPlanCode.INVALID_PRICE_RANGE
    assert plan.query is None


def test_query_planner_denies_multi_adult_pricing_until_price_basis_totals_supported() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan(
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            passengers=2,
            currency="RUB",
            adults=2,
            children=0,
            infants=0,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.UNSUPPORTED_PASSENGER_MIX
    assert plan.query is None
    assert "multi-passenger totals are not inferred" in plan.message


def test_query_planner_denies_child_or_infant_pricing_until_supported() -> None:
    planner = AviasalesDataQueryPlanner()

    plan = planner.plan(
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            passengers=3,
            currency="RUB",
            adults=2,
            children=1,
            infants=0,
        ),
        market="ru",
    )

    assert plan.code == AviasalesDataPlanCode.UNSUPPORTED_PASSENGER_MIX
    assert plan.query is None
    assert "single-adult-ticket prices" in plan.message
