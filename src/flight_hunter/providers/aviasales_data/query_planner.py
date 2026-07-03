from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from flight_hunter.domain.offers import SearchIntent, TripType
from flight_hunter.providers.aviasales_data.client import (
    GroupedPricesQuery,
    LatestPricesQuery,
    MonthMatrixQuery,
    NearestPlacesMatrixQuery,
    PopularDirectionsQuery,
    PricesForDatesQuery,
    SearchByPriceRangeQuery,
    SpecialOffersQuery,
    WeekMatrixQuery,
)


class AviasalesDataEndpoint(StrEnum):
    PRICES_FOR_DATES = "prices_for_dates"
    SEARCH_BY_PRICE_RANGE = "search_by_price_range"
    GROUPED_PRICES = "grouped_prices"
    LATEST_PRICES = "latest_prices"
    WEEK_MATRIX = "week_matrix"
    MONTH_MATRIX = "month_matrix"
    NEAREST_PLACES_MATRIX = "nearest_places_matrix"
    POPULAR_DIRECTIONS = "popular_directions"
    SPECIAL_OFFERS = "special_offers"


class AviasalesDataPlanCode(StrEnum):
    PLANNED = "planned"
    UNSUPPORTED_PASSENGER_MIX = "unsupported_passenger_mix"
    INVALID_PRICE_RANGE = "invalid_price_range"


@dataclass(frozen=True, slots=True)
class AviasalesDataQueryPlan:
    code: AviasalesDataPlanCode
    endpoint: AviasalesDataEndpoint | None
    query: (
        GroupedPricesQuery
        | LatestPricesQuery
        | MonthMatrixQuery
        | NearestPlacesMatrixQuery
        | PopularDirectionsQuery
        | PricesForDatesQuery
        | SearchByPriceRangeQuery
        | SpecialOffersQuery
        | WeekMatrixQuery
        | None
    )
    degraded: bool
    degraded_reason: str | None
    message: str


