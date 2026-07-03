from __future__ import annotations

import json
from datetime import UTC, datetime

from flight_hunter.config import AppSettings
from flight_hunter.providers.aviasales_data.client import (
    AviasalesDataItem,
    AviasalesDataRateLimit,
    AviasalesDataRateLimited,
    AviasalesDataResponse,
    PricesForDatesQuery,
)
from flight_hunter.providers.aviasales_data.smoke import (
    AviasalesDataSmokeResult,
    format_smoke_result,
    run_smoke_check,
)

SECRET = "secret-token-value"
NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_smoke_check_reports_missing_credentials_without_live_call() -> None:
    called = False

    def factory(token: str) -> StubClient:
        nonlocal called
        called = True
        return StubClient()

    result = run_smoke_check(
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_data_enabled=False,
            travelpayouts_api_token=None,
            aviasales_data_default_market="pl",
            aviasales_data_internal_rpm=30,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
        client_factory=factory,
    )

    assert result.ok is False
    assert result.code == "credentials_missing"
    assert called is False


def test_smoke_check_returns_sanitized_success_summary() -> None:
    result = run_smoke_check(
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_data_enabled=True,
            travelpayouts_api_token=SECRET,
            aviasales_data_default_market="pl",
            aviasales_data_internal_rpm=30,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
        client_factory=lambda token: StubClient(token=token),
    )
    payload = json.loads(format_smoke_result(result))

    assert result.ok is True
    assert result.code == "ok"
    assert result.item_count == 1
    assert payload == {
        "provider": "aviasales_data",
        "ok": True,
        "code": "ok",
        "item_count": 1,
        "received_at": "2026-06-23T12:00:00+00:00",
        "retry_after_seconds": None,
        "rate_limit": 600,
        "rate_limit_remaining": 599,
        "rate_limit_reset": 42,
    }
    assert SECRET not in format_smoke_result(result)
    assert "/search/" not in format_smoke_result(result)


def test_smoke_check_reports_rate_limit_without_retry_loop() -> None:
    result = run_smoke_check(
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_data_enabled=True,
            travelpayouts_api_token=SECRET,
            aviasales_data_default_market="pl",
            aviasales_data_internal_rpm=30,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
        client_factory=lambda token: RateLimitedClient(),
    )

    assert result == AviasalesDataSmokeResult(
        ok=False,
        code="rate_limited",
        item_count=0,
        received_at=None,
        retry_after_seconds=60,
        rate_limit=600,
        rate_limit_remaining=0,
        rate_limit_reset=60,
    )
    assert SECRET not in format_smoke_result(result)


class StubClient:
    def __init__(self, token: str = SECRET) -> None:
        self.token = token

    def prices_for_dates(self, query: PricesForDatesQuery) -> AviasalesDataResponse:
        assert query.limit == 1
        assert query.market == "pl"
        assert self.token == SECRET
        return AviasalesDataResponse(
            received_at=NOW,
            rate_limit=AviasalesDataRateLimit(limit=600, remaining=599, reset=42),
            items=(
                AviasalesDataItem(
                    origin="WAW",
                    destination="BCN",
                    origin_airport="WAW",
                    destination_airport="BCN",
                    price_minor_units=51200,
                    currency="PLN",
                    departure_date="2026-10-12",
                    return_date="2026-10-19",
                    airline="LO",
                    flight_number="437",
                    link_path="/search/WAW1210BCN1910",
                ),
            ),
        )


class RateLimitedClient:
    def prices_for_dates(self, query: PricesForDatesQuery) -> AviasalesDataResponse:
        raise AviasalesDataRateLimited(
            retry_after_seconds=60,
            rate_limit=AviasalesDataRateLimit(limit=600, remaining=0, reset=60),
        )
