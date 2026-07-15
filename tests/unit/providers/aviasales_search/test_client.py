from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from flight_hunter.domain.agent_search import LocationScopeKind
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchClient,
    AviasalesSearchError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    AviasalesSearchTransport,
    CurlCffiTransport,
    SearchStartParams,
)
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"x" if payload is not None else b""
        self.headers = headers or {}

    def json(self) -> Any:
        return self._payload

    @property
    def text(self) -> str:
        return json.dumps(self._payload) if self._payload is not None else ""


class _FakeTransport:
    def __init__(
        self, *, posts: list[_FakeResponse] | None = None, gets: list[_FakeResponse] | None = None
    ) -> None:
        self._posts = list(posts or [])
        self._gets = list(gets or [])
        self.post_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def post(
        self, url: str, *, json: Any, headers: Mapping[str, str], timeout: float
    ) -> _FakeResponse:
        self.post_calls.append(
            {"url": url, "json": json, "headers": dict(headers), "timeout": timeout}
        )
        if not self._posts:
            return _FakeResponse(status_code=500)
        return self._posts.pop(0)

    def get(
        self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str], timeout: float
    ) -> _FakeResponse:
        self.get_calls.append(
            {"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout}
        )
        if not self._gets:
            return _FakeResponse(status_code=404)
        return self._gets.pop(0)


def _client(transport: AviasalesSearchTransport) -> AviasalesSearchClient:
    return AviasalesSearchClient(
        signature="sig",
        marker="mobile_app.token",
        transport=transport,
        timeout=5.0,
        max_retries=0,
        sleep_fn=lambda _seconds: None,
    )


def _start_params() -> SearchStartParams:
    return SearchStartParams(
        origin=ProviderLocation(kind=LocationScopeKind.CITY, code="MOW"),
        destination=ProviderLocation(kind=LocationScopeKind.CITY, code="LED"),
        departure_date="2026-09-15",
        return_date=None,
        adults=1,
        children=0,
        infants=0,
        trip_class="Y",
        currency="RUB",
        market="RU",
    )


def test_start_search_builds_mobile_body_and_returns_ids() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={"search_id": "sid-1", "results_url": "host-1", "blet_url": "blet-1"}
            )
        ]
    )
    client = _client(transport)

    result = client.start_search(_start_params())

    assert result.search_id == "sid-1"
    assert result.results_url == "host-1"
    assert result.blet_url == "blet-1"
    call = transport.post_calls[0]
    assert "/search/v2/start" in call["url"]
    body = call["json"]
    assert body["marker"] == "mobile_app.token"
    assert body["search_params"]["directions"][0]["origin"] == "MOW"
    assert body["search_params"]["passengers"] == {"adults": 1, "children": 0, "infants": 0}
    assert call["headers"]["X-Signature"] == "sig"


def test_start_search_preserves_typed_location_flags_in_reverse_direction() -> None:
    transport = _FakeTransport(
        posts=[_FakeResponse(payload={"search_id": "sid-1", "results_url": "host-1"})]
    )
    client = _client(transport)
    params = SearchStartParams(
        origin=ProviderLocation(kind=LocationScopeKind.AIRPORT, code="svo"),
        destination=ProviderLocation(kind=LocationScopeKind.CITY, code="led"),
        departure_date="2026-09-15",
        return_date="2026-09-22",
        adults=1,
        children=0,
        infants=0,
        trip_class="Y",
        currency="RUB",
        market="RU",
    )

    client.start_search(params)

    outbound, inbound = transport.post_calls[0]["json"]["search_params"]["directions"]
    assert outbound == {
        "origin": "SVO",
        "destination": "LED",
        "date": "2026-09-15",
        "is_origin_airport": True,
        "is_destination_airport": False,
    }
    assert inbound == {
        "origin": "LED",
        "destination": "SVO",
        "date": "2026-09-22",
        "is_origin_airport": False,
        "is_destination_airport": True,
    }


