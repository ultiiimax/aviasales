from __future__ import annotations

from datetime import UTC, datetime

import httpx2
import pytest

from flight_hunter.providers.aviasales_data.client import (
    AviasalesDataClient,
    AviasalesDataError,
    AviasalesDataRateLimit,
    AviasalesDataRateLimited,
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


def test_prices_for_dates_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.prices_for_dates(
        PricesForDatesQuery(
            origin="WAW",
            destination="BCN",
            departure_at="2026-10-12",
            return_at="2026-10-19",
            currency="PLN",
            market="pl",
            one_way=False,
            direct=False,
            limit=30,
            page=1,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/prices_for_dates"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "WAW"
    assert captured_request.url.params["destination"] == "BCN"
    assert captured_request.url.params["departure_at"] == "2026-10-12"
    assert captured_request.url.params["return_at"] == "2026-10-19"
    assert captured_request.url.params["cy"] == "pln"
    assert captured_request.url.params["one_way"] == "false"


def test_prices_for_dates_logs_safe_provider_call_event(monkeypatch) -> None:
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "flight_hunter.providers.aviasales_data.client.log_event",
        lambda event, **fields: events.append({"event": event, **fields}),
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="secret-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.prices_for_dates(
        PricesForDatesQuery(
            origin="WAW",
            destination="BCN",
            departure_at="2026-10-12",
            return_at=None,
            currency="PLN",
            market="pl",
            one_way=True,
            direct=False,
            limit=30,
            page=1,
        )
    )

    payload = events[0]
    assert payload["provider"] == "aviasales_data"
    assert payload["endpoint"] == "prices_for_dates"
    assert payload["status_code"] == 200
    assert isinstance(payload["duration_ms"], int)
    log_text = str(payload)
    assert "secret-token" not in log_text
    assert "travelpayouts" not in log_text
    assert "WAW" not in log_text
    assert "BCN" not in log_text


def test_prices_for_dates_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            429,
            headers={
                "Retry-After": "60",
                "X-Rate-Limit": "600",
                "X-Rate-Limit-Remaining": "0",
                "X-Rate-Limit-Reset": "60",
            },
            json={"error": "rate limit"},
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    with pytest.raises(AviasalesDataRateLimited) as exc_info:
        client.prices_for_dates(
            PricesForDatesQuery(
                origin="WAW",
                destination="BCN",
                departure_at="2026-10-12",
                return_at=None,
                currency="PLN",
                market="pl",
                one_way=True,
                direct=False,
                limit=30,
                page=1,
            )
        )

    assert exc_info.value.retry_after_seconds == 60
    assert exc_info.value.rate_limit == AviasalesDataRateLimit(
        limit=600,
        remaining=0,
        reset=60,
    )


def test_prices_for_dates_maps_successful_response() -> None:
    received_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "WAW",
                        "destination": "BCN",
                        "origin_airport": "WAW",
                        "destination_airport": "BCN",
                        "price": 512,
                        "airline": "LO",
                        "flight_number": "437",
                        "departure_at": "2026-10-12T07:00:00+02:00",
                        "return_at": "2026-10-19T14:30:00+02:00",
                        "transfers": 0,
                        "return_transfers": 1,
                        "duration": 340,
                        "link": "/search/WAW1210BCN1910",
                    }
                ],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.prices_for_dates(
        PricesForDatesQuery(
            origin="WAW",
            destination="BCN",
            departure_at="2026-10-12",
            return_at="2026-10-19",
            currency="PLN",
            market="pl",
            one_way=False,
            direct=False,
            limit=30,
            page=1,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 51200
    assert response.items[0].departure_date == "2026-10-12"
    assert response.items[0].return_date == "2026-10-19"


def test_prices_for_dates_rejects_latest_endpoint_shape() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "origin": "WAW",
                        "destination": "BCN",
                        "value": 512,
                        "depart_date": "2026-10-12",
                        "return_date": "2026-10-19",
                        "actual": True,
                    }
                ],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    with pytest.raises(AviasalesDataError, match="aviasales_data_missing_price"):
        client.prices_for_dates(
            PricesForDatesQuery(
                origin="WAW",
                destination="BCN",
                departure_at="2026-10-12",
                return_at="2026-10-19",
                currency="PLN",
                market="pl",
                one_way=False,
                direct=False,
                limit=30,
                page=1,
            )
        )


