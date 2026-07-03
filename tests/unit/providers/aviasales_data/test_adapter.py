from __future__ import annotations

from datetime import UTC, datetime

import httpx2

from flight_hunter.domain.offers import Freshness, PriceBasis, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.providers.aviasales_data.adapter import AviasalesDataAdapter
from flight_hunter.providers.aviasales_data.client import AviasalesDataClient

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_adapter_checks_policy_before_http_call_when_disabled() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=False,
        credentials_present=True,
        clock=lambda: NOW,
    )

    offers = adapter.search(
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="PLN",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert offers == ()
    assert calls == 0


def test_adapter_returns_cached_offers_when_enabled_and_credentials_present() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "WAW",
                        "destination": "BCN",
                        "price": 512,
                        "departure_at": "2026-10-12T07:00:00+02:00",
                        "return_at": None,
                        "link": "/search/WAW1210BCN",
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
    )

    offers = adapter.search(
        SearchIntent(
            origin="WAW",
            destination="BCN",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="PLN",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].price_basis == PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
    assert offers[0].requires_live_confirmation


def test_adapter_returns_cached_grouped_prices_without_live_claims() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/grouped_prices"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": {
                    "2026-09-10": {
                        "origin": "MOW",
                        "destination": "IST",
                        "price": 18420,
                        "departure_at": "2026-09-10T09:20:00+03:00",
                        "return_at": "2026-09-20T18:40:00+03:00",
                        "link": "/search/MOW1009IST2009",
                    }
                },
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.grouped_prices(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09",
            return_date="2026-09",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].total_price.minor_units == 1_842_000


def test_adapter_returns_cached_latest_prices_without_live_claims() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_latest_prices"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "price": 17500,
                        "departure_at": "2026-09-11T10:20:00+03:00",
                        "return_at": None,
                        "link": "/search/MOW1109IST",
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.latest_prices(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-01",
            return_date=None,
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].total_price.minor_units == 1_750_000


def test_adapter_uses_latest_prices_provider_found_at_as_observed_at() -> None:
    found_at = datetime(2026, 6, 29, 8, 15, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_latest_prices"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "value": 17600,
                        "depart_date": "2026-09-12",
                        "return_date": "2026-09-20",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "actual": True,
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.latest_prices(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-01",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].observed_at == found_at
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True


def test_adapter_returns_cached_week_matrix_without_live_claims() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/week-matrix"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18420,
                        "actual": True,
                    },
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-11",
                        "return_date": "2026-09-21",
                        "value": 9999,
                        "actual": False,
                    },
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.week_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].total_price.minor_units == 1_842_000


def test_adapter_returns_cached_month_matrix_without_live_claims() -> None:
    found_at = datetime(2026, 6, 29, 10, 4, 37, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/month-matrix"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18420,
                        "found_at": "2026-06-29T10:04:37+00:00",
                        "actual": True,
                    },
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-11",
                        "return_date": "2026-09-21",
                        "value": 9999,
                        "actual": False,
                    },
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.month_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].observed_at == found_at
    assert offers[0].total_price.minor_units == 1_842_000


def test_adapter_returns_cached_nearest_places_matrix_without_live_claims() -> None:
    found_at = datetime(2026, 6, 29, 11, 4, 37, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v2/prices/nearest-places-matrix"
        assert request.url.params["distance"] == "300"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "DME",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18100,
                        "found_at": "2026-06-29T11:04:37+00:00",
                        "distance": 42,
                        "actual": True,
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.nearest_places_matrix(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
        distance_km=300,
    )

    assert len(offers) == 1
    assert offers[0].origin == "DME"
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].observed_at == found_at
    assert offers[0].total_price.minor_units == 1_810_000


def test_adapter_returns_cached_search_by_price_range_without_live_claims() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/search_by_price_range"
        assert request.url.params["value_min"] == "10000"
        assert request.url.params["value_max"] == "20000"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin_code": "MOW",
                        "destination_code": "IST",
                        "origin_airport": "DME",
                        "destination_airport": "IST",
                        "departure_at": "2026-09-10",
                        "price": 18420,
                        "link": "/MOW1009IST1?t=signature",
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.search_by_price_range(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date=None,
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
        value_min=10_000,
        value_max=20_000,
        locale="ru",
    )

    assert len(offers) == 1
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].total_price.minor_units == 1_842_000
    assert offers[0].observed_at == NOW


def test_adapter_returns_cached_popular_directions_without_live_claims() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_popular_directions"
        assert request.url.params["destination"] == "IST"
        assert request.url.params["locale"] == "ru"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": {
                    "destination": {"iata": "IST", "name": "Istanbul"},
                    "origin": [
                        {
                            "city_iata": "MOW",
                            "price": 18420,
                            "departure_at": "2026-09-10",
                            "return_at": "2026-09-20",
                        }
                    ],
                },
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.popular_directions(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
        locale="ru",
    )

    assert len(offers) == 1
    assert offers[0].origin == "MOW"
    assert offers[0].destination == "IST"
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].total_price.minor_units == 1_842_000
    assert offers[0].observed_at == NOW


def test_adapter_returns_cached_special_offers_without_live_claims() -> None:
    found_at = datetime(2026, 6, 29, 8, 15, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/aviasales/v3/get_special_offers"
        assert request.url.params["origin"] == "MOW"
        assert request.url.params["destination"] == "IST"
        assert request.url.params["locale"] == "ru"
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "origin_airport": "DME",
                        "destination_airport": "IST",
                        "price": 18420,
                        "departure_at": "2026-09-10T09:20:00+03:00",
                        "return_at": "2026-09-20T18:40:00+03:00",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "link": "/search/MOW1009IST2009",
                        "signature": "signed-link",
                        "search_id": "provider-search-id",
                    }
                ],
                "error": None,
            },
        )

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
        market="ru",
    )

    offers = adapter.special_offers(
        SearchIntent(
            origin="MOW",
            destination="IST",
            departure_date="2026-09-10",
            return_date="2026-09-20",
            passengers=1,
            currency="RUB",
        ),
        request_fingerprint="sha256:test",
        context=ExecutionContext.SCHEDULER,
        locale="ru",
    )

    assert len(offers) == 1
    assert offers[0].origin == "MOW"
    assert offers[0].destination == "IST"
    assert offers[0].freshness == Freshness.CACHED
    assert offers[0].requires_live_confirmation is True
    assert offers[0].observed_at == found_at
    assert offers[0].total_price.minor_units == 1_842_000


def test_adapter_does_not_call_data_api_for_child_or_infant_pricing() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
    )

    offers = adapter.search(
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
        request_fingerprint="sha256:test",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert offers == ()
    assert calls == 0


def test_adapter_does_not_call_data_api_for_multi_adult_inferred_totals() -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    adapter = AviasalesDataAdapter(
        client=AviasalesDataClient(
            token="test-token",
            http_client=httpx2.Client(
                transport=httpx2.MockTransport(handler),
                base_url="https://api.travelpayouts.com",
            ),
            clock=lambda: NOW,
        ),
        enabled=True,
        credentials_present=True,
        clock=lambda: NOW,
    )

    offers = adapter.search(
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
        request_fingerprint="sha256:test",
        context=ExecutionContext.WEB_USER_ACTION,
    )

    assert offers == ()
    assert calls == 0
