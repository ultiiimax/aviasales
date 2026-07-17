from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from time import perf_counter, sleep
from typing import Any, Literal, Protocol, cast

from curl_cffi import requests as cc
from curl_cffi.curl import CURL_WRITEFUNC_ERROR

from flight_hunter.domain.agent_search import (
    MAX_ANYWHERE_DISCOVERY_MONTHS,
    inclusive_month_count,
)
from flight_hunter.domain.money import MAX_MONEY_MINOR_UNITS
from flight_hunter.domain.provider_errors import ProviderOperationError
from flight_hunter.ops.structured_logging import log_event
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

TICKETS_BASE = "https://tickets-api.aviasales.ru"
EXPLORE_BASE = "https://explore-api.aviasales.ru"
SUGGEST_BASE = "https://suggest.aviasales.ru"
ARIADNE_BASE = "https://ariadne.aviasales.ru"
DEFAULT_USER_AGENT = "Aviasales/7.24.0 (Android; 14; Pixel_8) okhttp/5.3.2"
DEFAULT_IMPERSONATE: Literal["chrome120"] = "chrome120"
_ASCII_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_ASCII_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ASCII_MARKET_RE = re.compile(r"^[A-Z]{2}$")
_RESULT_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_RESULT_HOST_SUFFIX = "aviasales.ru"
_DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_HOT_OFFERS_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_HOT_OFFERS_MAX_DIRECTIONS = 512
_HOT_OFFERS_MAX_TAGS = 64
_HOT_OFFERS_MAX_FILTERS = 64
_HOT_OFFERS_MAX_ENTITY_ITEMS = 2_048
_HOT_OFFERS_MAX_SEGMENTS = 8
_HOT_OFFERS_MAX_FLIGHT_LEGS = 16
_HOT_OFFERS_MAX_TRANSFERS = 16
_HOT_OFFERS_MAX_TECHNICAL_STOPS = 8
_HOT_OFFERS_DEFAULT_MAX_RESULTS = 100


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


class AviasalesSearchTransportError(AviasalesSearchError):
    code = "aviasales_search_transport_error"
    retryable = True


class AviasalesSearchHttpStatusError(AviasalesSearchError):
    code = "aviasales_search_http_status_error"

    def __init__(self, *, status_code: int) -> None:
        if type(status_code) is not int or not 400 <= status_code <= 599:
            raise ValueError("status_code must be an HTTP 4xx or 5xx status")
        super().__init__()
        self.status_code = status_code
        self.status_class: Literal["client_error", "server_error"] = (
            "client_error" if status_code < 500 else "server_error"
        )
        self.retryable = status_code >= 500


@dataclass(frozen=True, slots=True, repr=False)
class StartSearchResult:
    search_id: str
    results_url: str
    blet_url: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.search_id, str) or not self.search_id:
            raise AviasalesSearchSchemaError()
        object.__setattr__(self, "results_url", normalize_results_host(self.results_url))
        if self.blet_url is not None and not isinstance(self.blet_url, str):
            raise AviasalesSearchSchemaError()

    def __repr__(self) -> str:
        return "StartSearchResult(<private>)"


@dataclass(frozen=True, slots=True, repr=False)
class PollSearchResult:
    chunks: tuple[dict[str, object], ...]
    last_update_timestamp: int
    has_tickets: bool
    not_modified: bool = False

    def __repr__(self) -> str:
        return "PollSearchResult(<private>)"


class AviasalesTripClass(StrEnum):
    ECONOMY = "Y"


@dataclass(frozen=True, slots=True)
class SearchStartParams:
    origin: ProviderLocation
    destination: ProviderLocation
    departure_date: str
    return_date: str | None
    adults: int
    children: int
    infants: int
    trip_class: AviasalesTripClass
    currency: str
    market: str

    def __post_init__(self) -> None:
        if not isinstance(self.origin, ProviderLocation):
            raise TypeError("origin must be ProviderLocation")
        if not isinstance(self.destination, ProviderLocation):
            raise TypeError("destination must be ProviderLocation")
        if not isinstance(self.departure_date, str):
            raise TypeError("departure_date must be an ISO date string")
        try:
            departure = date.fromisoformat(self.departure_date)
        except ValueError:
            raise ValueError("departure_date must be a valid ISO date") from None
        if self.return_date is not None:
            if not isinstance(self.return_date, str):
                raise TypeError("return_date must be an ISO date string")
            try:
                return_date = date.fromisoformat(self.return_date)
            except ValueError:
                raise ValueError("return_date must be a valid ISO date") from None
            if return_date < departure:
                raise ValueError("return_date cannot be before departure_date")
        for field_name in ("adults", "children", "infants"):
            value = getattr(self, field_name)
            minimum = 1 if field_name == "adults" else 0
            if type(value) is not int or value < minimum:
                raise ValueError(f"{field_name} has an invalid value")
        if not isinstance(self.trip_class, str):
            raise TypeError("trip_class must be a string")
        trip_class = self.trip_class.upper()
        if trip_class not in {item.value for item in AviasalesTripClass}:
            raise ValueError("trip_class must be a supported provider value")
        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")
        currency = self.currency.upper()
        if not _ASCII_CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be an ISO 4217 alpha-3 code")
        if not isinstance(self.market, str):
            raise TypeError("market must be a string")
        market = self.market.upper()
        if not _ASCII_MARKET_RE.fullmatch(market):
            raise ValueError("market must be an ISO alpha-2 code")
        object.__setattr__(self, "trip_class", AviasalesTripClass(trip_class))
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "market", market)

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants


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
    departure_date: str
    return_date: str | None
    price_minor_units: int
    currency: str


