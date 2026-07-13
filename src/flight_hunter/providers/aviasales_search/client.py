from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter, sleep
from typing import Any, Literal, Protocol, cast

from curl_cffi import requests as cc

from flight_hunter.domain.provider_errors import ProviderOperationError
from flight_hunter.ops.structured_logging import log_event

TICKETS_BASE = "https://tickets-api.aviasales.ru"
EXPLORE_BASE = "https://explore-api.aviasales.ru"
SUGGEST_BASE = "https://suggest.aviasales.ru"
ARIADNE_BASE = "https://ariadne.aviasales.ru"
DEFAULT_USER_AGENT = "Aviasales/7.24.0 (Android; 14; Pixel_8) okhttp/5.3.2"
DEFAULT_IMPERSONATE: Literal["chrome120"] = "chrome120"


class AviasalesSearchError(ProviderOperationError):
    """Raised when the Aviasales Search mobile API call cannot be used safely."""

    provider_id = "aviasales_search"
    code = "aviasales_search_unavailable"


class AviasalesSearchAuthFailed(AviasalesSearchError):
    """The configured mobile credentials were rejected (HTTP 401)."""

    code = "aviasales_search_auth_failed"


class AviasalesSearchBlocked(AviasalesSearchError):
    """CloudFront/WAF blocked the request (typically HTTP 403)."""

    code = "aviasales_search_blocked"


class AviasalesSearchSchemaError(AviasalesSearchError):
    """The provider response did not match the verified mobile contract."""

    code = "aviasales_search_schema_error"


class AviasalesSearchRateLimited(AviasalesSearchError):
    code = "aviasales_search_rate_limited"

    def __init__(self, *, retry_after_seconds: int | None) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True, slots=True)
class StartSearchResult:
    search_id: str
    results_url: str
    blet_url: str | None


@dataclass(frozen=True, slots=True)
class SearchStartParams:
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    adults: int
    children: int
    infants: int
    trip_class: str
    currency: str
    market: str


@dataclass(frozen=True, slots=True)
class SuggestPlace:
    code: str
    name: str
    place_type: str
    country_code: str | None


@dataclass(frozen=True, slots=True)
class HotOffer:
    origin: str
    destination: str
    departure_date: str | None
    return_date: str | None
    price_minor_units: int | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class CalendarPrice:
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    price_minor_units: int
    currency: str


@dataclass(frozen=True, slots=True)
class GraphqlFeedBlock:
    typename: str


class AviasalesSearchResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def content(self) -> bytes: ...
    def json(self) -> Any: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


