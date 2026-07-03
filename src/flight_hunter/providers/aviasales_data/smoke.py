from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.providers.aviasales_data.client import (
    AviasalesDataClient,
    AviasalesDataError,
    AviasalesDataRateLimited,
    AviasalesDataResponse,
    PricesForDatesQuery,
)


class SmokeClient(Protocol):
    def prices_for_dates(self, query: PricesForDatesQuery) -> AviasalesDataResponse: ...


@dataclass(frozen=True, slots=True)
class AviasalesDataSmokeResult:
    ok: bool
    code: str
    item_count: int
    received_at: datetime | None
    retry_after_seconds: int | None
    rate_limit: int | None
    rate_limit_remaining: int | None
    rate_limit_reset: int | None


def run_smoke_check(
    *,
    settings: AppSettings,
    client_factory: Callable[[str], SmokeClient] = lambda token: AviasalesDataClient(token=token),
    origin: str = "WAW",
    destination: str = "BCN",
    departure_at: str = "2026-10-12",
    return_at: str | None = "2026-10-19",
    currency: str = "PLN",
) -> AviasalesDataSmokeResult:
    token = settings.travelpayouts_api_token
    if token is None:
        return AviasalesDataSmokeResult(
            ok=False,
            code="credentials_missing",
            item_count=0,
            received_at=None,
            retry_after_seconds=None,
            rate_limit=None,
            rate_limit_remaining=None,
            rate_limit_reset=None,
        )

    query = PricesForDatesQuery(
        origin=origin,
        destination=destination,
        departure_at=departure_at,
        return_at=return_at,
        currency=currency,
        market=settings.aviasales_data_default_market,
        one_way=return_at is None,
        direct=False,
        limit=1,
        page=1,
    )
    try:
        response = client_factory(token).prices_for_dates(query)
    except AviasalesDataRateLimited as exc:
        return AviasalesDataSmokeResult(
            ok=False,
            code="rate_limited",
            item_count=0,
            received_at=None,
            retry_after_seconds=exc.retry_after_seconds,
            rate_limit=exc.rate_limit.limit if exc.rate_limit else None,
            rate_limit_remaining=exc.rate_limit.remaining if exc.rate_limit else None,
            rate_limit_reset=exc.rate_limit.reset if exc.rate_limit else None,
        )
    except AviasalesDataError:
        return AviasalesDataSmokeResult(
            ok=False,
            code="provider_error",
            item_count=0,
            received_at=None,
            retry_after_seconds=None,
            rate_limit=None,
            rate_limit_remaining=None,
            rate_limit_reset=None,
        )

    return AviasalesDataSmokeResult(
        ok=True,
        code="ok",
        item_count=len(response.items),
        received_at=response.received_at,
        retry_after_seconds=None,
        rate_limit=response.rate_limit.limit if response.rate_limit else None,
        rate_limit_remaining=response.rate_limit.remaining if response.rate_limit else None,
        rate_limit_reset=response.rate_limit.reset if response.rate_limit else None,
    )


def format_smoke_result(result: AviasalesDataSmokeResult) -> str:
    payload = asdict(result)
    payload["provider"] = "aviasales_data"
    payload["received_at"] = result.received_at.isoformat() if result.received_at else None
    ordered_payload = {
        "provider": payload["provider"],
        "ok": payload["ok"],
        "code": payload["code"],
        "item_count": payload["item_count"],
        "received_at": payload["received_at"],
        "retry_after_seconds": payload["retry_after_seconds"],
        "rate_limit": payload["rate_limit"],
        "rate_limit_remaining": payload["rate_limit_remaining"],
        "rate_limit_reset": payload["rate_limit_reset"],
    }
    return json.dumps(ordered_payload, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one sanitized Aviasales Data API smoke check."
    )
    parser.add_argument("--origin", default="WAW")
    parser.add_argument("--destination", default="BCN")
    parser.add_argument("--departure-at", default="2026-10-12")
    parser.add_argument("--return-at", default="2026-10-19")
    parser.add_argument("--currency", default="PLN")
    args = parser.parse_args()

    load_env_file()
    result = run_smoke_check(
        settings=AppSettings.from_env(),
        origin=args.origin,
        destination=args.destination,
        departure_at=args.departure_at,
        return_at=args.return_at or None,
        currency=args.currency,
    )
    print(format_smoke_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
