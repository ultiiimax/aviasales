from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError, Crawl4AiMarkdownClient
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResponse
from flight_hunter.deals.searxng_client import SearxngClient, SearxngClientError
from flight_hunter.domain.offers import FlightOffer, SearchIntent
from flight_hunter.domain.policy import ExecutionContext
from flight_hunter.providers.aviasales_search.adapter import AviasalesSearchAdapter
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchClient,
    AviasalesSearchError,
)


class SearxngSmokeClient(Protocol):
    def search(
        self,
        query: str,
        *,
        language: str = "ru",
        categories: str = "general",
    ) -> SearxngSearchResponse: ...


class Crawl4AiSmokeClient(Protocol):
    async def fetch_markdown(self, url: str, *, title: str = "") -> DealPageMarkdown: ...


class AviasalesSearchSmokeClient(Protocol):
    def suggest_places(self, term: str, *, max_results: int = 5) -> tuple[object, ...]: ...


class AviasalesSearchSmokeAdapter(Protocol):
    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext = ExecutionContext.WEB_USER_ACTION,
    ) -> tuple[FlightOffer, ...]: ...


@dataclass(frozen=True, slots=True)
class SourceSmokeResult:
    source: str
    ok: bool
    code: str
    item_count: int
    checked_at: datetime
    received_at: datetime | None = None
    retry_after_seconds: int | None = None
    rate_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: int | None = None
    message: str | None = None
    source_ids: tuple[str, ...] = ()
    freshness_values: tuple[str, ...] = ()


async def run_source_smoke(
    *,
    settings: AppSettings,
    source: str,
    query: str = "авиабилеты MOW IST акция",
    url: str | None = None,
    exact_search: bool = False,
    origin: str | None = None,
    destination: str | None = None,
    departure_offset_days: int = 30,
    aviasales_client_factory: Callable[[AppSettings], AviasalesSearchSmokeClient] | None = None,
    aviasales_adapter_factory: Callable[[AppSettings], AviasalesSearchSmokeAdapter] | None = None,
    searxng_client_factory: Callable[[AppSettings], SearxngSmokeClient] | None = None,
    crawl4ai_client_factory: Callable[[AppSettings], Crawl4AiSmokeClient] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SourceSmokeResult:
    now = clock or (lambda: datetime.now(UTC))
    aviasales_factory = aviasales_client_factory or _aviasales_search_client
    aviasales_exact_factory = aviasales_adapter_factory or _aviasales_search_adapter
    searxng_factory = searxng_client_factory or _searxng_client
    crawl4ai_factory = crawl4ai_client_factory or _crawl4ai_client
    normalized_source = source.strip().lower()
    if normalized_source == "aviasales_search":
        return _aviasales_search_smoke(
            settings=settings,
            client_factory=aviasales_factory,
            checked_at=now(),
            exact_search=exact_search,
            origin=origin,
            destination=destination,
            departure_offset_days=departure_offset_days,
            adapter_factory=aviasales_exact_factory,
        )
    if normalized_source == "searxng":
        return _searxng_smoke(
            settings=settings,
            query=query,
            client_factory=searxng_factory,
            checked_at=now(),
        )
    if normalized_source == "crawl4ai":
        return await _crawl4ai_smoke(
            settings=settings,
            url=url,
            client_factory=crawl4ai_factory,
            checked_at=now(),
        )
    return SourceSmokeResult(
        source=normalized_source or "unknown",
        ok=False,
        code="unsupported_source",
        item_count=0,
        checked_at=now(),
        message="supported sources: aviasales_search, searxng, crawl4ai",
    )


def format_source_smoke_result(result: SourceSmokeResult) -> str:
    payload = asdict(result)
    payload["checked_at"] = result.checked_at.isoformat()
    payload["received_at"] = result.received_at.isoformat() if result.received_at else None
    ordered_payload = {
        "source": payload["source"],
        "ok": payload["ok"],
        "code": payload["code"],
        "item_count": payload["item_count"],
        "checked_at": payload["checked_at"],
        "received_at": payload["received_at"],
        "retry_after_seconds": payload["retry_after_seconds"],
        "rate_limit": payload["rate_limit"],
        "rate_limit_remaining": payload["rate_limit_remaining"],
        "rate_limit_reset": payload["rate_limit_reset"],
        "message": payload["message"],
        "source_ids": payload["source_ids"],
        "freshness_values": payload["freshness_values"],
    }
    return json.dumps(ordered_payload, ensure_ascii=False, indent=2)


def _aviasales_search_smoke(
    *,
    settings: AppSettings,
    client_factory: Callable[[AppSettings], AviasalesSearchSmokeClient],
    checked_at: datetime,
    exact_search: bool,
    origin: str | None,
    destination: str | None,
    departure_offset_days: int,
    adapter_factory: Callable[[AppSettings], AviasalesSearchSmokeAdapter],
) -> SourceSmokeResult:
    if not settings.aviasales_search_enabled:
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="aviasales_search_disabled",
            item_count=0,
            checked_at=checked_at,
        )
    if not settings.aviasales_search_credentials_present:
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="aviasales_search_credentials_missing",
            item_count=0,
            checked_at=checked_at,
        )
    if not settings.aviasales_search_credentials_valid:
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="aviasales_search_credentials_invalid",
            item_count=0,
            checked_at=checked_at,
        )
    if exact_search:
        return _aviasales_exact_search_smoke(
            settings=settings,
            adapter_factory=adapter_factory,
            checked_at=checked_at,
            origin=origin,
            destination=destination,
            departure_offset_days=departure_offset_days,
        )
    try:
        places = client_factory(settings).suggest_places("LED", max_results=5)
    except AviasalesSearchError as exc:
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code=str(exc) or "aviasales_search_unavailable",
            item_count=0,
            checked_at=checked_at,
        )
    except Exception as exc:  # process boundary: classify transport/runtime failures.
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="aviasales_search_unavailable",
            item_count=0,
            checked_at=checked_at,
            message=exc.__class__.__name__,
        )
    return SourceSmokeResult(
        source="aviasales_search",
        ok=True,
        code="ok",
        item_count=len(places),
        checked_at=checked_at,
        received_at=checked_at,
    )