class AviasalesSearchTransport(Protocol):
    def post(
        self,
        url: str,
        *,
        json: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse: ...

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse: ...


class CurlCffiTransport:
    """Real transport: curl_cffi with Chrome TLS impersonation to pass CloudFront."""

    def post(
        self,
        url: str,
        *,
        json: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse:
        return cast(
            AviasalesSearchResponse,
            cc.post(
                url,
                json=json,
                headers=dict(headers),
                impersonate=DEFAULT_IMPERSONATE,
                timeout=timeout,
            ),
        )

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse:
        return cast(
            AviasalesSearchResponse,
            cc.get(
                url,
                params=dict(params),
                headers=dict(headers),
                impersonate=DEFAULT_IMPERSONATE,
                timeout=timeout,
            ),
        )


class AviasalesSearchClient:
    def __init__(
        self,
        *,
        signature: str,
        marker: str,
        transport: AviasalesSearchTransport | None = None,
        base_url: str = TICKETS_BASE,
        suggest_base_url: str = SUGGEST_BASE,
        explore_base_url: str = EXPLORE_BASE,
        ariadne_base_url: str = ARIADNE_BASE,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        max_retries: int = 2,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        if not signature:
            raise ValueError("signature is required")
        if not marker:
            raise ValueError("marker is required")
        self._signature = signature
        self._marker = marker
        self._transport = transport or CurlCffiTransport()
        self._base_url = base_url.rstrip("/")
        self._suggest_base_url = suggest_base_url.rstrip("/")
        self._explore_base_url = explore_base_url.rstrip("/")
        self._ariadne_base_url = ariadne_base_url.rstrip("/")
        self._timeout = timeout
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_retries = max_retries
        self._sleep = sleep_fn or sleep
        self._headers: dict[str, str] = {
            "User-Agent": user_agent,
            "X-Client-Type": "mobile",
            "Referer": "https://www.aviasales.ru/",
            "Accept": "application/json",
            "X-Signature": signature,
        }

    def start_search(self, params: SearchStartParams) -> StartSearchResult:
        directions = [
            {
                "origin": params.origin.upper(),
                "destination": params.destination.upper(),
                "date": params.departure_date,
                "is_origin_airport": False,
                "is_destination_airport": False,
            }
        ]
        if params.return_date is not None:
            directions.append(
                {
                    "origin": params.destination.upper(),
                    "destination": params.origin.upper(),
                    "date": params.return_date,
                    "is_origin_airport": False,
                    "is_destination_airport": False,
                }
            )
        body = {
            "search_params": {
                "directions": directions,
                "passengers": {
                    "adults": params.adults,
                    "children": params.children,
                    "infants": params.infants,
                },
                "trip_class": params.trip_class,
            },
            "marker": self._marker,
            "market_code": params.market,
            "currency_code": params.currency.upper(),
            "languages": {"ru": 1.0},
            "debug": {},
            "brand": "AS",
            "search_source": "mobile",
            "filters": {},
        }
        response = self._request("POST", "/search/v2/start", json_body=body)
        payload = _json_object(response)
        search_id = _require_str(payload.get("search_id"), "search_id")
        results_url = _require_str(payload.get("results_url"), "results_url")
        blet_url = payload.get("blet_url")
        return StartSearchResult(
            search_id=search_id,
            results_url=results_url,
            blet_url=str(blet_url) if isinstance(blet_url, str) and blet_url else None,
        )

    def poll_results(
        self,
        results_url: str,
        search_id: str,
        *,
        rounds: int = 8,
        delay: float = 2.0,
        limit: int = 50,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        host = results_url.split("/")[0]
        poll_url = f"https://{host}/search/v3.2/results"
        req_id = request_id or str(uuid.uuid4())
        chunks: list[dict[str, Any]] = []
        last_ts = 0
        for _ in range(rounds):
            body = {
                "search_id": search_id,
                "limit": limit,
                "last_update_timestamp": last_ts,
                "required_tickets": [],
                "highlighted_ticket": None,
                "search_by_airport": False,
                "price_per_person": False,
                "filters_state": {},
            }
            response = self._request(
                "POST",
                poll_url,
                json_body=body,
                extra_headers={"X-Request-Id": req_id},
                full_url=True,
            )
            parsed = _json_value(response)
            if not isinstance(parsed, list):
                raise AviasalesSearchSchemaError()
            for chunk in parsed:
                if not isinstance(chunk, dict):
                    raise AviasalesSearchSchemaError()
                chunks.append(chunk)
                ts = chunk.get("last_update_timestamp")
                if isinstance(ts, int):
                    last_ts = max(last_ts, ts)
            if any(isinstance(c, dict) and c.get("tickets") for c in chunks):
                break
            self._sleep(delay)
        return chunks

    def get_purchase_url(
        self,
        search_id: str,
        proposal_id: str,
        results_url: str,
        *,
        blet_request_id: str | None = None,
    ) -> str | None:
        host = results_url.split("/")[0]
        url = f"{self._base_url}/searches/{search_id}/clicks/{proposal_id}"
        params = {
            "marker": self._marker,
            "host": host,
            "blet_request_id": blet_request_id or str(uuid.uuid4()),
        }
        response = self._request("GET", url, params=params, full_url=True)
        if response.status_code != 200 or not response.content:
            return None
        payload = response.json()
        if isinstance(payload, dict):
            link = payload.get("url")
            if isinstance(link, str) and link:
                return link
        return None

    def suggest_places(
        self,
        term: str,
        *,
        locale: str = "ru",
        place_types: tuple[str, ...] = ("city", "airport"),
        max_results: int = 5,
    ) -> tuple[SuggestPlace, ...]:
        response = self._request(
            "GET",
            f"{self._suggest_base_url}/v2/places.json",
            params={
                "term": term,
                "locale": locale,
                "types[]": list(place_types),
                "max": max_results,
                "marker": self._marker,
            },
            full_url=True,
        )
        return tuple(_parse_suggest_place(item) for item in _iter_items(_json_value(response)))

    def hot_offers(
        self,
        *,
        origin: str,
        origin_type: str = "city",
        market: str = "RU",
        passport_country: str = "RU",
        currency: str = "rub",
        one_way: bool = True,
    ) -> tuple[HotOffer, ...]:
        response = self._request(
            "GET",
            f"{self._explore_base_url}/v1/hot_offers/list.json",
            params={
                "origin": origin.upper(),
                "origin_type": origin_type,
                "market": market,
                "passport_country": passport_country,
                "language": "ru",
                "currency": currency.lower(),
                "one_way": str(one_way).lower(),
                "sort_type": "price",
                "marker": self._marker,
            },
            full_url=True,
        )
        return tuple(
            _parse_hot_offer(item, default_currency=currency)
            for item in _iter_items(_json_value(response))
        )

    def calendar_prices(
        self,
        *,
        origin: str,
        destination: str,
        depart_from: str,
        depart_to: str,
        one_way: bool,
        currency: str = "rub",
    ) -> tuple[CalendarPrice, ...]:
        response = self._request(
            "GET",
            f"{self._explore_base_url}/api/v6/calendar.json",
            params={
                "origin_iata": origin.upper(),
                "origin_type": "city",
                "destination_iata": destination.upper(),
                "destination_type": "city",
                "one_way": str(one_way).lower(),
                "depart_date_from": depart_from,
                "depart_date_to": depart_to,
                "currency": currency.lower(),
                "locale": "ru",
                "trip_class": "Y",
                "marker": self._marker,
            },
            full_url=True,
        )
        return tuple(
            price
            for item in _iter_items(_json_value(response))
            if (
                price := _parse_calendar_price(
                    item,
                    default_origin=origin,
                    default_destination=destination,
                    default_currency=currency,
                )
            )
            is not None
        )

    def main_page_blocks(
        self,
        *,
        origin: str,
        origin_type: str = "CITY",
        market: str = "RU",
        currency: str = "rub",
        language: str = "ru",
        one_way: bool = True,
    ) -> tuple[GraphqlFeedBlock, ...]:
        query = (
            "query MainPageBlocksV1($brand: Brand!, $application: Application!, "
            "$citiesLimit: Int!, $countriesLimit: Int!, $currency: String!, "
            "$language: String!, $market: String!, $oneWay: Boolean!, "
            "$origin: String!, $originType: PlaceType!, $passportCountry: String!, "
            "$tripClass: TripClass!, $features: MainScreenFeatures!) { "
            "mainPageBlocksV1: main_page_blocks_v1(input: { application: $application "
            "cities_limit: $citiesLimit countries_limit: $countriesLimit "
            "currency: $currency language: $language market: $market one_way: $oneWay "
            "origin: $origin origin_type: $originType passport_country: $passportCountry "
            "trip_class: $tripClass features: $features }, brand: $brand) { "
            "blocks { __typename } } }"
        )
        variables = {
            "brand": "AS",
            "application": "aviasales",
            "citiesLimit": 5,
            "countriesLimit": 3,
            "currency": currency.lower(),
            "language": language,
            "market": market,
            "oneWay": one_way,
            "origin": origin.upper(),
            "originType": origin_type.upper(),
            "passportCountry": "RU",
            "tripClass": "Y",
            "features": {
                "useNewCalendar": False,
                "useNewAiSearch": False,
                "useHotTicketsV2": False,
                "useWeekendsV2": False,
            },
        }
        response = self._request(
            "POST",
            f"{self._ariadne_base_url}/api/gql",
            json_body={
                "operationName": "MainPageBlocksV1",
                "query": query,
                "variables": variables,
            },
            extra_headers={"Content-Type": "application/json"},
            full_url=True,
        )
        payload = _json_object(response)
        data = payload.get("data")
        if not isinstance(data, dict):
            return ()
        block_container = data.get("mainPageBlocksV1") or data.get("main_page_blocks_v1")
        if not isinstance(block_container, dict):
            return ()
        blocks = block_container.get("blocks")
        if not isinstance(blocks, list):
            return ()
        return tuple(
            GraphqlFeedBlock(typename=typename)
            for block in blocks
            if isinstance(block, dict)
            if isinstance((typename := block.get("__typename")), str) and typename
        )

    def _request(
        self,
        method: str,
        target: str,
        *,
        json_body: Any = None,
        params: Mapping[str, Any] | None = None,
        extra_headers: Mapping[str, str] | None = None,
        full_url: bool = False,
    ) -> AviasalesSearchResponse:
        url = target if full_url else self._base_url + target
        headers: dict[str, str] = dict(self._headers)
        if extra_headers:
            headers.update(extra_headers)
        last_error: str | None = None
        for attempt in range(self._max_retries + 1):
            started = perf_counter()
            status: int | None = None
            error_class: str | None = None
            try:
                if method == "POST":
                    response = self._transport.post(
                        url, json=json_body, headers=headers, timeout=self._timeout
                    )
                else:
                    response = self._transport.get(
                        url, params=params or {}, headers=headers, timeout=self._timeout
                    )
                status = response.status_code
                if status == 401:
                    log_event(
                        "provider_call",
                        provider="aviasales_search",
                        endpoint=_endpoint_name(target),
                        status_code=status,
                        error_class="auth_failed",
                        duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    )
                    raise AviasalesSearchAuthFailed()
                if status == 403:
                    log_event(
                        "provider_call",
                        provider="aviasales_search",
                        endpoint=_endpoint_name(target),
                        status_code=status,
                        error_class="blocked",
                        duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    )
                    raise AviasalesSearchBlocked()
                if status == 429:
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    log_event(
                        "provider_call",
                        provider="aviasales_search",
                        endpoint=_endpoint_name(target),
                        status_code=status,
                        error_class="rate_limited",
                        duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    )
                    raise AviasalesSearchRateLimited(retry_after_seconds=retry_after)
                if status >= 500 and attempt < self._max_retries:
                    last_error = f"http_{status}"
                    self._sleep(_backoff(attempt))
                    continue
                log_event(
                    "provider_call",
                    provider="aviasales_search",
                    endpoint=_endpoint_name(target),
                    status_code=status,
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )
                return response
            except AviasalesSearchError:
                raise
            except Exception as exc:  # provider transport boundary: classify + log
                error_class = exc.__class__.__name__
                last_error = error_class
                log_event(
                    "provider_call",
                    provider="aviasales_search",
                    endpoint=_endpoint_name(target),
                    status_code=status,
                    error_class=error_class,
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )
                if attempt < self._max_retries:
                    self._sleep(_backoff(attempt))
                    continue
                raise AviasalesSearchError(
                    f"aviasales_search_transport_error:{error_class}"
                ) from exc
        raise AviasalesSearchError(f"aviasales_search_failed:{last_error}")


def _backoff(attempt: int) -> float:
    return min(2.0**attempt, 4.0)


def _endpoint_name(target: str) -> str:
    if "/search/v2/start" in target:
        return "start_search"
    if "/search/v3.2/results" in target:
        return "poll_results"
    if "/clicks/" in target:
        return "clicks"
    return target.strip("/").replace("/", "_").replace("-", "_")


def _json_object(response: AviasalesSearchResponse) -> dict[str, Any]:
    payload = _json_value(response)
    if not isinstance(payload, dict):
        raise AviasalesSearchSchemaError()
    return payload


def _json_value(response: AviasalesSearchResponse) -> Any:
    if response.status_code >= 400:
        raise AviasalesSearchError(f"aviasales_search_http_{response.status_code}")
    if not response.content:
        raise AviasalesSearchSchemaError()
    try:
        return response.json()
    except Exception as exc:  # JSON decoder boundary; payload text is intentionally discarded.
        raise AviasalesSearchSchemaError() from exc


def _require_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AviasalesSearchSchemaError()
    return value


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _iter_items(payload: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, list):
        return tuple(item for item in payload if isinstance(item, dict))
    if not isinstance(payload, dict):
        return ()
    for key in ("items", "places", "data", "tickets", "offers", "prices", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return tuple(item for item in value if isinstance(item, dict))
    nested = payload.get("response")
    if isinstance(nested, dict):
        return _iter_items(nested)
    return ()


def _parse_suggest_place(item: dict[str, Any]) -> SuggestPlace:
    code = _first_str(item, "code", "iata", "iata_code", "id").upper()
    return SuggestPlace(
        code=code,
        name=_first_str(item, "name", "city_name", "airport_name", "label"),
        place_type=_first_str(item, "type", "place_type") or "unknown",
        country_code=(_first_str(item, "country_code", "country").upper() or None),
    )


def _parse_hot_offer(item: dict[str, Any], *, default_currency: str) -> HotOffer:
    price = _price_minor_units(item)
    return HotOffer(
        origin=_first_str(item, "origin", "origin_iata").upper(),
        destination=_first_str(item, "destination", "destination_iata").upper(),
        departure_date=_first_str(item, "depart_date", "departure_date", "departure_at") or None,
        return_date=_first_str(item, "return_date", "return_at") or None,
        price_minor_units=price,
        currency=(_first_str(item, "currency", "currency_code") or default_currency).upper(),
    )


def _parse_calendar_price(
    item: dict[str, Any],
    *,
    default_origin: str,
    default_destination: str,
    default_currency: str,
) -> CalendarPrice | None:
    departure_date = _first_str(item, "depart_date", "departure_date", "date")
    price_minor_units = _price_minor_units(item)
    if not departure_date or price_minor_units is None:
        return None
    return CalendarPrice(
        origin=(_first_str(item, "origin", "origin_iata") or default_origin).upper(),
        destination=(
            _first_str(item, "destination", "destination_iata") or default_destination
        ).upper(),
        departure_date=departure_date,
        return_date=_first_str(item, "return_date", "return_at") or None,
        price_minor_units=price_minor_units,
        currency=(_first_str(item, "currency", "currency_code") or default_currency).upper(),
    )


def _first_str(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str):
            return value
    return ""


def _price_minor_units(item: dict[str, Any]) -> int | None:
    raw = item.get("price")
    if isinstance(raw, dict):
        raw = raw.get("value")
    if raw is None:
        raw = item.get("value", item.get("min_price"))
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    if isinstance(raw, float) and not raw.is_integer():
        return None
    return int(raw) * 100
