from __future__ import annotations

import copy
import json
import traceback
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from curl_cffi.curl import CURL_WRITEFUNC_ERROR

import flight_hunter.providers.aviasales_search.client as client_module
from flight_hunter.domain.agent_search import LocationScopeKind
from flight_hunter.domain.money import MAX_MONEY_MINOR_UNITS
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchClient,
    AviasalesSearchError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    AviasalesSearchTransport,
    CurlCffiTransport,
    PollSearchResult,
    SearchStartParams,
    StartSearchResult,
)
from flight_hunter.providers.aviasales_search.schemas import ProviderLocation

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")
HOT_OFFERS_FIXTURE = Path(
    "tests/fixtures/provider/aviasales_search/hot_offers_nested_apk_contract.json"
)
RESULTS_HOST = "results-fixture.aviasales.ru"


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
        self.json_calls = 0

    def json(self) -> Any:
        self.json_calls += 1
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


def _assert_private_sentinel_absent(error: BaseException, sentinel: str) -> None:
    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    assert sentinel not in str(error)
    assert sentinel not in repr(error)
    assert sentinel not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def test_start_search_builds_mobile_body_and_returns_ids() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "sid-1",
                    "results_url": RESULTS_HOST,
                    "blet_url": "blet-1",
                }
            )
        ]
    )
    client = _client(transport)

    result = client.start_search(_start_params())

    assert result.search_id == "sid-1"
    assert result.results_url == RESULTS_HOST
    assert result.blet_url == "blet-1"
    call = transport.post_calls[0]
    assert "/search/v2/start" in call["url"]
    body = call["json"]
    assert body["marker"] == "mobile_app.token"
    assert body["search_params"]["directions"][0]["origin"] == "MOW"
    assert body["search_params"]["passengers"] == {"adults": 1, "children": 0, "infants": 0}
    assert call["headers"]["X-Signature"] == "sig"


def test_start_search_normalizes_contract_result_host() -> None:
    transport = _FakeTransport(
        posts=[
            _FakeResponse(
                payload={
                    "search_id": "sid-1",
                    "results_url": "RESULTS-FIXTURE.AVIASALES.RU",
                }
            )
        ]
    )

    result = _client(transport).start_search(_start_params())

    assert result.results_url == RESULTS_HOST


@pytest.mark.parametrize(
    "invalid_host",
    [
        "https://results-fixture.aviasales.ru",
        "results-fixture.aviasales.ru/path",
        "results-fixture.aviasales.ru?query=1",
        "results-fixture.aviasales.ru#fragment",
        "user@results-fixture.aviasales.ru",
        "results-fixture.aviasales.ru:443",
        "127.0.0.1",
        "результат.aviasales.ru",
        "aviasales.ru.example.test",
    ],
)
def test_start_search_rejects_untrusted_result_host(
    invalid_host: str,
) -> None:
    transport = _FakeTransport(
        posts=[_FakeResponse(payload={"search_id": "sid-private", "results_url": invalid_host})]
    )

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        _client(transport).start_search(_start_params())

    assert invalid_host not in str(raised.value)
    assert len(transport.post_calls) == 1


@pytest.mark.parametrize("operation", ["poll", "click"])
@pytest.mark.parametrize(
    "invalid_host",
    [
        "https://results-fixture.aviasales.ru",
        "results-fixture.aviasales.ru/path",
        "results-fixture.aviasales.ru?query=1",
        "results-fixture.aviasales.ru#fragment",
        "user@results-fixture.aviasales.ru",
        "results-fixture.aviasales.ru:443",
        "[::1]",
        "127.0.0.1",
        "результат.aviasales.ru",
        "evil.example.test",
    ],
)
def test_poll_and_click_reject_untrusted_result_host_before_transport(
    operation: str,
    invalid_host: str,
) -> None:
    transport = _FakeTransport()
    client = _client(transport)

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        if operation == "poll":
            client.poll_results_once(
                invalid_host,
                "sid-private",
                last_update_timestamp=0,
                limit=50,
                request_id="request-private",
            )
        else:
            client.get_purchase_url("sid-private", "proposal-private", invalid_host)

    assert invalid_host not in str(raised.value)
    assert transport.post_calls == []
    assert transport.get_calls == []