def _aviasales_exact_search_smoke(
    *,
    settings: AppSettings,
    adapter_factory: Callable[[AppSettings], AviasalesSearchSmokeAdapter],
    checked_at: datetime,
    origin: str | None,
    destination: str | None,
    departure_offset_days: int,
) -> SourceSmokeResult:
    if (
        origin is None
        or destination is None
        or len(origin.strip()) != 3
        or len(destination.strip()) != 3
        or not origin.isalpha()
        or not destination.isalpha()
        or departure_offset_days < 1
    ):
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="smoke_arguments_invalid",
            item_count=0,
            checked_at=checked_at,
        )
    intent = SearchIntent(
        origin=origin,
        destination=destination,
        departure_date=(checked_at.date() + timedelta(days=departure_offset_days)).isoformat(),
        return_date=None,
        passengers=1,
        currency="RUB",
    )
    try:
        offers = adapter_factory(settings).search(
            intent,
            request_fingerprint="source-smoke:exact-search",
            context=ExecutionContext.WEB_USER_ACTION,
        )
    except AviasalesSearchError as exc:
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code=exc.code,
            item_count=0,
            checked_at=checked_at,
        )
    except Exception as exc:  # process boundary: classify transport/runtime failures.
        return SourceSmokeResult(
            source="aviasales_search",
            ok=False,
            code="aviasales_search_unavailable",
            item_count=0,
            checked_at=checked_at,
            message=exc.__class__.__name__,
        )
    observed_times = [offer.observed_at for offer in offers]
    return SourceSmokeResult(
        source="aviasales_search",
        ok=True,
        code="ok",
        item_count=len(offers),
        checked_at=checked_at,
        received_at=max(observed_times) if observed_times else checked_at,
        source_ids=tuple(sorted({offer.provider_id for offer in offers})),
        freshness_values=tuple(sorted({offer.freshness.value for offer in offers})),
    )


def _searxng_smoke(
    *,
    settings: AppSettings,
    query: str,
    client_factory: Callable[[AppSettings], SearxngSmokeClient],
    checked_at: datetime,
) -> SourceSmokeResult:
    if not settings.searxng_enabled:
        return SourceSmokeResult(
            source="searxng",
            ok=False,
            code="searxng_disabled",
            item_count=0,
            checked_at=checked_at,
        )
    try:
        response = client_factory(settings).search(query)
    except SearxngClientError as exc:
        return SourceSmokeResult(
            source="searxng",
            ok=False,
            code=str(exc) or "searxng_error",
            item_count=0,
            checked_at=checked_at,
        )
    except Exception as exc:  # process boundary: classify transport/runtime failures.
        return SourceSmokeResult(
            source="searxng",
            ok=False,
            code="searxng_unavailable",
            item_count=0,
            checked_at=checked_at,
            message=exc.__class__.__name__,
        )
    return SourceSmokeResult(
        source="searxng",
        ok=True,
        code="ok",
        item_count=len(response.results),
        checked_at=checked_at,
        received_at=response.received_at,
    )