@dataclass(frozen=True, slots=True)
class _HotOfferFact:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    price_minor_units: int
    currency: str
    ordinal: int


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


class _BoundedResponseBuffer:
    __slots__ = ("_content", "_max_response_bytes", "exceeded")

    def __init__(self, max_response_bytes: int) -> None:
        self._max_response_bytes = max_response_bytes
        self._content = bytearray()
        self.exceeded = False

    @property
    def content(self) -> bytes:
        return bytes(self._content)

    def write(self, chunk: bytes) -> int:
        if self.exceeded or len(chunk) > self._max_response_bytes - len(self._content):
            self.exceeded = True
            return CURL_WRITEFUNC_ERROR
        self._content.extend(chunk)
        return len(chunk)


class CurlCffiTransport:
    """Real transport: curl_cffi with Chrome TLS impersonation to pass CloudFront."""

    def __init__(self, *, max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES) -> None:
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be a positive integer")
        self._max_response_bytes = max_response_bytes

    def post(
        self,
        url: str,
        *,
        json: Any,
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse:
        buffer = _BoundedResponseBuffer(self._max_response_bytes)
        response: cc.Response | None = None
        try:
            response = cc.post(
                url,
                json=json,
                headers=dict(headers),
                impersonate=DEFAULT_IMPERSONATE,
                timeout=timeout,
                content_callback=buffer.write,
            )
        except cc.RequestsError:
            if not buffer.exceeded:
                raise
        if buffer.exceeded or response is None:
            raise AviasalesSearchSchemaError()
        response.content = buffer.content
        return cast(AviasalesSearchResponse, response)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> AviasalesSearchResponse:
        buffer = _BoundedResponseBuffer(self._max_response_bytes)
        response: cc.Response | None = None
        try:
            response = cc.get(
                url,
                params=dict(params),
                headers=dict(headers),
                impersonate=DEFAULT_IMPERSONATE,
                timeout=timeout,
                content_callback=buffer.write,
            )
        except cc.RequestsError:
            if not buffer.exceeded:
                raise
        if buffer.exceeded or response is None:
            raise AviasalesSearchSchemaError()
        response.content = buffer.content
        return cast(AviasalesSearchResponse, response)


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
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
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

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def start_search(self, params: SearchStartParams) -> StartSearchResult:
        directions = [
            {
                "origin": params.origin.code,
                "destination": params.destination.code,
                "date": params.departure_date,
                "is_origin_airport": params.origin.is_airport,
                "is_destination_airport": params.destination.is_airport,
            }
        ]
        if params.return_date is not None:
            directions.append(
                {
                    "origin": params.destination.code,
                    "destination": params.origin.code,
                    "date": params.return_date,
                    "is_origin_airport": params.destination.is_airport,
                    "is_destination_airport": params.origin.is_airport,
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
        req_id = request_id or str(uuid.uuid4())
        chunks: list[dict[str, Any]] = []
        last_ts = 0
        for round_index in range(rounds):
            result = self.poll_results_once(
                results_url,
                search_id,
                last_update_timestamp=last_ts,
                limit=limit,
                request_id=req_id,
            )
            chunks.extend(cast(tuple[dict[str, Any], ...], result.chunks))
            last_ts = result.last_update_timestamp
            if result.has_tickets:
                break
            if round_index + 1 < rounds:
                self._sleep(delay)
        return chunks

    def poll_results_once(
        self,
        results_url: str,
        search_id: str,
        *,
        last_update_timestamp: int,
        limit: int,
        request_id: str,
    ) -> PollSearchResult:
        if type(last_update_timestamp) is not int or last_update_timestamp < 0:
            raise ValueError("last_update_timestamp must be a non-negative integer")
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        if not request_id:
            raise ValueError("request_id is required")
        host = normalize_results_host(results_url)
        poll_url = f"https://{host}/search/v3.2/results"
        response = self._request(
            "POST",
            poll_url,
            json_body={
                "search_id": search_id,
                "limit": limit,
                "last_update_timestamp": last_update_timestamp,
                "required_tickets": [],
                "highlighted_ticket": None,
                "search_by_airport": False,
                "price_per_person": False,
                "filters_state": {},
            },
            extra_headers={"X-Request-Id": request_id},
            full_url=True,
        )
        chunks = (
            () if response.status_code == 304 else _validated_poll_chunks(_json_value(response))
        )
        cursor = max(
            (
                timestamp
                for chunk in chunks
                if type(timestamp := chunk.get("last_update_timestamp")) is int
            ),
            default=last_update_timestamp,
        )
        return PollSearchResult(
            chunks=chunks,
            last_update_timestamp=max(last_update_timestamp, cursor),
            has_tickets=any(bool(chunk.get("tickets")) for chunk in chunks),
            not_modified=response.status_code == 304,
        )

    def get_purchase_url(
        self,
        search_id: str,
        proposal_id: str,
        results_url: str,
        *,
        blet_request_id: str | None = None,
    ) -> str | None:
        host = normalize_results_host(results_url)
        url = f"{self._base_url}/searches/{search_id}/clicks/{proposal_id}"
        params = {
            "marker": self._marker,
            "host": host,
            "blet_request_id": blet_request_id or str(uuid.uuid4()),
        }
        response = self._request("GET", url, params=params, full_url=True)
        if response.status_code != 200 or not response.content:
            return None
        payload = _json_value(response)
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
        date_from: date | None = None,
        date_to: date | None = None,
        max_results: int = _HOT_OFFERS_DEFAULT_MAX_RESULTS,
        allowed_destination_airports: frozenset[str] | None = None,
        excluded_destination_airports: frozenset[str] = frozenset(),
    ) -> tuple[HotOffer, ...]:
        normalized_origin = _normalized_ascii_iata(origin)
        normalized_currency = _normalized_ascii_currency(currency)
        if type(one_way) is not bool:
            raise TypeError("one_way must be a boolean")
        if type(max_results) is not int or max_results <= 0:
            raise ValueError("max_results must be a positive integer")
        allowed_destinations = _hot_offer_airport_filter(
            allowed_destination_airports,
            field_name="allowed_destination_airports",
            allow_none=True,
        )
        excluded_destinations = _hot_offer_airport_filter(
            excluded_destination_airports,
            field_name="excluded_destination_airports",
            allow_none=False,
        )
        assert excluded_destinations is not None
        if allowed_destinations is not None:
            if not allowed_destinations:
                raise ValueError("allowed_destination_airports cannot be empty")
            if not excluded_destinations <= allowed_destinations:
                raise ValueError("excluded destinations must be a subset of allowed destinations")
            if normalized_origin in allowed_destinations:
                raise ValueError("origin cannot be an allowed destination")
        depart_months = _hot_offer_departure_months(date_from=date_from, date_to=date_to)
        request_params: dict[str, Any] = {
            "origin": normalized_origin,
            "origin_type": origin_type,
            "market": market,
            "passport_country": passport_country,
            "language": "ru",
            "currency": normalized_currency.lower(),
            "one_way": str(one_way).lower(),
            "sort_type": "price",
            "with_baggage": "false",
            "direct": "false",
            "marker": self._marker,
        }
        if depart_months is not None:
            request_params["depart_months[]"] = list(depart_months)
        response = self._request(
            "GET",
            f"{self._explore_base_url}/v1/hot_offers/list.json",
            params=request_params,
            full_url=True,
        )
        return _parse_hot_offers_payload(
            _json_value(response, max_response_bytes=_HOT_OFFERS_MAX_RESPONSE_BYTES),
            expected_origin=normalized_origin,
            expected_currency=normalized_currency,
            one_way=one_way,
            max_results=max_results,
            date_from=date_from,
            date_to=date_to,
            allowed_destination_airports=allowed_destinations,
            excluded_destination_airports=excluded_destinations,
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
        origin_type: str = "city",
        destination_type: str = "city",
        locale: str = "ru_RU",
    ) -> tuple[CalendarPrice, ...]:
        normalized_origin = _normalized_ascii_iata(origin)
        normalized_destination = _normalized_ascii_iata(destination)
        normalized_currency = _normalized_ascii_currency(currency)
        departure_from = _request_date(depart_from)
        departure_to = _request_date(depart_to)
        if departure_to < departure_from:
            raise ValueError("depart_to cannot be before depart_from")
        if type(one_way) is not bool:
            raise TypeError("one_way must be a boolean")
        response = self._request(
            "GET",
            f"{self._explore_base_url}/api/v6/calendar.json",
            params={
                "origin_iata": normalized_origin,
                "origin_type": origin_type,
                "destination_iata": normalized_destination,
                "destination_type": destination_type,
                "one_way": str(one_way).lower(),
                "depart_date_from": depart_from,
                "depart_date_to": depart_to,
                "currency": normalized_currency.lower(),
                "locale": locale,
                "trip_class": "Y",
                "marker": self._marker,
            },
            full_url=True,
        )
        parsed = tuple(
            price
            for item in _iter_items(_json_value(response))
            if (price := _parse_calendar_price(item)) is not None
        )
        return validate_calendar_price_rows(
            parsed,
            origin=normalized_origin,
            destination=normalized_destination,
            depart_from=departure_from,
            depart_to=departure_to,
            one_way=one_way,
            currency=normalized_currency,
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
        transport_exhausted = False
        http_status_error: int | None = None
        for attempt in range(self._max_retries + 1):
            started = perf_counter()
            status: int | None = None
            response: AviasalesSearchResponse | None = None
            transport_failed = False
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
            except AviasalesSearchSchemaError:
                log_event(
                    "provider_call",
                    provider="aviasales_search",
                    endpoint=_endpoint_name(target),
                    status_code=None,
                    error_class="schema_error",
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )
                raise
            except Exception:  # provider transport boundary: classify + log
                transport_failed = True
            if transport_failed:
                log_event(
                    "provider_call",
                    provider="aviasales_search",
                    endpoint=_endpoint_name(target),
                    status_code=None,
                    error_class="transport_error",
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )
                if attempt < self._max_retries:
                    self._sleep(_backoff(attempt))
                    continue
                transport_exhausted = True
                break
            if response is None or type(status) is not int:
                raise AviasalesSearchSchemaError()
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
            if status >= 400:
                log_event(
                    "provider_call",
                    provider="aviasales_search",
                    endpoint=_endpoint_name(target),
                    status_code=status,
                    error_class="server_error" if status >= 500 else "client_error",
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                )
                if status >= 500 and attempt < self._max_retries:
                    self._sleep(_backoff(attempt))
                    continue
                http_status_error = status
                break
            log_event(
                "provider_call",
                provider="aviasales_search",
                endpoint=_endpoint_name(target),
                status_code=status,
                duration_ms=max(0, int((perf_counter() - started) * 1000)),
            )
            return response
        if http_status_error is not None:
            raise AviasalesSearchHttpStatusError(status_code=http_status_error)
        if transport_exhausted:
            raise AviasalesSearchTransportError()
        raise AviasalesSearchTransportError()


def _backoff(attempt: int) -> float:
    return min(2.0**attempt, 4.0)


def normalize_results_host(value: str) -> str:
    """Return a contract-proven bare Aviasales result host or fail safely."""

    if not isinstance(value, str) or not value or len(value) > 253 or not value.isascii():
        raise AviasalesSearchSchemaError()
    if value != value.strip():
        raise AviasalesSearchSchemaError()
    normalized = value.lower()
    labels = normalized.split(".")
    if normalized != _RESULT_HOST_SUFFIX and not normalized.endswith(f".{_RESULT_HOST_SUFFIX}"):
        raise AviasalesSearchSchemaError()
    if not labels or any(not _RESULT_HOST_LABEL_RE.fullmatch(label) for label in labels):
        raise AviasalesSearchSchemaError()
    return normalized


def _endpoint_name(target: str) -> str:
    known_endpoints = (
        ("/search/v2/start", "start_search"),
        ("/search/v3.2/results", "poll_results"),
        ("/clicks/", "clicks"),
        ("/v2/places.json", "suggest_places"),
        ("/v1/hot_offers/list.json", "hot_offers"),
        ("/api/v6/calendar.json", "calendar"),
        ("/api/gql", "main_page_blocks"),
    )
    for fragment, safe_name in known_endpoints:
        if fragment in target:
            return safe_name
    return "unknown_endpoint"


def _json_object(response: AviasalesSearchResponse) -> dict[str, Any]:
    payload = _json_value(response)
    if not isinstance(payload, dict):
        raise AviasalesSearchSchemaError()
    return payload


def _json_value(
    response: AviasalesSearchResponse,
    *,
    max_response_bytes: int | None = None,
) -> Any:
    if response.status_code >= 400:
        raise AviasalesSearchHttpStatusError(status_code=response.status_code)
    content = response.content
    if not isinstance(content, bytes) or not content:
        raise AviasalesSearchSchemaError()
    if max_response_bytes is not None and len(content) > max_response_bytes:
        raise AviasalesSearchSchemaError()
    decode_failed = False
    payload: Any = None
    try:
        payload = response.json()
    except Exception:  # JSON decoder boundary; payload text is intentionally discarded.
        decode_failed = True
    if decode_failed:
        raise AviasalesSearchSchemaError()
    return payload


def _validated_poll_chunks(payload: Any) -> tuple[dict[str, object], ...]:
    if not isinstance(payload, list):
        raise AviasalesSearchSchemaError()
    chunks: list[dict[str, object]] = []
    for raw_chunk in payload:
        if not isinstance(raw_chunk, dict):
            raise AviasalesSearchSchemaError()
        timestamp = raw_chunk.get("last_update_timestamp")
        if timestamp is not None and (type(timestamp) is not int or timestamp < 0):
            raise AviasalesSearchSchemaError()
        tickets = raw_chunk.get("tickets")
        if tickets is not None and not isinstance(tickets, list):
            raise AviasalesSearchSchemaError()
        chunks.append(cast(dict[str, object], raw_chunk))
    return tuple(chunks)


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


def _parse_hot_offers_payload(
    payload: object,
    *,
    expected_origin: str,
    expected_currency: str,
    one_way: bool,
    max_results: int,
    date_from: date | None,
    date_to: date | None,
    allowed_destination_airports: frozenset[str] | None,
    excluded_destination_airports: frozenset[str],
) -> tuple[HotOffer, ...]:
    if not isinstance(payload, dict):
        raise AviasalesSearchSchemaError()
    required_keys = {
        "origin",
        "directions",
        "sale_info",
        "entities_info",
        "tags_order",
        "filters_order",
    }
    if not required_keys.issubset(payload):
        raise AviasalesSearchSchemaError()
    top_origin = payload["origin"]
    translation = top_origin.get("translation") if isinstance(top_origin, dict) else None
    if (
        not isinstance(top_origin, dict)
        or not {"translation", "image_url"}.issubset(top_origin)
        or not isinstance(translation, dict)
        or not _non_empty_string(translation.get("su"))
        or any(
            key in translation
            and translation[key] is not None
            and not isinstance(translation[key], str)
            for key in ("ro", "da", "vi", "tv", "pr")
        )
        or (top_origin["image_url"] is not None and not isinstance(top_origin["image_url"], str))
    ):
        raise AviasalesSearchSchemaError()
    directions = payload["directions"]
    if not isinstance(directions, list) or len(directions) > _HOT_OFFERS_MAX_DIRECTIONS:
        raise AviasalesSearchSchemaError()
    if payload["sale_info"] is not None and not isinstance(payload["sale_info"], dict):
        raise AviasalesSearchSchemaError()
    entities_info = payload["entities_info"]
    if not isinstance(entities_info, dict):
        raise AviasalesSearchSchemaError()
    entity_items = 0
    for entity_kind in ("airports", "cities", "countries"):
        entity_map = entities_info.get(entity_kind)
        if entity_map is not None and not isinstance(entity_map, dict):
            raise AviasalesSearchSchemaError()
        if isinstance(entity_map, dict):
            entity_items += len(entity_map)
            if entity_items > _HOT_OFFERS_MAX_ENTITY_ITEMS:
                raise AviasalesSearchSchemaError()
    tags_order = payload["tags_order"]
    if tags_order is not None and (
        not isinstance(tags_order, list) or len(tags_order) > _HOT_OFFERS_MAX_TAGS
    ):
        raise AviasalesSearchSchemaError()
    filters_order = payload["filters_order"]
    if not isinstance(filters_order, list) or len(filters_order) > _HOT_OFFERS_MAX_FILTERS:
        raise AviasalesSearchSchemaError()

    selected: list[_HotOfferFact] = []
    ordinal = 0
    for direction in directions:
        if not isinstance(direction, dict):
            raise AviasalesSearchSchemaError()
        direction_keys = {
            "destination_iata",
            "ticket",
            "sale_ticket",
            "tags",
            "tickets_count",
        }
        if not direction_keys.issubset(direction):
            raise AviasalesSearchSchemaError()
        destination = _ascii_iata_or_none(direction["destination_iata"])
        if destination is None or destination == expected_origin:
            raise AviasalesSearchSchemaError()
        direction_tags = direction["tags"]
        if direction_tags is not None and (
            not isinstance(direction_tags, list) or len(direction_tags) > _HOT_OFFERS_MAX_TAGS
        ):
            raise AviasalesSearchSchemaError()
        tickets_count = direction["tickets_count"]
        if type(tickets_count) is not int or tickets_count < 0:
            raise AviasalesSearchSchemaError()
        ticket = _parse_hot_offer_ticket(
            direction["ticket"],
            direction_destination=destination,
            expected_origin=expected_origin,
            expected_currency=expected_currency,
            one_way=one_way,
            ordinal=ordinal,
        )
        ordinal += 1
        if _hot_offer_fact_matches(
            ticket,
            date_from=date_from,
            date_to=date_to,
            allowed_destination_airports=allowed_destination_airports,
            excluded_destination_airports=excluded_destination_airports,
        ):
            _retain_hot_offer_fact(
                selected,
                ticket,
                max_results=max_results,
                deduplicate_destination=allowed_destination_airports is not None,
            )
        sale_ticket = direction["sale_ticket"]
        if sale_ticket is not None:
            parsed_sale = _parse_hot_offer_ticket(
                sale_ticket,
                direction_destination=destination,
                expected_origin=expected_origin,
                expected_currency=expected_currency,
                one_way=one_way,
                ordinal=ordinal,
            )
            ordinal += 1
            if _hot_offer_fact_matches(
                parsed_sale,
                date_from=date_from,
                date_to=date_to,
                allowed_destination_airports=allowed_destination_airports,
                excluded_destination_airports=excluded_destination_airports,
            ):
                _retain_hot_offer_fact(
                    selected,
                    parsed_sale,
                    max_results=max_results,
                    deduplicate_destination=allowed_destination_airports is not None,
                )
    if allowed_destination_airports is not None:
        ordered = sorted(selected, key=_hot_offer_fact_rank)
    else:
        ordered = sorted(selected, key=lambda fact: fact.ordinal)
    return tuple(_hot_offer_from_fact(fact) for fact in ordered)


def _parse_hot_offer_ticket(
    value: object,
    *,
    direction_destination: str,
    expected_origin: str,
    expected_currency: str,
    one_way: bool,
    ordinal: int,
) -> _HotOfferFact:
    if not isinstance(value, dict) or not {"price", "badge"}.issubset(value):
        raise AviasalesSearchSchemaError()
    if value["badge"] is not None and not isinstance(value["badge"], dict):
        raise AviasalesSearchSchemaError()
    price = value["price"]
    if not isinstance(price, dict):
        raise AviasalesSearchSchemaError()
    price_keys = {
        "signature",
        "value",
        "currency",
        "duration",
        "gate",
        "search_id",
        "origin_city_iata",
        "destination_city_iata",
        "depart_date",
        "return_date",
        "withBaggage",
        "fareKey",
        "segments",
    }
    if not price_keys.issubset(price):
        raise AviasalesSearchSchemaError()
    # The signature proves this is the nested price fragment, but it remains private.
    if not isinstance(price["signature"], str) or not price["signature"]:
        raise AviasalesSearchSchemaError()
    duration = price["duration"]
    if type(duration) is not int or duration < 0:
        raise AviasalesSearchSchemaError()
    for key in ("gate", "search_id", "fareKey"):
        if not isinstance(price[key], str) or not price[key]:
            raise AviasalesSearchSchemaError()
    if type(price["withBaggage"]) is not bool or not isinstance(price["segments"], list):
        raise AviasalesSearchSchemaError()

    origin_city = _ascii_iata_or_none(price["origin_city_iata"])
    destination_city = _ascii_iata_or_none(price["destination_city_iata"])
    currency = _ascii_currency_or_none(price["currency"])
    departure = _provider_date_or_none(price["depart_date"])
    raw_return = price["return_date"]
    returned = _provider_date_or_none(raw_return) if raw_return is not None else None
    raw_amount = price["value"]
    if (
        origin_city is None
        or destination_city != direction_destination
        or origin_city == destination_city
        or currency != expected_currency
        or departure is None
        or (raw_return is not None and returned is None)
        or isinstance(raw_amount, bool)
        or not isinstance(raw_amount, int | float)
        or (isinstance(raw_amount, float) and not raw_amount.is_integer())
        or raw_amount < 0
        or raw_amount > MAX_MONEY_MINOR_UNITS // 100
    ):
        raise AviasalesSearchSchemaError()
    if one_way:
        if returned is not None:
            raise AviasalesSearchSchemaError()
    elif returned is None or returned < departure:
        raise AviasalesSearchSchemaError()
    origin, destination = _parse_hot_offer_airport_itinerary(
        price["segments"],
        expected_departure=departure,
    )
    if origin != expected_origin or destination == origin:
        raise AviasalesSearchSchemaError()
    return _HotOfferFact(
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=returned,
        price_minor_units=int(raw_amount) * 100,
        currency=currency,
        ordinal=ordinal,
    )


def _hot_offer_fact_matches(
    fact: _HotOfferFact,
    *,
    date_from: date | None,
    date_to: date | None,
    allowed_destination_airports: frozenset[str] | None,
    excluded_destination_airports: frozenset[str],
) -> bool:
    if (
        date_from is not None
        and date_to is not None
        and not date_from <= fact.departure_date <= date_to
    ):
        return False
    if (
        allowed_destination_airports is not None
        and fact.destination not in allowed_destination_airports
    ):
        return False
    return fact.destination not in excluded_destination_airports


def _hot_offer_fact_rank(fact: _HotOfferFact) -> tuple[int, date, date, str, str, str, int]:
    return (
        fact.price_minor_units,
        fact.departure_date,
        fact.return_date or date.min,
        fact.destination,
        fact.origin,
        fact.currency,
        fact.ordinal,
    )


def _retain_hot_offer_fact(
    selected: list[_HotOfferFact],
    candidate: _HotOfferFact,
    *,
    max_results: int,
    deduplicate_destination: bool,
) -> None:
    candidate_rank = _hot_offer_fact_rank(candidate)
    if deduplicate_destination:
        for index, current in enumerate(selected):
            if current.destination == candidate.destination:
                if candidate_rank < _hot_offer_fact_rank(current):
                    selected[index] = candidate
                return
    if len(selected) < max_results:
        selected.append(candidate)
        return
    worst_index = max(range(len(selected)), key=lambda index: _hot_offer_fact_rank(selected[index]))
    if candidate_rank < _hot_offer_fact_rank(selected[worst_index]):
        selected[worst_index] = candidate


def _hot_offer_from_fact(fact: _HotOfferFact) -> HotOffer:
    return HotOffer(
        origin=fact.origin,
        destination=fact.destination,
        departure_date=fact.departure_date.isoformat(),
        return_date=fact.return_date.isoformat() if fact.return_date is not None else None,
        price_minor_units=fact.price_minor_units,
        currency=fact.currency,
    )


def _parse_hot_offer_airport_itinerary(
    value: object,
    *,
    expected_departure: date,
) -> tuple[str, str]:
    if not isinstance(value, list) or not value or len(value) > _HOT_OFFERS_MAX_SEGMENTS:
        raise AviasalesSearchSchemaError()
    itinerary_origin: str | None = None
    previous_destination: str | None = None
    first_departure: date | None = None
    for segment in value:
        if not isinstance(segment, dict):
            raise AviasalesSearchSchemaError()
        segment_keys = {
            "localArrivalDate",
            "localArrivalTime",
            "localDepartDate",
            "localDepartTime",
            "flightLegs",
            "transfers",
        }
        if not segment_keys.issubset(segment):
            raise AviasalesSearchSchemaError()
        segment_departure = _provider_date_or_none(segment["localDepartDate"])
        segment_arrival = _provider_date_or_none(segment["localArrivalDate"])
        if (
            segment_departure is None
            or segment_arrival is None
            or not _non_empty_string(segment["localDepartTime"])
            or not _non_empty_string(segment["localArrivalTime"])
            or not isinstance(segment["transfers"], list)
            or len(segment["transfers"]) > _HOT_OFFERS_MAX_TRANSFERS
        ):
            raise AviasalesSearchSchemaError()
        flight_legs = segment["flightLegs"]
        if (
            not isinstance(flight_legs, list)
            or not flight_legs
            or len(flight_legs) > _HOT_OFFERS_MAX_FLIGHT_LEGS
        ):
            raise AviasalesSearchSchemaError()
        segment_first_departure: date | None = None
        segment_last_arrival: date | None = None
        for flight_leg in flight_legs:
            if not isinstance(flight_leg, dict):
                raise AviasalesSearchSchemaError()
            flight_leg_keys = {
                "localArrivalDate",
                "localArrivalTime",
                "localDepartDate",
                "localDepartTime",
                "origin",
                "destination",
                "carrier",
                "technicalStops",
                "flightNumber",
                "aircraftCode",
                "durationSeconds",
                "equipmentType",
            }
            if not flight_leg_keys.issubset(flight_leg):
                raise AviasalesSearchSchemaError()
            leg_departure = _provider_date_or_none(flight_leg["localDepartDate"])
            leg_arrival = _provider_date_or_none(flight_leg["localArrivalDate"])
            origin = _ascii_iata_or_none(flight_leg["origin"])
            destination = _ascii_iata_or_none(flight_leg["destination"])
            technical_stops = flight_leg["technicalStops"]
            duration_seconds = flight_leg["durationSeconds"]
            required_strings = (
                flight_leg["localArrivalTime"],
                flight_leg["localDepartTime"],
                flight_leg["carrier"],
                flight_leg["flightNumber"],
                flight_leg["aircraftCode"],
                flight_leg["equipmentType"],
            )
            if (
                leg_departure is None
                or leg_arrival is None
                or origin is None
                or destination is None
                or origin == destination
                or any(not _non_empty_string(item) for item in required_strings)
                or not isinstance(technical_stops, list)
                or len(technical_stops) > _HOT_OFFERS_MAX_TECHNICAL_STOPS
                or any(not _non_empty_string(item) for item in technical_stops)
                or type(duration_seconds) is not int
                or duration_seconds < 0
                or (previous_destination is not None and origin != previous_destination)
            ):
                raise AviasalesSearchSchemaError()
            if itinerary_origin is None:
                itinerary_origin = origin
                first_departure = leg_departure
            if segment_first_departure is None:
                segment_first_departure = leg_departure
            segment_last_arrival = leg_arrival
            previous_destination = destination
        if segment_first_departure != segment_departure or segment_last_arrival != segment_arrival:
            raise AviasalesSearchSchemaError()
    if (
        itinerary_origin is None
        or previous_destination is None
        or first_departure != expected_departure
    ):
        raise AviasalesSearchSchemaError()
    return itinerary_origin, previous_destination


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _parse_calendar_price(item: dict[str, Any]) -> CalendarPrice | None:
    origin = _first_str(item, "origin", "origin_iata")
    destination = _first_str(item, "destination", "destination_iata")
    departure_date = _first_str(item, "depart_date", "departure_date", "date")
    currency = _first_str(item, "currency", "currency_code")
    price_minor_units = _price_minor_units(item)
    if not origin or not destination or not departure_date or not currency:
        return None
    if price_minor_units is None:
        return None
    return CalendarPrice(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=_first_str(item, "return_date", "return_at") or None,
        price_minor_units=price_minor_units,
        currency=currency,
    )


def validate_calendar_price_rows(
    prices: tuple[CalendarPrice, ...],
    *,
    origin: str,
    destination: str,
    depart_from: date,
    depart_to: date,
    one_way: bool,
    currency: str,
) -> tuple[CalendarPrice, ...]:
    """Validate provider calendar facts against the exact request context."""

    normalized_origin = _normalized_ascii_iata(origin)
    normalized_destination = _normalized_ascii_iata(destination)
    normalized_currency = _normalized_ascii_currency(currency)
    if type(depart_from) is not date or type(depart_to) is not date:
        raise TypeError("calendar bounds must be dates")
    if depart_to < depart_from:
        raise ValueError("depart_to cannot be before depart_from")
    if type(one_way) is not bool:
        raise TypeError("one_way must be a boolean")

    valid: list[CalendarPrice] = []
    currency_mismatch = False
    schema_corruption = False
    for price in tuple(prices):
        if not isinstance(price, CalendarPrice):
            raise AviasalesSearchSchemaError()
        row_origin = _ascii_iata_or_none(price.origin)
        row_destination = _ascii_iata_or_none(price.destination)
        if row_origin != normalized_origin or row_destination != normalized_destination:
            continue
        departure = _provider_date_or_none(price.departure_date)
        if departure is None:
            schema_corruption = True
            continue
        if not depart_from <= departure <= depart_to:
            continue
        returned = (
            _provider_date_or_none(price.return_date) if price.return_date is not None else None
        )
        if price.return_date is not None and returned is None:
            schema_corruption = True
            continue
        if one_way:
            if price.return_date is not None:
                continue
        elif returned is None or returned < departure:
            continue
        if (
            type(price.price_minor_units) is not int
            or price.price_minor_units < 0
            or price.price_minor_units > MAX_MONEY_MINOR_UNITS
        ):
            schema_corruption = True
            continue
        row_currency = _ascii_currency_or_none(price.currency)
        if row_currency != normalized_currency:
            currency_mismatch = True
            continue
        valid.append(
            CalendarPrice(
                origin=row_origin,
                destination=row_destination,
                departure_date=departure.isoformat(),
                return_date=returned.isoformat() if returned is not None else None,
                price_minor_units=price.price_minor_units,
                currency=row_currency,
            )
        )
    if currency_mismatch or schema_corruption:
        raise AviasalesSearchSchemaError()
    return tuple(valid)


def _normalized_ascii_iata(value: str) -> str:
    normalized = _ascii_iata_or_none(value)
    if normalized is None:
        raise AviasalesSearchSchemaError()
    return normalized


def _ascii_iata_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    return normalized if _ASCII_IATA_RE.fullmatch(normalized) else None


def _normalized_ascii_currency(value: str) -> str:
    normalized = _ascii_currency_or_none(value)
    if normalized is None:
        raise AviasalesSearchSchemaError()
    return normalized


def _ascii_currency_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.upper()
    return normalized if _ASCII_CURRENCY_RE.fullmatch(normalized) else None


def _hot_offer_airport_filter(
    value: frozenset[str] | None,
    *,
    field_name: str,
    allow_none: bool,
) -> frozenset[str] | None:
    if value is None:
        if allow_none:
            return None
        raise TypeError(f"{field_name} must be a frozenset")
    if not isinstance(value, frozenset):
        raise TypeError(f"{field_name} must be a frozenset")
    if any(not isinstance(code, str) or not _ASCII_IATA_RE.fullmatch(code) for code in value):
        raise ValueError(f"{field_name} must contain uppercase IATA codes")
    return value


def _request_date(value: str) -> date:
    if not isinstance(value, str):
        raise TypeError("calendar date must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("calendar date must be a valid ISO date") from None
    if parsed.isoformat() != value:
        raise ValueError("calendar date must be a canonical ISO date")
    return parsed


def _hot_offer_departure_months(
    *,
    date_from: date | None,
    date_to: date | None,
) -> tuple[str, ...] | None:
    if date_from is None and date_to is None:
        return None
    if type(date_from) is not date or type(date_to) is not date:
        raise TypeError("hot-offer bounds must both be dates")
    if date_to < date_from:
        raise ValueError("date_to cannot be before date_from")
    month_count = inclusive_month_count(date_from, date_to)
    if month_count > MAX_ANYWHERE_DISCOVERY_MONTHS:
        raise ValueError(
            "hot-offer discovery cannot span more than "
            f"{MAX_ANYWHERE_DISCOVERY_MONTHS} inclusive months"
        )
    cursor = date(date_from.year, date_from.month, 1)
    final = date(date_to.year, date_to.month, 1)
    months: list[str] = []
    while True:
        months.append(f"{cursor.year:04d}-{cursor.month:02d}")
        if cursor == final:
            break
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return tuple(months)


def _provider_date_or_none(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    invalid = False
    parsed: date | None = None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        invalid = True
    if invalid or parsed is None or parsed.isoformat() != value:
        return None
    return parsed


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
    if raw < 0 or raw > MAX_MONEY_MINOR_UNITS // 100:
        return None
    return int(raw) * 100