def test_prices_for_dates_captures_rate_limit_headers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={
                "X-Rate-Limit": "600",
                "X-Rate-Limit-Remaining": "599",
                "X-Rate-Limit-Reset": "42",
            },
            json={
                "success": True,
                "data": [],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    response = client.prices_for_dates(
        PricesForDatesQuery(
            origin="WAW",
            destination="BCN",
            departure_at="2026-10-12",
            return_at=None,
            currency="PLN",
            market="pl",
            one_way=True,
            direct=False,
            limit=30,
            page=1,
        )
    )

    assert response.rate_limit == AviasalesDataRateLimit(limit=600, remaining=599, reset=42)


def test_grouped_prices_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": {}, "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.grouped_prices(
        GroupedPricesQuery(
            origin="mow",
            destination="ist",
            departure_at="2026-09",
            return_at=None,
            currency="RUB",
            market="ru",
            group_by="departure_at",
            direct=False,
            limit=30,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/grouped_prices"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["departure_at"] == "2026-09"
    assert captured_request.url.params["cy"] == "rub"
    assert captured_request.url.params["group_by"] == "departure_at"


def test_grouped_prices_maps_successful_response_mapping() -> None:
    received_at = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
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
                        "airline": "TK",
                        "flight_number": "420",
                        "link": "/search/MOW1009IST2009",
                    }
                },
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.grouped_prices(
        GroupedPricesQuery(
            origin="MOW",
            destination="IST",
            departure_at="2026-09",
            return_at="2026-09",
            currency="RUB",
            market="ru",
            group_by="departure_at",
            direct=False,
            limit=30,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"


def test_latest_prices_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.latest_prices(
        LatestPricesQuery(
            origin="mow",
            destination="ist",
            beginning_of_period="2026-09-01",
            period_type="month",
            group_by="dates",
            one_way=False,
            currency="RUB",
            market="ru",
            sorting="price",
            page=1,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/get_latest_prices"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["beginning_of_period"] == "2026-09-01"
    assert captured_request.url.params["period_type"] == "month"
    assert captured_request.url.params["group_by"] == "dates"
    assert captured_request.url.params["one_way"] == "false"
    assert captured_request.url.params["cy"] == "rub"


def test_latest_prices_maps_successful_response_list() -> None:
    received_at = datetime(2026, 6, 29, 13, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
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
                        "airline": "DP",
                        "flight_number": "993",
                        "link": "/search/MOW1109IST",
                    }
                ],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.latest_prices(
        LatestPricesQuery(
            origin="MOW",
            destination="IST",
            beginning_of_period="2026-09-01",
            period_type="month",
            group_by="dates",
            one_way=True,
            currency="RUB",
            market="ru",
            sorting="price",
            page=1,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_750_000
    assert response.items[0].departure_date == "2026-09-11"
    assert response.items[0].return_date is None


def test_latest_prices_maps_docs_style_value_dates_and_found_at() -> None:
    received_at = datetime(2026, 6, 29, 13, 0, tzinfo=UTC)
    found_at = datetime(2026, 6, 29, 8, 15, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
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
                    },
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "value": 9999,
                        "depart_date": "2026-09-13",
                        "return_date": "2026-09-21",
                        "found_at": "2026-06-01T08:15:00+00:00",
                        "actual": False,
                    },
                ],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.latest_prices(
        LatestPricesQuery(
            origin="MOW",
            destination="IST",
            beginning_of_period="2026-09-01",
            period_type="month",
            group_by="dates",
            one_way=False,
            currency="RUB",
            market="ru",
            sorting="price",
            page=1,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_760_000
    assert response.items[0].departure_date == "2026-09-12"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].found_at == found_at


def test_week_matrix_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.week_matrix(
        WeekMatrixQuery(
            origin="mow",
            destination="ist",
            depart_date="2026-09-10",
            return_date="2026-09-20",
            currency="RUB",
            market="ru",
            show_to_affiliates=True,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/v2/prices/week-matrix"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["depart_date"] == "2026-09-10"
    assert captured_request.url.params["return_date"] == "2026-09-20"
    assert captured_request.url.params["currency"] == "rub"
    assert captured_request.url.params["market"] == "ru"
    assert captured_request.url.params["show_to_affiliates"] == "true"


def test_week_matrix_maps_only_actual_cached_items() -> None:
    received_at = datetime(2026, 6, 29, 14, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "show_to_affiliates": True,
                        "trip_class": 0,
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "number_of_changes": 1,
                        "value": 18420,
                        "found_at": "2026-06-29T10:04:37+03:00",
                        "distance": 1750,
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

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.week_matrix(
        WeekMatrixQuery(
            origin="MOW",
            destination="IST",
            depart_date="2026-09-10",
            return_date="2026-09-20",
            currency="RUB",
            market="ru",
            show_to_affiliates=True,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].link_path is None


def test_month_matrix_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.month_matrix(
        MonthMatrixQuery(
            origin="mow",
            destination="ist",
            month="2026-09-01",
            currency="RUB",
            market="ru",
            show_to_affiliates=True,
            one_way=False,
            trip_duration_weeks=1,
            limit=30,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/v2/prices/month-matrix"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["month"] == "2026-09-01"
    assert captured_request.url.params["currency"] == "rub"
    assert captured_request.url.params["market"] == "ru"
    assert captured_request.url.params["show_to_affiliates"] == "true"
    assert captured_request.url.params["one_way"] == "false"
    assert captured_request.url.params["trip_duration"] == "1"
    assert captured_request.url.params["limit"] == "30"


def test_month_matrix_maps_only_actual_cached_items() -> None:
    received_at = datetime(2026, 6, 29, 15, 0, tzinfo=UTC)
    found_at = datetime(2026, 6, 29, 10, 4, 37, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"X-Rate-Limit": "300", "X-Rate-Limit-Remaining": "299"},
            json={
                "success": True,
                "data": [
                    {
                        "show_to_affiliates": True,
                        "trip_class": 0,
                        "origin": "MOW",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "number_of_changes": 1,
                        "value": 18420,
                        "found_at": "2026-06-29T10:04:37+00:00",
                        "distance": 1750,
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

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.month_matrix(
        MonthMatrixQuery(
            origin="MOW",
            destination="IST",
            month="2026-09-01",
            currency="RUB",
            market="ru",
            show_to_affiliates=True,
            one_way=False,
            trip_duration_weeks=1,
            limit=30,
        )
    )

    assert response.received_at == received_at
    assert response.rate_limit == AviasalesDataRateLimit(limit=300, remaining=299, reset=None)
    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].found_at == found_at
    assert response.items[0].link_path is None


def test_nearest_places_matrix_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.nearest_places_matrix(
        NearestPlacesMatrixQuery(
            origin="mow",
            destination="ist",
            currency="RUB",
            show_to_affiliates=True,
            distance_km=300,
            limit=30,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/v2/prices/nearest-places-matrix"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["currency"] == "rub"
    assert captured_request.url.params["show_to_affiliates"] == "true"
    assert captured_request.url.params["distance"] == "300"
    assert captured_request.url.params["limit"] == "30"


def test_nearest_places_matrix_maps_only_actual_cached_items() -> None:
    received_at = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
    found_at = datetime(2026, 6, 29, 11, 4, 37, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
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
                    },
                    {
                        "origin": "VKO",
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

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.nearest_places_matrix(
        NearestPlacesMatrixQuery(
            origin="MOW",
            destination="IST",
            currency="RUB",
            show_to_affiliates=True,
            distance_km=300,
            limit=30,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].origin == "DME"
    assert response.items[0].destination == "IST"
    assert response.items[0].price_minor_units == 1_810_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].found_at == found_at
    assert response.items[0].link_path is None


def test_nearest_places_matrix_maps_top_level_prices_payload() -> None:
    received_at = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)
    found_at = datetime(2026, 6, 29, 11, 4, 37, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "prices": [
                    {
                        "origin": "DME",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "",
                        "value": 18100.0,
                        "found_at": "2026-06-29T11:04:37+00:00",
                        "distance": 42,
                        "actual": True,
                    }
                ],
                "origins": ["DME"],
                "destinations": ["IST"],
                "errors": {},
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.nearest_places_matrix(
        NearestPlacesMatrixQuery(
            origin="MOW",
            destination="IST",
            currency="RUB",
            show_to_affiliates=True,
            distance_km=300,
            limit=30,
        )
    )

    assert response.received_at == received_at
    assert len(response.items) == 1
    assert response.items[0].origin == "DME"
    assert response.items[0].destination == "IST"
    assert response.items[0].price_minor_units == 1_810_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date is None
    assert response.items[0].found_at == found_at


def test_nearest_places_matrix_rejects_fractional_float_price() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "prices": [
                    {
                        "origin": "DME",
                        "destination": "IST",
                        "depart_date": "2026-09-10",
                        "return_date": "2026-09-20",
                        "value": 18100.5,
                        "actual": True,
                    }
                ],
                "origins": ["DME"],
                "destinations": ["IST"],
                "errors": {},
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    with pytest.raises(AviasalesDataError, match="aviasales_data_missing_value"):
        client.nearest_places_matrix(
            NearestPlacesMatrixQuery(
                origin="MOW",
                destination="IST",
                currency="RUB",
                show_to_affiliates=True,
                distance_km=300,
                limit=30,
            )
        )


def test_search_by_price_range_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.search_by_price_range(
        SearchByPriceRangeQuery(
            origin="mow",
            destination="ist",
            value_min=10_000,
            value_max=20_000,
            one_way=False,
            direct=False,
            locale="ru",
            currency="RUB",
            market="ru",
            limit=30,
            page=1,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/search_by_price_range"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["value_min"] == "10000"
    assert captured_request.url.params["value_max"] == "20000"
    assert captured_request.url.params["one_way"] == "false"
    assert captured_request.url.params["direct"] == "false"
    assert captured_request.url.params["locale"] == "ru"
    assert captured_request.url.params["currency"] == "rub"
    assert captured_request.url.params["market"] == "ru"
    assert captured_request.url.params["limit"] == "30"
    assert captured_request.url.params["page"] == "1"


def test_search_by_price_range_maps_docs_style_response() -> None:
    received_at = datetime(2026, 6, 29, 17, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"X-Rate-Limit": "600", "X-Rate-Limit-Remaining": "599"},
            json={
                "success": True,
                "currency": "rub",
                "data": [
                    {
                        "departure_at": "2026-09-10",
                        "destination_airport": "IST",
                        "destination_code": "IST",
                        "destination_name": "Istanbul",
                        "duration": 175,
                        "link": "/MOW1009IST1?t=signature",
                        "origin_airport": "DME",
                        "origin_code": "MOW",
                        "origin_name": "Moscow",
                        "price": 18420,
                        "transfers": 0,
                    }
                ],
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.search_by_price_range(
        SearchByPriceRangeQuery(
            origin="MOW",
            destination="IST",
            value_min=10_000,
            value_max=20_000,
            one_way=True,
            direct=False,
            locale="ru",
            currency="RUB",
            market="ru",
            limit=30,
            page=1,
        )
    )

    assert response.received_at == received_at
    assert response.rate_limit == AviasalesDataRateLimit(limit=600, remaining=599, reset=None)
    assert len(response.items) == 1
    assert response.items[0].origin == "MOW"
    assert response.items[0].destination == "IST"
    assert response.items[0].origin_airport == "DME"
    assert response.items[0].destination_airport == "IST"
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date is None
    assert response.items[0].link_path == "/MOW1009IST1?t=signature"


def test_popular_directions_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(
            200,
            json={
                "success": True,
                "data": {"destination": {"iata": "IST"}, "origin": []},
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.popular_directions(
        PopularDirectionsQuery(
            destination="ist",
            locale="ru",
            currency="RUB",
            limit=30,
            page=1,
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/get_popular_directions"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["locale"] == "ru"
    assert captured_request.url.params["currency"] == "rub"
    assert captured_request.url.params["limit"] == "30"
    assert captured_request.url.params["page"] == "1"


def test_popular_directions_maps_docs_style_response() -> None:
    received_at = datetime(2026, 6, 29, 17, 0, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"X-Rate-Limit": "300", "X-Rate-Limit-Remaining": "299"},
            json={
                "success": True,
                "currency": "rub",
                "data": {
                    "destination": {"iata": "IST", "name": "Istanbul"},
                    "origin": [
                        {
                            "city_iata": "MOW",
                            "city_name": "Moscow",
                            "price": 18420,
                            "departure_at": "2026-09-10",
                            "return_at": "2026-09-20",
                        }
                    ],
                },
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.popular_directions(
        PopularDirectionsQuery(
            destination="IST",
            locale="ru",
            currency="RUB",
            limit=30,
            page=1,
        )
    )

    assert response.received_at == received_at
    assert response.rate_limit == AviasalesDataRateLimit(limit=300, remaining=299, reset=None)
    assert len(response.items) == 1
    assert response.items[0].origin == "MOW"
    assert response.items[0].destination == "IST"
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].link_path is None


def test_special_offers_sends_token_in_header_and_safe_query_params() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"success": True, "data": [], "error": None})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    client.special_offers(
        SpecialOffersQuery(
            origin="mow",
            destination="ist",
            locale="ru",
            currency="RUB",
        )
    )

    assert captured_request is not None
    assert captured_request.url.path == "/aviasales/v3/get_special_offers"
    assert captured_request.headers["x-access-token"] == "test-token"
    assert "token" not in str(captured_request.url)
    assert captured_request.url.params["origin"] == "MOW"
    assert captured_request.url.params["destination"] == "IST"
    assert captured_request.url.params["locale"] == "ru"
    assert captured_request.url.params["currency"] == "rub"


def test_special_offers_maps_docs_style_response_without_booking_link() -> None:
    received_at = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)
    found_at = datetime(2026, 6, 29, 8, 15, tzinfo=UTC)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"X-Rate-Limit": "600", "X-Rate-Limit-Remaining": "599"},
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
                        "airline": "TK",
                        "flight_number": "420",
                        "found_at": "2026-06-29T08:15:00+00:00",
                        "link": "/search/MOW1009IST2009",
                        "signature": "signed-link",
                        "search_id": "provider-search-id",
                    },
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "value": 9999,
                        "depart_date": "2026-09-11",
                        "actual": False,
                    },
                ],
                "error": None,
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
        clock=lambda: received_at,
    )

    response = client.special_offers(
        SpecialOffersQuery(
            origin="MOW",
            destination="IST",
            locale="ru",
            currency="RUB",
        )
    )

    assert response.received_at == received_at
    assert response.rate_limit == AviasalesDataRateLimit(limit=600, remaining=599, reset=None)
    assert len(response.items) == 1
    assert response.items[0].origin == "MOW"
    assert response.items[0].destination == "IST"
    assert response.items[0].origin_airport == "DME"
    assert response.items[0].destination_airport == "IST"
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].departure_date == "2026-09-10"
    assert response.items[0].return_date == "2026-09-20"
    assert response.items[0].airline == "TK"
    assert response.items[0].flight_number == "420"
    assert response.items[0].found_at == found_at
    assert response.items[0].link_path is None


def test_special_offers_normalizes_empty_return_date() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "success": True,
                "currency": "rub",
                "data": [
                    {
                        "origin": "MOW",
                        "destination": "IST",
                        "value": 18420.0,
                        "depart_date": "2026-09-10",
                        "return_date": "",
                        "actual": True,
                    }
                ],
            },
        )

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    response = client.special_offers(
        SpecialOffersQuery(
            origin="MOW",
            destination="IST",
            locale="ru",
            currency="RUB",
        )
    )

    assert len(response.items) == 1
    assert response.items[0].price_minor_units == 1_842_000
    assert response.items[0].return_date is None


def test_week_matrix_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, headers={"Retry-After": "30"}, json={"error": "rate limit"})

    client = AviasalesDataClient(
        token="test-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.travelpayouts.com",
        ),
    )

    with pytest.raises(AviasalesDataRateLimited) as exc_info:
        client.week_matrix(
            WeekMatrixQuery(
                origin="MOW",
                destination="IST",
                depart_date="2026-09-10",
                return_date=None,
                currency="RUB",
                market="ru",
                show_to_affiliates=True,
            )
        )

    assert exc_info.value.retry_after_seconds == 30