async def _crawl4ai_smoke(
    *,
    settings: AppSettings,
    url: str | None,
    client_factory: Callable[[AppSettings], Crawl4AiSmokeClient],
    checked_at: datetime,
) -> SourceSmokeResult:
    if not settings.crawl4ai_enabled:
        return SourceSmokeResult(
            source="crawl4ai",
            ok=False,
            code="crawl4ai_disabled",
            item_count=0,
            checked_at=checked_at,
        )
    if url is None or not url.strip():
        return SourceSmokeResult(
            source="crawl4ai",
            ok=False,
            code="crawl4ai_url_required",
            item_count=0,
            checked_at=checked_at,
        )
    if not url.startswith(("http://", "https://")):
        return SourceSmokeResult(
            source="crawl4ai",
            ok=False,
            code="crawl4ai_invalid_url",
            item_count=0,
            checked_at=checked_at,
        )
    try:
        page = await client_factory(settings).fetch_markdown(url, title="source smoke")
    except Crawl4AiClientError as exc:
        return SourceSmokeResult(
            source="crawl4ai",
            ok=False,
            code=str(exc) or "crawl4ai_error",
            item_count=0,
            checked_at=checked_at,
        )
    except Exception as exc:  # process boundary: classify transport/runtime failures.
        return SourceSmokeResult(
            source="crawl4ai",
            ok=False,
            code="crawl4ai_unavailable",
            item_count=0,
            checked_at=checked_at,
            message=exc.__class__.__name__,
        )
    return SourceSmokeResult(
        source="crawl4ai",
        ok=True,
        code="ok",
        item_count=1 if page.markdown.strip() else 0,
        checked_at=checked_at,
        received_at=page.fetched_at,
    )


def _searxng_client(settings: AppSettings) -> SearxngSmokeClient:
    return SearxngClient(
        base_url=settings.searxng_base_url,
        timeout_seconds=settings.searxng_timeout_seconds,
    )


def _aviasales_search_client(settings: AppSettings) -> AviasalesSearchSmokeClient:
    return AviasalesSearchClient(
        signature=settings.aviasales_search_signature or "",
        marker=settings.aviasales_search_marker or "",
    )


def _aviasales_search_adapter(settings: AppSettings) -> AviasalesSearchSmokeAdapter:
    return AviasalesSearchAdapter(
        client=AviasalesSearchClient(
            signature=settings.aviasales_search_signature or "",
            marker=settings.aviasales_search_marker or "",
        ),
        enabled=settings.aviasales_search_enabled,
        credentials_present=settings.aviasales_search_credentials_present,
        internal_rpm=settings.aviasales_search_internal_rpm,
    )


def _crawl4ai_client(settings: AppSettings) -> Crawl4AiSmokeClient:
    return Crawl4AiMarkdownClient(
        enabled=settings.crawl4ai_enabled,
        mode=settings.crawl4ai_mode,
        base_url=settings.crawl4ai_base_url,
        api_token=settings.crawl4ai_api_token,
        timeout_seconds=settings.crawl4ai_timeout_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-source-smoke",
        description="Run one sanitized source health smoke check.",
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=("aviasales_search", "searxng", "crawl4ai"),
    )
    parser.add_argument("--query", default="авиабилеты MOW IST акция")
    parser.add_argument("--url", default=None)
    parser.add_argument("--exact-search", action="store_true")
    parser.add_argument("--origin", default=None)
    parser.add_argument("--destination", default=None)
    parser.add_argument("--departure-offset-days", type=int, default=30)
    args = parser.parse_args()

    load_env_file()
    result = asyncio.run(
        run_source_smoke(
            settings=AppSettings.from_env(),
            source=args.source,
            query=args.query,
            url=args.url,
            exact_search=args.exact_search,
            origin=args.origin,
            destination=args.destination,
            departure_offset_days=args.departure_offset_days,
        )
    )
    print(format_source_smoke_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
