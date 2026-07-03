from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import httpx2

from flight_hunter.ops.structured_logging import log_event


@dataclass(frozen=True, slots=True)
class PricesForDatesQuery:
    origin: str
    destination: str
    departure_at: str
    return_at: str | None
    currency: str
    market: str
    one_way: bool
    direct: bool
    limit: int
    page: int


@dataclass(frozen=True, slots=True)
class SearchByPriceRangeQuery:
    origin: str
    destination: str
    value_min: int
    value_max: int
    one_way: bool
    direct: bool
    locale: str
    currency: str
    market: str
    limit: int
    page: int


@dataclass(frozen=True, slots=True)
class GroupedPricesQuery:
    origin: str
    destination: str
    departure_at: str | None
    return_at: str | None
    currency: str
    market: str
    group_by: str
    direct: bool
    limit: int


@dataclass(frozen=True, slots=True)
class LatestPricesQuery:
    origin: str
    destination: str | None
    beginning_of_period: str
    period_type: str
    group_by: str
    one_way: bool
    currency: str
    market: str
    sorting: str
    page: int


@dataclass(frozen=True, slots=True)
class MonthMatrixQuery:
    origin: str
    destination: str
    month: str
    currency: str
    market: str
    show_to_affiliates: bool
    one_way: bool
    trip_duration_weeks: int | None
    limit: int


@dataclass(frozen=True, slots=True)
class NearestPlacesMatrixQuery:
    origin: str
    destination: str
    currency: str
    show_to_affiliates: bool
    distance_km: int
    limit: int


@dataclass(frozen=True, slots=True)
class PopularDirectionsQuery:
    destination: str
    locale: str
    currency: str
    limit: int
    page: int


@dataclass(frozen=True, slots=True)
class SpecialOffersQuery:
    origin: str
    destination: str
    locale: str
    currency: str


@dataclass(frozen=True, slots=True)
class WeekMatrixQuery:
    origin: str
    destination: str
    depart_date: str
    return_date: str | None
    currency: str
    market: str
    show_to_affiliates: bool


@dataclass(frozen=True, slots=True)
class AviasalesDataItem:
    origin: str
    destination: str
    origin_airport: str | None
    destination_airport: str | None
    price_minor_units: int
    currency: str
    departure_date: str
    return_date: str | None
    airline: str | None
    flight_number: str | None
    link_path: str | None
    found_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AviasalesDataResponse:
    received_at: datetime
    items: tuple[AviasalesDataItem, ...]
    rate_limit: AviasalesDataRateLimit | None = None


@dataclass(frozen=True, slots=True)
class AviasalesDataRateLimit:
    limit: int | None
    remaining: int | None
    reset: int | None


class AviasalesDataError(RuntimeError):
    """Raised when the cached Aviasales Data API response cannot be used safely."""


class AviasalesDataRateLimited(AviasalesDataError):
    def __init__(
        self,
        *,
        retry_after_seconds: int | None,
        rate_limit: AviasalesDataRateLimit | None = None,
    ) -> None:
        super().__init__("aviasales_data_rate_limited")
        self.retry_after_seconds = retry_after_seconds
        self.rate_limit = rate_limit