def test_private_client_dtos_have_redacted_repr() -> None:
    start = StartSearchResult(
        search_id="private-search-id",
        results_url="private-results-host.aviasales.ru",
        blet_url="private-blet-state",
    )
    poll = PollSearchResult(
        chunks=(
            {
                "tickets": [
                    {
                        "signature": "private-signature",
                        "proposals": ["private-proposal"],
                    }
                ]
            },
        ),
        last_update_timestamp=99,
        has_tickets=True,
    )

    rendered = repr(start) + repr(poll)

    for sentinel in (
        "private-search-id",
        "private-results-host",
        "private-blet-state",
        "private-signature",
        "private-proposal",
        "tickets",
    ):
        assert sentinel not in rendered


def test_start_search_preserves_typed_location_flags_in_reverse_direction() -> None:
    transport = _FakeTransport(
        posts=[_FakeResponse(payload={"search_id": "sid-1", "results_url": RESULTS_HOST})]
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
        ({"currency": "РУБ"}, "currency"),
        ({"market": "РФ"}, "market"),
        ({"trip_class": "P"}, "trip_class"),
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
        _FakeResponse(payload={"results_url": RESULTS_HOST}),
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

    chunks = client.poll_results(RESULTS_HOST, "sid-1", rounds=4, delay=0.0)

    assert len(chunks) == 1
    assert chunks[0] is chunk
    assert len(transport.post_calls) == 1


def test_poll_results_returns_empty_when_no_tickets_after_rounds() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload=[]) for _ in range(3)])
    client = _client(transport)

    chunks = client.poll_results(RESULTS_HOST, "sid-1", rounds=3, delay=0.0)

    assert chunks == []
    assert len(transport.post_calls) == 3


def test_poll_results_once_treats_304_as_an_empty_incremental_update() -> None:
    response = _FakeResponse(status_code=304)
    transport = _FakeTransport(posts=[response])

    result = _client(transport).poll_results_once(
        RESULTS_HOST,
        "sid-1",
        last_update_timestamp=12,
        limit=50,
        request_id="request-1",
    )

    assert result.chunks == ()
    assert result.last_update_timestamp == 12
    assert result.has_tickets is False
    assert result.not_modified is True
    assert response.json_calls == 0


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
        RESULTS_HOST,
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
            RESULTS_HOST,
            "sid-1",
            last_update_timestamp=0,
            limit=50,
            request_id="request-1",
        )

    assert len(transport.post_calls) == 1


def test_poll_results_rejects_non_list_payload() -> None:
    transport = _FakeTransport(posts=[_FakeResponse(payload={"tickets": []})])

    with pytest.raises(AviasalesSearchSchemaError, match="aviasales_search_schema_error"):
        _client(transport).poll_results(RESULTS_HOST, "sid-1", rounds=1, delay=0.0)


def test_get_purchase_url_returns_url_from_clicks_response() -> None:
    transport = _FakeTransport(
        gets=[_FakeResponse(payload={"url": "https://gate.example/booking/abc"})]
    )
    client = _client(transport)

    url = client.get_purchase_url("sid-1", "120:0", RESULTS_HOST)

    assert url == "https://gate.example/booking/abc"
    assert "/clicks/120:0" in transport.get_calls[0]["url"]
    assert transport.get_calls[0]["params"]["marker"] == "mobile_app.token"


def test_get_purchase_url_returns_none_when_response_lacks_url() -> None:
    transport = _FakeTransport(gets=[_FakeResponse(payload={"status": "ok"})])
    client = _client(transport)

    assert client.get_purchase_url("sid-1", "120:0", RESULTS_HOST) is None


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