def test_search_start_params_reject_untyped_locations() -> None:
    with pytest.raises(TypeError, match="origin must be ProviderLocation"):
        SearchStartParams(
            origin="MOW",  # type: ignore[arg-type]
            destination=ProviderLocation(kind=LocationScopeKind.AIRPORT, code="LED"),
            departure_date="2026-09-15",
            return_date=None,
            adults=1,
            children=0,
            infants=0,
            trip_class="Y",
            currency="RUB",
            market="RU",
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"departure_date": "not-a-date"}, "departure_date"),
        ({"return_date": "2026-09-14"}, "return_date"),
        ({"adults": 0}, "adults"),
        ({"children": -1}, "children"),
        ({"currency": "R"}, "currency"),
        ({"currency": 123}, "currency"),
    ],
)
def test_search_start_params_reject_invalid_typed_values_before_transport(
    overrides: dict[str, Any],
    message: str,
) -> None:
    values: dict[str, Any] = {
        "origin": ProviderLocation(kind=LocationScopeKind.AIRPORT, code="SVO"),
        "destination": ProviderLocation(kind=LocationScopeKind.AIRPORT, code="LED"),
        "departure_date": "2026-09-15",
        "return_date": None,
        "adults": 1,
        "children": 0,
        "infants": 0,
        "trip_class": "Y",
        "currency": "RUB",
        "market": "RU",
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError), match=message):
        SearchStartParams(**values)


def test_start_search_classifies_upstream_auth_failure_without_retry() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(status_code=401, payload={})])

    with pytest.raises(AviasalesSearchAuthFailed, match="aviasales_search_auth_failed"):
        _client(transport).start_search(_start_params())

    assert len(transport.post_calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(payload=None),
        _FakeResponse(payload=[]),
        _FakeResponse(payload={"results_url": "host-1"}),
    ],
)
def test_start_search_classifies_invalid_payload_as_schema_error(
    response: _FakeResponse,
) -> None:
    transport = _FakeTransport(posts=[response])

    with pytest.raises(AviasalesSearchSchemaError, match="aviasales_search_schema_error"):
        _client(transport).start_search(_start_params())


def test_start_search_raises_blocked_on_403() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(status_code=403)])
    client = _client(transport)

    with pytest.raises(AviasalesSearchBlocked):
        client.start_search(_start_params())


def test_start_search_raises_rate_limited_on_429_with_retry_after() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(status_code=429, headers={"Retry-After": "5"})])
    client = _client(transport)

    with pytest.raises(AviasalesSearchRateLimited) as exc:
        client.start_search(_start_params())

    assert exc.value.retry_after_seconds == 5


def test_poll_results_accumulates_chunks_with_tickets_and_stops_early() -> None:
    chunk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    transport = _FakeTransport(posts=[_FakeResponse(payload=[chunk])])
    client = _client(transport)

    chunks = client.poll_results("host-1", "sid-1", rounds=4, delay=0.0)

    assert len(chunks) == 1
    assert chunks[0] is chunk
    assert len(transport.post_calls) == 1


def test_poll_results_returns_empty_when_no_tickets_after_rounds() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload=[]) for _ in range(3)])
    client = _client(transport)

    chunks = client.poll_results("host-1", "sid-1", rounds=3, delay=0.0)

    assert chunks == []
    assert len(transport.post_calls) == 3


def test_poll_results_once_makes_one_call_and_advances_cursor_monotonically() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload=[
                    {"last_update_timestamp": 9, "tickets": []},
                    {"last_update_timestamp": 14, "tickets": [{"id": "fixture"}]},
                ]
            )
        ]
    )
    client = _client(transport)

    result = client.poll_results_once(
        "host-1",
        "sid-1",
        last_update_timestamp=10,
        limit=50,
        request_id="request-1",
    )

    assert len(transport.post_calls) == 1
    assert len(result.chunks) == 2
    assert result.last_update_timestamp == 14
    assert result.has_tickets is True
    assert transport.post_calls[0]["json"]["last_update_timestamp"] == 10
    assert transport.post_calls[0]["headers"]["X-Request-Id"] == "request-1"


def test_poll_results_once_rejects_a_non_object_chunk() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload=[{"tickets": []}, "bad-chunk"])])

    with pytest.raises(AviasalesSearchSchemaError, match="aviasales_search_schema_error"):
        _client(transport).poll_results_once(
            "host-1",
            "sid-1",
            last_update_timestamp=0,
            limit=50,
            request_id="request-1",
        )

    assert len(transport.post_calls) == 1


def test_poll_results_rejects_non_list_payload() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload={"tickets": []})])

    with pytest.raises(AviasalesSearchSchemaError, match="aviasales_search_schema_error"):
        _client(transport).poll_results("host-1", "sid-1", rounds=1, delay=0.0)