class AviasalesDataClient:
    def __init__(
        self,
        *,
        token: str,
        http_client: httpx2.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not token:
            raise ValueError("token is required")
        self._token = token
        self._client = http_client or httpx2.Client(
            base_url="https://api.travelpayouts.com",
            timeout=10.0,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    def prices_for_dates(self, query: PricesForDatesQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/prices_for_dates",
            params=_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        return AviasalesDataResponse(
            received_at=received_at,
            items=tuple(_parse_item(item, query.currency) for item in raw_items),
            rate_limit=_parse_rate_limit(response.headers),
        )

    def search_by_price_range(self, query: SearchByPriceRangeQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/search_by_price_range",
            params=_price_range_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        return AviasalesDataResponse(
            received_at=received_at,
            items=tuple(_parse_price_range_item(item, query.currency) for item in raw_items),
            rate_limit=_parse_rate_limit(response.headers),
        )

    def grouped_prices(self, query: GroupedPricesQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/grouped_prices",
            params=_grouped_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, dict):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        return AviasalesDataResponse(
            received_at=received_at,
            items=tuple(_parse_item(item, query.currency) for item in raw_items.values()),
            rate_limit=_parse_rate_limit(response.headers),
        )

    def latest_prices(self, query: LatestPricesQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/get_latest_prices",
            params=_latest_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        return AviasalesDataResponse(
            received_at=received_at,
            items=tuple(
                parsed
                for item in raw_items
                if (parsed := _parse_latest_item(item, query.currency)) is not None
            ),
            rate_limit=_parse_rate_limit(response.headers),
        )

    def week_matrix(self, query: WeekMatrixQuery) -> AviasalesDataResponse:
        response = self._get(
            "/v2/prices/week-matrix",
            params=_week_matrix_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        items = tuple(
            parsed
            for item in raw_items
            if (parsed := _parse_week_matrix_item(item, query.currency)) is not None
        )
        return AviasalesDataResponse(
            received_at=received_at,
            items=items,
            rate_limit=_parse_rate_limit(response.headers),
        )

    def month_matrix(self, query: MonthMatrixQuery) -> AviasalesDataResponse:
        response = self._get(
            "/v2/prices/month-matrix",
            params=_month_matrix_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        items = tuple(
            parsed
            for item in raw_items
            if (parsed := _parse_matrix_item(item, query.currency)) is not None
        )
        return AviasalesDataResponse(
            received_at=received_at,
            items=items,
            rate_limit=_parse_rate_limit(response.headers),
        )

    def nearest_places_matrix(self, query: NearestPlacesMatrixQuery) -> AviasalesDataResponse:
        response = self._get(
            "/v2/prices/nearest-places-matrix",
            params=_nearest_places_matrix_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True and "prices" not in payload:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if raw_items is None:
            raw_items = payload.get("prices")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        items = tuple(
            parsed
            for item in raw_items
            if (parsed := _parse_matrix_item(item, query.currency)) is not None
        )
        return AviasalesDataResponse(
            received_at=received_at,
            items=items,
            rate_limit=_parse_rate_limit(response.headers),
        )

    def special_offers(self, query: SpecialOffersQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/get_special_offers",
            params=_special_offers_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        currency = _optional_string(payload.get("currency")) or query.currency
        return AviasalesDataResponse(
            received_at=received_at,
            items=tuple(
                parsed
                for item in raw_items
                if (parsed := _parse_special_offer_item(item, currency)) is not None
            ),
            rate_limit=_parse_rate_limit(response.headers),
        )

    def popular_directions(self, query: PopularDirectionsQuery) -> AviasalesDataResponse:
        response = self._get(
            "/aviasales/v3/get_popular_directions",
            params=_popular_directions_query_params(query),
        )
        if response.status_code == 429:
            raise AviasalesDataRateLimited(
                retry_after_seconds=_parse_retry_after(response.headers.get("Retry-After")),
                rate_limit=_parse_rate_limit(response.headers),
            )
        if response.status_code >= 400:
            raise AviasalesDataError(f"aviasales_data_http_{response.status_code}")

        payload = response.json()
        if not isinstance(payload, dict):
            raise AviasalesDataError("aviasales_data_invalid_payload")
        if payload.get("success") is not True:
            raise AviasalesDataError("aviasales_data_unsuccessful")

        raw_data = payload.get("data")
        if not isinstance(raw_data, dict):
            raise AviasalesDataError("aviasales_data_invalid_data")
        raw_items = raw_data.get("origin")
        if not isinstance(raw_items, list):
            raise AviasalesDataError("aviasales_data_invalid_data")

        received_at = self._clock()
        currency = _optional_string(payload.get("currency")) or query.currency
        items = tuple(
            _parse_popular_direction_item(item, query.destination, currency) for item in raw_items
        )
        return AviasalesDataResponse(
            received_at=received_at,
            items=items,
            rate_limit=_parse_rate_limit(response.headers),
        )

    def _get(self, path: str, *, params: Mapping[str, str | int]) -> httpx2.Response:
        started_at = perf_counter()
        status_code: int | None = None
        error_class: str | None = None
        try:
            response = self._client.get(
                path,
                params=params,
                headers={"X-Access-Token": self._token},
            )
            status_code = response.status_code
            return response
        except httpx2.HTTPError as exc:
            error_class = exc.__class__.__name__
            raise
        finally:
            log_event(
                "provider_call",
                provider="aviasales_data",
                endpoint=_endpoint_name(path),
                status_code=status_code,
                error_class=error_class,
                duration_ms=max(0, int((perf_counter() - started_at) * 1000)),
            )


def _endpoint_name(path: str) -> str:
    return {
        "/aviasales/v3/prices_for_dates": "prices_for_dates",
        "/aviasales/v3/search_by_price_range": "search_by_price_range",
        "/aviasales/v3/grouped_prices": "grouped_prices",
        "/aviasales/v3/get_latest_prices": "latest_prices",
        "/v2/prices/week-matrix": "week_matrix",
        "/v2/prices/month-matrix": "month_matrix",
        "/v2/prices/nearest-places-matrix": "nearest_places_matrix",
        "/aviasales/v3/get_special_offers": "special_offers",
        "/aviasales/v3/get_popular_directions": "popular_directions",
    }.get(path, path.strip("/").replace("/", "_").replace("-", "_"))


def _query_params(query: PricesForDatesQuery) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "departure_at": query.departure_at,
        "one_way": _bool_param(query.one_way),
        "direct": _bool_param(query.direct),
        "market": query.market.lower(),
        "cy": query.currency.lower(),
        "limit": query.limit,
        "page": query.page,
        "sorting": "price",
        "unique": "false",
    }
    if query.return_at is not None:
        params["return_at"] = query.return_at
    return params


def _price_range_query_params(query: SearchByPriceRangeQuery) -> dict[str, str | int]:
    return {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "value_min": query.value_min,
        "value_max": query.value_max,
        "one_way": _bool_param(query.one_way),
        "direct": _bool_param(query.direct),
        "locale": query.locale.lower(),
        "currency": query.currency.lower(),
        "market": query.market.lower(),
        "limit": query.limit,
        "page": query.page,
    }


def _grouped_query_params(query: GroupedPricesQuery) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "market": query.market.lower(),
        "cy": query.currency.lower(),
        "group_by": query.group_by,
        "direct": _bool_param(query.direct),
        "limit": query.limit,
    }
    if query.departure_at is not None:
        params["departure_at"] = query.departure_at
    if query.return_at is not None:
        params["return_at"] = query.return_at
    return params


def _latest_query_params(query: LatestPricesQuery) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "origin": query.origin.upper(),
        "beginning_of_period": query.beginning_of_period,
        "period_type": query.period_type,
        "group_by": query.group_by,
        "one_way": _bool_param(query.one_way),
        "cy": query.currency.lower(),
        "market": query.market.lower(),
        "sorting": query.sorting,
        "page": query.page,
    }
    if query.destination is not None:
        params["destination"] = query.destination.upper()
    return params


def _week_matrix_query_params(query: WeekMatrixQuery) -> dict[str, str]:
    params = {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "depart_date": query.depart_date,
        "currency": query.currency.lower(),
        "market": query.market.lower(),
        "show_to_affiliates": _bool_param(query.show_to_affiliates),
    }
    if query.return_date is not None:
        params["return_date"] = query.return_date
    return params


def _month_matrix_query_params(query: MonthMatrixQuery) -> dict[str, str | int]:
    params: dict[str, str | int] = {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "month": query.month,
        "currency": query.currency.lower(),
        "market": query.market.lower(),
        "show_to_affiliates": _bool_param(query.show_to_affiliates),
        "one_way": _bool_param(query.one_way),
        "limit": query.limit,
    }
    if query.trip_duration_weeks is not None:
        params["trip_duration"] = query.trip_duration_weeks
    return params


def _nearest_places_matrix_query_params(query: NearestPlacesMatrixQuery) -> dict[str, str | int]:
    return {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "currency": query.currency.lower(),
        "show_to_affiliates": _bool_param(query.show_to_affiliates),
        "distance": query.distance_km,
        "limit": query.limit,
    }


def _popular_directions_query_params(query: PopularDirectionsQuery) -> dict[str, str | int]:
    return {
        "destination": query.destination.upper(),
        "locale": query.locale.lower(),
        "currency": query.currency.lower(),
        "limit": query.limit,
        "page": query.page,
    }


def _special_offers_query_params(query: SpecialOffersQuery) -> dict[str, str]:
    return {
        "origin": query.origin.upper(),
        "destination": query.destination.upper(),
        "locale": query.locale.lower(),
        "currency": query.currency.lower(),
    }


def _parse_item(raw: Any, currency: str) -> AviasalesDataItem:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    price = _required_major_units(raw.get("price"), "price")
    departure_at = _required_string(raw.get("departure_at"), "departure_at")
    return_at = raw.get("return_at")
    if return_at is not None and not isinstance(return_at, str):
        return_at = None

    return AviasalesDataItem(
        origin=_required_string(raw.get("origin"), "origin").upper(),
        destination=_required_string(raw.get("destination"), "destination").upper(),
        origin_airport=_optional_upper(raw.get("origin_airport")),
        destination_airport=_optional_upper(raw.get("destination_airport")),
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=departure_at[:10],
        return_date=_date_prefix_or_none(return_at),
        airline=_optional_upper(raw.get("airline")),
        flight_number=_optional_string(raw.get("flight_number")),
        link_path=_optional_string(raw.get("link")),
    )


def _parse_price_range_item(raw: Any, currency: str) -> AviasalesDataItem:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    price = _required_major_units(raw.get("price"), "price")
    departure_at = _required_string(raw.get("departure_at"), "departure_at")

    return AviasalesDataItem(
        origin=_required_string(raw.get("origin_code") or raw.get("origin"), "origin").upper(),
        destination=_required_string(
            raw.get("destination_code") or raw.get("destination"),
            "destination",
        ).upper(),
        origin_airport=_optional_upper(raw.get("origin_airport")),
        destination_airport=_optional_upper(raw.get("destination_airport")),
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=departure_at[:10],
        return_date=None,
        airline=_optional_upper(raw.get("airline")),
        flight_number=_optional_string(raw.get("flight_number")),
        link_path=_optional_string(raw.get("link")),
    )


def _parse_latest_item(raw: Any, currency: str) -> AviasalesDataItem | None:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    if raw.get("actual") is False:
        return None
    price = _required_major_units(raw.get("value", raw.get("price")), "price")
    departure_at = raw.get("depart_date", raw.get("departure_at"))
    departure_date = _required_string(departure_at, "departure_at")
    return_at = raw.get("return_date", raw.get("return_at"))
    if return_at is not None and not isinstance(return_at, str):
        return_at = None

    return AviasalesDataItem(
        origin=_required_string(raw.get("origin"), "origin").upper(),
        destination=_required_string(raw.get("destination"), "destination").upper(),
        origin_airport=_optional_upper(raw.get("origin_airport")),
        destination_airport=_optional_upper(raw.get("destination_airport")),
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=departure_date[:10],
        return_date=_date_prefix_or_none(return_at),
        airline=_optional_upper(raw.get("airline")),
        flight_number=_optional_string(raw.get("flight_number")),
        link_path=_optional_string(raw.get("link")),
        found_at=_optional_datetime(raw.get("found_at")),
    )


def _parse_week_matrix_item(raw: Any, currency: str) -> AviasalesDataItem | None:
    return _parse_matrix_item(raw, currency)


def _parse_matrix_item(raw: Any, currency: str) -> AviasalesDataItem | None:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    if raw.get("actual") is False:
        return None
    price = _required_major_units(raw.get("value"), "value")
    depart_date = _required_string(raw.get("depart_date"), "depart_date")
    return_date = raw.get("return_date")
    if return_date is not None and not isinstance(return_date, str):
        return_date = None

    return AviasalesDataItem(
        origin=_required_string(raw.get("origin"), "origin").upper(),
        destination=_required_string(raw.get("destination"), "destination").upper(),
        origin_airport=None,
        destination_airport=None,
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=depart_date[:10],
        return_date=_date_prefix_or_none(return_date),
        airline=None,
        flight_number=None,
        link_path=None,
        found_at=_optional_datetime(raw.get("found_at")),
    )


def _parse_popular_direction_item(
    raw: Any,
    destination: str,
    currency: str,
) -> AviasalesDataItem:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    price = _required_major_units(raw.get("price"), "price")
    departure_at = _required_string(raw.get("departure_at"), "departure_at")
    return_at = raw.get("return_at")
    if not isinstance(return_at, str) or not return_at:
        return_at = None

    return AviasalesDataItem(
        origin=_required_string(raw.get("city_iata") or raw.get("origin"), "origin").upper(),
        destination=destination.upper(),
        origin_airport=None,
        destination_airport=None,
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=departure_at[:10],
        return_date=_date_prefix_or_none(return_at),
        airline=None,
        flight_number=None,
        link_path=None,
    )


def _parse_special_offer_item(raw: Any, currency: str) -> AviasalesDataItem | None:
    if not isinstance(raw, dict):
        raise AviasalesDataError("aviasales_data_invalid_item")
    if raw.get("actual") is False:
        return None
    price = _required_major_units(raw.get("price", raw.get("value")), "price")
    departure_at = raw.get("departure_at", raw.get("depart_date"))
    departure_date = _required_string(departure_at, "departure_at")
    return_at = raw.get("return_at", raw.get("return_date"))
    if return_at is not None and not isinstance(return_at, str):
        return_at = None

    return AviasalesDataItem(
        origin=_required_string(raw.get("origin") or raw.get("origin_code"), "origin").upper(),
        destination=_required_string(
            raw.get("destination") or raw.get("destination_code"),
            "destination",
        ).upper(),
        origin_airport=_optional_upper(raw.get("origin_airport")),
        destination_airport=_optional_upper(raw.get("destination_airport")),
        price_minor_units=price * 100,
        currency=currency.upper(),
        departure_date=departure_date[:10],
        return_date=_date_prefix_or_none(return_at),
        airline=_optional_upper(raw.get("airline")),
        flight_number=_optional_string(raw.get("flight_number")),
        link_path=None,
        found_at=_optional_datetime(raw.get("found_at")),
    )


def stable_item_id(item: AviasalesDataItem) -> str:
    raw = "|".join(
        (
            item.origin,
            item.destination,
            item.departure_date,
            item.return_date or "",
            str(item.price_minor_units),
            item.currency,
            item.airline or "",
            item.flight_number or "",
        )
    )
    return "aviasales_data:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AviasalesDataError(f"aviasales_data_missing_{field_name}")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_upper(value: Any) -> str | None:
    return value.upper() if isinstance(value, str) and value else None


def _required_major_units(value: Any, field_name: str) -> int:
    if type(value) is int:
        return value
    if type(value) is float and value.is_integer():
        return int(value)
    raise AviasalesDataError(f"aviasales_data_missing_{field_name}")


def _date_prefix_or_none(value: str | None) -> str | None:
    return value[:10] if isinstance(value, str) and value else None


def _optional_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _bool_param(value: bool) -> str:
    return "true" if value else "false"


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        retry_after = int(value)
    except ValueError:
        return None
    return retry_after if retry_after >= 0 else None


def _parse_rate_limit(headers: Any) -> AviasalesDataRateLimit | None:
    limit = _parse_nonnegative_int(headers.get("X-Rate-Limit"))
    remaining = _parse_nonnegative_int(headers.get("X-Rate-Limit-Remaining"))
    reset = _parse_nonnegative_int(headers.get("X-Rate-Limit-Reset"))
    if limit is None and remaining is None and reset is None:
        return None
    return AviasalesDataRateLimit(limit=limit, remaining=remaining, reset=reset)


def _parse_nonnegative_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