class AviasalesDataQueryPlanner:
    def plan(self, intent: SearchIntent, *, market: str) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        trip_type_value = intent.trip_type
        if trip_type_value is None:
            trip_type = TripType.ROUND_TRIP if intent.return_date is not None else TripType.ONE_WAY
        elif isinstance(trip_type_value, TripType):
            trip_type = trip_type_value
        else:
            trip_type = TripType(trip_type_value)
        query = PricesForDatesQuery(
            origin=intent.origin,
            destination=intent.destination,
            departure_at=intent.departure_date,
            return_at=intent.return_date,
            currency=intent.currency,
            market=market,
            one_way=trip_type == TripType.ONE_WAY,
            direct=False,
            limit=30,
            page=1,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.PRICES_FOR_DATES,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="exact-date prices_for_dates query planned",
        )

    def plan_grouped_prices(
        self,
        intent: SearchIntent,
        *,
        market: str,
        group_by: str = "departure_at",
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        query = GroupedPricesQuery(
            origin=intent.origin,
            destination=intent.destination,
            departure_at=intent.departure_date,
            return_at=intent.return_date,
            currency=intent.currency,
            market=market,
            group_by=group_by,
            direct=False,
            limit=30,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.GROUPED_PRICES,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached grouped_prices query planned",
        )

    def plan_search_by_price_range(
        self,
        intent: SearchIntent,
        *,
        value_min: int,
        value_max: int,
        market: str,
        locale: str,
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers
        if value_min < 0 or value_max < value_min:
            return AviasalesDataQueryPlan(
                code=AviasalesDataPlanCode.INVALID_PRICE_RANGE,
                endpoint=None,
                query=None,
                degraded=False,
                degraded_reason=None,
                message="search_by_price_range requires a non-negative ascending price range",
            )

        trip_type_value = intent.trip_type
        if trip_type_value is None:
            trip_type = TripType.ROUND_TRIP if intent.return_date is not None else TripType.ONE_WAY
        elif isinstance(trip_type_value, TripType):
            trip_type = trip_type_value
        else:
            trip_type = TripType(trip_type_value)
        query = SearchByPriceRangeQuery(
            origin=intent.origin,
            destination=intent.destination,
            value_min=value_min,
            value_max=value_max,
            one_way=trip_type == TripType.ONE_WAY,
            direct=False,
            locale=locale,
            currency=intent.currency,
            market=market,
            limit=30,
            page=1,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.SEARCH_BY_PRICE_RANGE,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached search_by_price_range query planned",
        )

    def plan_latest_prices(
        self,
        intent: SearchIntent,
        *,
        market: str,
        period_type: str = "month",
        group_by: str = "dates",
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        trip_type_value = intent.trip_type
        if trip_type_value is None:
            trip_type = TripType.ROUND_TRIP if intent.return_date is not None else TripType.ONE_WAY
        elif isinstance(trip_type_value, TripType):
            trip_type = trip_type_value
        else:
            trip_type = TripType(trip_type_value)
        query = LatestPricesQuery(
            origin=intent.origin,
            destination=intent.destination,
            beginning_of_period=intent.departure_date,
            period_type=period_type,
            group_by=group_by,
            one_way=trip_type == TripType.ONE_WAY,
            currency=intent.currency,
            market=market,
            sorting="price",
            page=1,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.LATEST_PRICES,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached latest_prices query planned",
        )

    def plan_week_matrix(
        self,
        intent: SearchIntent,
        *,
        market: str,
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        query = WeekMatrixQuery(
            origin=intent.origin,
            destination=intent.destination,
            depart_date=intent.departure_date,
            return_date=intent.return_date,
            currency=intent.currency,
            market=market,
            show_to_affiliates=True,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.WEEK_MATRIX,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached week-matrix query planned",
        )

    def plan_month_matrix(
        self,
        intent: SearchIntent,
        *,
        market: str,
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        one_way = intent.return_date is None
        query = MonthMatrixQuery(
            origin=intent.origin,
            destination=intent.destination,
            month=_month_start(intent.departure_date),
            currency=intent.currency,
            market=market,
            show_to_affiliates=True,
            one_way=one_way,
            trip_duration_weeks=None
            if one_way
            else _trip_duration_weeks(
                intent.departure_date,
                intent.return_date,
            ),
            limit=30,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.MONTH_MATRIX,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached month-matrix query planned",
        )

    def plan_nearest_places_matrix(
        self,
        intent: SearchIntent,
        *,
        distance_km: int = 300,
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        query = NearestPlacesMatrixQuery(
            origin=intent.origin,
            destination=intent.destination,
            currency=intent.currency,
            show_to_affiliates=True,
            distance_km=distance_km,
            limit=30,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.NEAREST_PLACES_MATRIX,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached nearest-places-matrix query planned",
        )

    def plan_popular_directions(
        self,
        intent: SearchIntent,
        *,
        locale: str = "en",
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        query = PopularDirectionsQuery(
            destination=intent.destination,
            locale=locale,
            currency=intent.currency,
            limit=30,
            page=1,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.POPULAR_DIRECTIONS,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached popular-directions query planned",
        )

    def plan_special_offers(
        self,
        intent: SearchIntent,
        *,
        locale: str = "en",
    ) -> AviasalesDataQueryPlan:
        unsupported_passengers = _unsupported_passengers(intent)
        if unsupported_passengers is not None:
            return unsupported_passengers

        query = SpecialOffersQuery(
            origin=intent.origin,
            destination=intent.destination,
            locale=locale,
            currency=intent.currency,
        )
        return AviasalesDataQueryPlan(
            code=AviasalesDataPlanCode.PLANNED,
            endpoint=AviasalesDataEndpoint.SPECIAL_OFFERS,
            query=query,
            degraded=False,
            degraded_reason=None,
            message="cached special-offers query planned",
        )


def _month_start(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value[:7] + "-01" if len(value) >= 7 else value
    return parsed.replace(day=1).isoformat()


def _unsupported_passengers(intent: SearchIntent) -> AviasalesDataQueryPlan | None:
    if intent.passengers == 1 and intent.children == 0 and intent.infants == 0:
        return None
    return AviasalesDataQueryPlan(
        code=AviasalesDataPlanCode.UNSUPPORTED_PASSENGER_MIX,
        endpoint=None,
        query=None,
        degraded=False,
        degraded_reason=None,
        message=(
            "Aviasales Data cached prices are treated as provider single-adult-ticket prices; "
            "multi-passenger totals are not inferred"
        ),
    )


def _trip_duration_weeks(departure_date: str, return_date: str | None) -> int | None:
    if return_date is None:
        return None
    try:
        departure = date.fromisoformat(departure_date)
        returning = date.fromisoformat(return_date)
    except ValueError:
        return None
    stay_days = (returning - departure).days
    if stay_days <= 0:
        return None
    return max(1, round(stay_days / 7))