def test_get_purchase_url_returns_url_from_clicks_response() -> None:
    transport = _FakeTransport(
        gets=[_FakeResponse(payload={"url": "https://gate.example/booking/abc"})]
    )
    client = _client(transport)

    url = client.get_purchase_url("sid-1", "120:0", "host-1")

    assert url == "https://gate.example/booking/abc"
    assert "/clicks/120:0" in transport.get_calls[0]["url"]
    assert transport.get_calls[0]["params"]["marker"] == "mobile_app.token"


def test_get_purchase_url_returns_none_when_response_lacks_url() -> None:
    transport = _FakeTransport(gets=[_FakeResponse(payload={"status": "ok"})])
    client = _client(transport)

    assert client.get_purchase_url("sid-1", "120:0", "host-1") is None


def test_suggest_places_uses_suggest_host_and_sanitizes_items() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload=[
                    {
                        "iata": "led",
                        "name": "Saint Petersburg",
                        "type": "city",
                        "country_code": "ru",
                    }
                ]
            )
        ]
    )
    client = _client(transport)

    places = client.suggest_places("led", max_results=3)

    assert places[0].code == "LED"
    assert places[0].name == "Saint Petersburg"
    assert places[0].place_type == "city"
    assert places[0].country_code == "RU"
    assert transport.get_calls[0]["url"] == "https://suggest.aviasales.ru/v2/places.json"
    assert transport.get_calls[0]["params"]["term"] == "led"
    assert transport.get_calls[0]["params"]["marker"] == "mobile_app.token"


def test_hot_offers_uses_explore_host_and_returns_typed_summary() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "tickets": [
                        {
                            "origin": "MOW",
                            "destination": "LED",
                            "departure_date": "2026-09-15",
                            "return_date": None,
                            "price": {"value": 1234},
                            "currency": "rub",
                        }
                    ]
                }
            )
        ]
    )
    client = _client(transport)

    offers = client.hot_offers(origin="mow", currency="rub")

    assert offers[0].origin == "MOW"
    assert offers[0].destination == "LED"
    assert offers[0].price_minor_units == 123_400
    assert offers[0].currency == "RUB"
    assert transport.get_calls[0]["url"] == (
        "https://explore-api.aviasales.ru/v1/hot_offers/list.json"
    )


def test_calendar_prices_uses_explore_calendar_and_filters_invalid_rows() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "prices": [
                        {
                            "origin": "MOW",
                            "destination": "LED",
                            "depart_date": "2026-09-15",
                            "value": 4321,
                            "currency": "rub",
                        },
                        {"depart_date": "2026-09-16"},
                    ]
                }
            )
        ]
    )
    client = _client(transport)

    prices = client.calendar_prices(
        origin="mow",
        destination="led",
        depart_from="2026-09-01",
        depart_to="2026-09-30",
        one_way=True,
    )

    assert len(prices) == 1
    assert prices[0].departure_date == "2026-09-15"
    assert prices[0].price_minor_units == 432_100
    assert transport.get_calls[0]["url"] == "https://explore-api.aviasales.ru/api/v6/calendar.json"
    assert transport.get_calls[0]["params"]["locale"] == "ru_RU"


def test_main_page_blocks_uses_typed_graphql_operation() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "data": {
                        "mainPageBlocksV1": {
                            "blocks": [
                                {"__typename": "HotTicketsBlock"},
                                {"__typename": "CalendarBlock"},
                            ]
                        }
                    }
                }
            )
        ]
    )
    client = _client(transport)

    blocks = client.main_page_blocks(origin="mow")

    assert [block.typename for block in blocks] == ["HotTicketsBlock", "CalendarBlock"]
    call = transport.post_calls[0]
    assert call["url"] == "https://ariadne.aviasales.ru/api/gql"
    assert call["json"]["operationName"] == "MainPageBlocksV1"
    assert call["json"]["variables"]["origin"] == "MOW"


def test_transport_error_is_retried_then_raised_as_search_error() -> None:
    class _BoomTransport:
        def post(
            self, url: str, *, json: Any, headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            raise OSError("boom")

        def get(
            self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            raise OSError("boom")

    client = AviasalesSearchClient(
        signature="sig",
        marker="m",
        transport=_BoomTransport(),
        timeout=5.0,
        max_retries=1,
        sleep_fn=lambda _s: None,
    )

    with pytest.raises(AviasalesSearchError):
        client.start_search(_start_params())


def test_curl_cffi_transport_is_the_default_when_not_injected() -> None:
    assert isinstance(CurlCffiTransport(), CurlCffiTransport)