def test_hot_offers_uses_verified_nested_contract_and_exact_departure_months() -> None:
    transport = _FakeTransport(
        gets=[_FakeResponse(payload=json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8")))]
    )
    client = _client(transport)

    offers = client.hot_offers(
        origin="svo",
        origin_type="airport",
        currency="rub",
        date_from=date(2026, 9, 15),
        date_to=date(2026, 11, 2),
    )

    assert len(offers) == 2
    assert offers[0].origin == "SVO"
    assert offers[0].destination == "CDG"
    assert offers[0].departure_date == "2026-09-15"
    assert offers[0].price_minor_units == 123_400
    assert offers[0].currency == "RUB"
    assert offers[1].departure_date == "2026-09-16"
    assert offers[1].destination == "ORY"
    assert offers[1].price_minor_units == 99_900
    assert not hasattr(offers[0], "signature")
    assert "fixture-hot-offer-signature" not in repr(offers)
    assert transport.get_calls[0]["url"] == (
        "https://explore-api.aviasales.ru/v1/hot_offers/list.json"
    )
    assert transport.get_calls[0]["params"] == {
        "origin": "SVO",
        "origin_type": "airport",
        "market": "RU",
        "passport_country": "RU",
        "language": "ru",
        "currency": "rub",
        "one_way": "true",
        "sort_type": "price",
        "with_baggage": "false",
        "direct": "false",
        "depart_months[]": ["2026-09", "2026-10", "2026-11"],
        "marker": "mobile_app.token",
    }


def test_hot_offers_rejects_oversized_body_before_json_decode() -> None:
    response = _FakeResponse(payload=json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8")))
    response.content = b"x" * (client_module._HOT_OFFERS_MAX_RESPONSE_BYTES + 1)
    client = _client(_FakeTransport(gets=[response]))

    with pytest.raises(AviasalesSearchSchemaError):
        client.hot_offers(origin="SVO", max_results=1)

    assert response.json_calls == 0


@pytest.mark.parametrize(
    "collection",
    (
        "directions",
        "direction_tags",
        "tags_order",
        "filters_order",
        "entity_airports",
        "segments",
        "flight_legs",
        "transfers",
        "technical_stops",
    ),
)
def test_hot_offers_rejects_oversized_nested_collections(collection: str) -> None:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    direction = payload["directions"][0]
    price = direction["ticket"]["price"]
    segment = price["segments"][0]
    flight_leg = segment["flightLegs"][0]
    if collection == "directions":
        payload["directions"] = [direction] * (client_module._HOT_OFFERS_MAX_DIRECTIONS + 1)
    elif collection == "direction_tags":
        direction["tags"] = ["tag"] * (client_module._HOT_OFFERS_MAX_TAGS + 1)
    elif collection == "tags_order":
        payload["tags_order"] = ["tag"] * (client_module._HOT_OFFERS_MAX_TAGS + 1)
    elif collection == "filters_order":
        payload["filters_order"] = ["filter"] * (client_module._HOT_OFFERS_MAX_FILTERS + 1)
    elif collection == "entity_airports":
        payload["entities_info"] = {
            "airports": {
                f"airport-{index}": {}
                for index in range(client_module._HOT_OFFERS_MAX_ENTITY_ITEMS + 1)
            }
        }
    elif collection == "segments":
        price["segments"] = [segment] * (client_module._HOT_OFFERS_MAX_SEGMENTS + 1)
    elif collection == "flight_legs":
        segment["flightLegs"] = [flight_leg] * (client_module._HOT_OFFERS_MAX_FLIGHT_LEGS + 1)
    elif collection == "transfers":
        segment["transfers"] = ["transfer"] * (client_module._HOT_OFFERS_MAX_TRANSFERS + 1)
    else:
        flight_leg["technicalStops"] = ["stop"] * (
            client_module._HOT_OFFERS_MAX_TECHNICAL_STOPS + 1
        )

    with pytest.raises(AviasalesSearchSchemaError):
        _client(_FakeTransport(gets=[_FakeResponse(payload=payload)])).hot_offers(
            origin="SVO",
            max_results=1,
        )


def test_hot_offers_caps_returned_objects_but_validates_the_full_payload() -> None:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    client = _client(_FakeTransport(gets=[_FakeResponse(payload=copy.deepcopy(payload))]))

    assert len(client.hot_offers(origin="SVO", max_results=1)) == 1

    payload["directions"][0]["sale_ticket"]["price"]["segments"] = []
    with pytest.raises(AviasalesSearchSchemaError):
        _client(_FakeTransport(gets=[_FakeResponse(payload=payload)])).hot_offers(
            origin="SVO",
            max_results=1,
        )


@pytest.mark.parametrize(
    "filters",
    (
        {
            "date_from": date(2026, 9, 16),
            "date_to": date(2026, 9, 16),
        },
        {
            "date_from": date(2026, 9, 15),
            "date_to": date(2026, 9, 16),
            "allowed_destination_airports": frozenset({"ORY"}),
        },
        {
            "date_from": date(2026, 9, 15),
            "date_to": date(2026, 9, 16),
            "allowed_destination_airports": frozenset({"CDG", "ORY"}),
            "excluded_destination_airports": frozenset({"CDG"}),
        },
    ),
)
def test_hot_offers_applies_approved_filters_before_consuming_result_limit(
    filters: dict[str, object],
) -> None:
    payload = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    client = _client(_FakeTransport(gets=[_FakeResponse(payload=payload)]))

    offers = client.hot_offers(origin="SVO", max_results=1, **filters)  # type: ignore[arg-type]

    assert [(offer.destination, offer.departure_date) for offer in offers] == [
        ("ORY", "2026-09-16")
    ]


def test_hot_offers_keeps_only_cheapest_eligible_row_per_destination() -> None:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    sale_price = payload["directions"][0]["sale_ticket"]["price"]
    sale_price["segments"][0]["flightLegs"][0]["destination"] = "CDG"
    client = _client(_FakeTransport(gets=[_FakeResponse(payload=payload)]))

    offers = client.hot_offers(
        origin="SVO",
        date_from=date(2026, 9, 15),
        date_to=date(2026, 9, 16),
        max_results=2,
        allowed_destination_airports=frozenset({"CDG"}),
    )

    assert [(offer.destination, offer.price_minor_units) for offer in offers] == [("CDG", 99_900)]


def test_hot_offers_rejects_price_above_persistence_ceiling() -> None:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    payload["directions"][0]["ticket"]["price"]["value"] = (MAX_MONEY_MINOR_UNITS // 100) + 1

    with pytest.raises(AviasalesSearchSchemaError):
        _client(_FakeTransport(gets=[_FakeResponse(payload=payload)])).hot_offers(
            origin="SVO",
            max_results=1,
        )


def test_curl_transport_aborts_download_above_the_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "private-bounded-download-sentinel"

    def oversized_get(_url: str, **kwargs: Any) -> object:
        callback = kwargs["content_callback"]
        assert callback(b"1234") == 4
        assert callback(b"56789") == CURL_WRITEFUNC_ERROR
        raise client_module.cc.RequestsError(sentinel)

    monkeypatch.setattr(client_module.cc, "get", oversized_get)
    transport = CurlCffiTransport(max_response_bytes=8)

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        transport.get(
            "https://explore-api.aviasales.ru/v1/hot_offers/list.json",
            params={},
            headers={},
            timeout=1.0,
        )

    _assert_private_sentinel_absent(raised.value, sentinel)


def test_curl_transport_reconstructs_a_response_from_bounded_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def successful_get(_url: str, **kwargs: Any) -> client_module.cc.Response:
        callback = kwargs["content_callback"]
        assert callback(b'{"ok":') == 6
        assert callback(b"true}") == 5
        return client_module.cc.Response()

    monkeypatch.setattr(client_module.cc, "get", successful_get)

    response = CurlCffiTransport(max_response_bytes=11).get(
        "https://explore-api.aviasales.ru/v1/hot_offers/list.json",
        params={},
        headers={},
        timeout=1.0,
    )

    assert response.content == b'{"ok":true}'
    assert response.json() == {"ok": True}


def test_transport_schema_failure_is_not_retried_or_reclassified() -> None:
    class _SchemaTransport(_FakeTransport):
        def get(
            self,
            url: str,
            *,
            params: Mapping[str, Any],
            headers: Mapping[str, str],
            timeout: float,
        ) -> _FakeResponse:
            self.get_calls.append(
                {"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout}
            )
            raise AviasalesSearchSchemaError()

    transport = _SchemaTransport()
    client = AviasalesSearchClient(
        signature="sig",
        marker="mobile_app.token",
        transport=transport,
        timeout=5.0,
        max_retries=2,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(AviasalesSearchSchemaError):
        client.hot_offers(origin="SVO", max_results=1)

    assert len(transport.get_calls) == 1


@pytest.mark.parametrize(
    "payload",
    (
        {
            "tickets": [
                {
                    "origin": "SVO",
                    "destination": "CDG",
                    "departure_date": "2026-09-15",
                    "price": {"value": 1234},
                    "currency": "rub",
                }
            ]
        },
        {
            "origin": {},
            "directions": [{"destination_iata": "CDG", "ticket": {"price": {}}}],
            "sale_info": None,
            "entities_info": {},
            "tags_order": None,
            "filters_order": [],
        },
    ),
)
def test_hot_offers_rejects_flat_or_malformed_nested_payload(payload: object) -> None:
    client = _client(_FakeTransport(gets=[_FakeResponse(payload=payload)]))

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        client.hot_offers(
            origin="SVO",
            currency="RUB",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
        )

    assert str(raised.value) == AviasalesSearchSchemaError.code


@pytest.mark.parametrize(
    "corruption",
    ("empty_segments", "empty_flight_legs", "missing_flight_leg_field", "city_mismatch"),
)
def test_hot_offers_rejects_missing_or_malformed_airport_itinerary(corruption: str) -> None:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    direction = payload["directions"][0]
    price = direction["ticket"]["price"]
    if corruption == "empty_segments":
        price["segments"] = []
    elif corruption == "empty_flight_legs":
        price["segments"][0]["flightLegs"] = []
    elif corruption == "missing_flight_leg_field":
        del price["segments"][0]["flightLegs"][0]["destination"]
    else:
        direction["destination_iata"] = "LON"
    client = _client(_FakeTransport(gets=[_FakeResponse(payload=payload)]))

    with pytest.raises(AviasalesSearchSchemaError):
        client.hot_offers(
            origin="SVO",
            currency="RUB",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
        )


def _hot_offer_with_connection(*, continuous: bool) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(HOT_OFFERS_FIXTURE.read_text(encoding="utf-8"))
    segment = payload["directions"][0]["ticket"]["price"]["segments"][0]
    first_leg = segment["flightLegs"][0]
    first_leg["destination"] = "BEG"
    first_leg["localArrivalTime"] = "11:00"
    segment["flightLegs"].append(
        {
            "localArrivalDate": "2026-09-15",
            "localArrivalTime": "13:30",
            "localDepartDate": "2026-09-15",
            "localDepartTime": "12:00",
            "origin": "BEG" if continuous else "VIE",
            "destination": "CDG",
            "carrier": "FH",
            "technicalStops": [],
            "flightNumber": "202",
            "aircraftCode": "320",
            "durationSeconds": 5400,
            "equipmentType": "aircraft",
        }
    )
    return payload


def test_hot_offers_derives_first_and_last_airports_across_connection_legs() -> None:
    client = _client(
        _FakeTransport(gets=[_FakeResponse(payload=_hot_offer_with_connection(continuous=True))])
    )

    offer = client.hot_offers(
        origin="SVO",
        currency="RUB",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )[0]

    assert (offer.origin, offer.destination) == ("SVO", "CDG")


def test_hot_offers_rejects_discontinuous_connection_legs() -> None:
    client = _client(
        _FakeTransport(gets=[_FakeResponse(payload=_hot_offer_with_connection(continuous=False))])
    )

    with pytest.raises(AviasalesSearchSchemaError):
        client.hot_offers(
            origin="SVO",
            currency="RUB",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
        )


@pytest.mark.parametrize(
    ("date_from", "date_to", "error_type"),
    (
        (date(2026, 10, 1), date(2026, 9, 30), ValueError),
        ("2026-09-01", date(2026, 9, 30), TypeError),
    ),
)
def test_hot_offers_rejects_invalid_approved_bounds_before_transport(
    date_from: object,
    date_to: object,
    error_type: type[Exception],
) -> None:
    transport = _FakeTransport()

    with pytest.raises(error_type):
        _client(transport).hot_offers(
            origin="SVO",
            date_from=date_from,  # type: ignore[arg-type]
            date_to=date_to,  # type: ignore[arg-type]
        )

    assert transport.get_calls == []


def test_hot_offers_rejects_more_than_twelve_departure_months_before_transport() -> None:
    transport = _FakeTransport()

    with pytest.raises(ValueError, match="months"):
        _client(transport).hot_offers(
            origin="SVO",
            date_from=date(2026, 1, 1),
            date_to=date(2027, 1, 1),
        )

    assert transport.get_calls == []


def test_hot_offer_month_generation_handles_latest_representable_month() -> None:
    assert client_module._hot_offer_departure_months(
        date_from=date(9999, 12, 1),
        date_to=date(9999, 12, 31),
    ) == ("9999-12",)


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


def test_transport_failure_drops_private_exception_chain() -> None:
    sentinel = "private-transport-sentinel"

    class _PrivateTransport:
        def post(
            self, url: str, *, json: Any, headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            raise OSError(sentinel)

        def get(
            self, url: str, *, params: Mapping[str, Any], headers: Mapping[str, str], timeout: float
        ) -> _FakeResponse:
            raise OSError(sentinel)

    with pytest.raises(AviasalesSearchError) as raised:
        _client(_PrivateTransport()).start_search(_start_params())

    _assert_private_sentinel_absent(raised.value, sentinel)


def test_provider_logs_never_include_transport_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flight_hunter.providers.aviasales_search import client as client_module

    logged: list[dict[str, object]] = []
    monkeypatch.setattr(
        client_module,
        "log_event",
        lambda _event, **fields: logged.append(fields),
    )

    class _FailingCalendarTransport(_FakeTransport):
        def get(
            self,
            url: str,
            *,
            params: Mapping[str, Any],
            headers: Mapping[str, str],
            timeout: float,
        ) -> _FakeResponse:
            raise OSError("private-calendar-transport")

    with pytest.raises(AviasalesSearchError):
        _client(_FailingCalendarTransport()).calendar_prices(
            origin="MOW",
            destination="LED",
            depart_from="2026-09-01",
            depart_to="2026-09-30",
            one_way=True,
            currency="RUB",
        )

    assert logged
    rendered = repr(logged)
    assert ".aviasales.ru" not in rendered
    assert "private-calendar-transport" not in rendered


def test_json_decoder_failure_drops_private_exception_chain() -> None:
    sentinel = "private-json-sentinel"

    class _PrivateJsonResponse(_FakeResponse):
        def __init__(self) -> None:
            super().__init__(payload={"safe": True})

        def json(self) -> Any:
            raise ValueError(sentinel)

    transport = _FakeTransport(posts=[_PrivateJsonResponse()])

    with pytest.raises(AviasalesSearchSchemaError) as raised:
        _client(transport).start_search(_start_params())

    _assert_private_sentinel_absent(raised.value, sentinel)


@pytest.mark.parametrize(
    ("status_code", "status_class", "retryable"),
    [(400, "client_error", False), (503, "server_error", True)],
)
def test_generic_http_failure_is_body_free_and_typed(
    status_code: int,
    status_class: str,
    retryable: bool,
) -> None:
    sentinel = "private-http-body-sentinel"
    transport = _FakeTransport(
        posts=[_FakeResponse(status_code=status_code, payload={"detail": sentinel})]
    )

    with pytest.raises(AviasalesSearchError) as raised:
        _client(transport).start_search(_start_params())

    error = raised.value
    assert getattr(error, "status_code", None) == status_code
    assert getattr(error, "status_class", None) == status_class
    assert getattr(error, "retryable", None) is retryable
    _assert_private_sentinel_absent(error, sentinel)
    assert len(transport.post_calls) == 1


def test_calendar_rejects_mixed_provider_currency_as_schema_failure() -> None:
    transport = _FakeTransport(
        gets=[
            _FakeResponse(
                payload={
                    "prices": [
                        {
                            "origin": "MOW",
                            "destination": "LED",
                            "depart_date": "2026-09-15",
                            "value": 100,
                            "currency": "RUB",
                        },
                        {
                            "origin": "MOW",
                            "destination": "LED",
                            "depart_date": "2026-09-16",
                            "value": 90,
                            "currency": "USD",
                        },
                    ]
                }
            )
        ]
    )

    with pytest.raises(AviasalesSearchSchemaError):
        _client(transport).calendar_prices(
            origin="MOW",
            destination="LED",
            depart_from="2026-09-01",
            depart_to="2026-09-30",
            one_way=True,
            currency="RUB",
        )


def test_curl_cffi_transport_is_the_default_when_not_injected() -> None:
    assert isinstance(CurlCffiTransport(), CurlCffiTransport)
