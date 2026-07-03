from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.deals.crawl4ai_client import Crawl4AiClientError, Crawl4AiMarkdownClient
from flight_hunter.deals.models import DealPageMarkdown, SearxngSearchResponse
from flight_hunter.deals.searxng_client import SearxngClient, SearxngClientError
from flight_hunter.providers.aviasales_data.smoke import run_smoke_check


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


async def run_source_smoke(
    *,
    settings: AppSettings,
    source: str,
    query: str = "авиабилеты MOW IST акция",
    url: str | None = None,
    searxng_client_factory: Callable[[AppSettings], SearxngSmokeClient] | None = None,
    crawl4ai_client_factory: Callable[[AppSettings], Crawl4AiSmokeClient] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> SourceSmokeResult:
    now = clock or (lambda: datetime.now(UTC))
    searxng_factory = searxng_client_factory or _searxng_client
    crawl4ai_factory = crawl4ai_client_factory or _crawl4ai_client
    normalized_source = source.strip().lower()
    if normalized_source == "aviasales_data":
        return _aviasales_data_smoke(settings=settings, checked_at=now())
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
        message="supported sources: aviasales_data, searxng, crawl4ai",
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
    }
    return json.dumps(ordered_payload, ensure_ascii=False, indent=2)


def _aviasales_data_smoke(
    *,
    settings: AppSettings,
    checked_at: datetime,
) -> SourceSmokeResult:
    result = run_smoke_check(settings=settings)
    return SourceSmokeResult(
        source="aviasales_data",
        ok=result.ok,
        code=result.code,
        item_count=result.item_count,
        checked_at=checked_at,
        received_at=result.received_at,
        retry_after_seconds=result.retry_after_seconds,
        rate_limit=result.rate_limit,
        rate_limit_remaining=result.rate_limit_remaining,
        rate_limit_reset=result.rate_limit_reset,
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
        choices=("aviasales_data", "searxng", "crawl4ai"),
    )
    parser.add_argument("--query", default="авиабилеты MOW IST акция")
    parser.add_argument("--url", default=None)
    args = parser.parse_args()

    load_env_file()
    result = asyncio.run(
        run_source_smoke(
            settings=AppSettings.from_env(),
            source=args.source,
            query=args.query,
            url=args.url,
        )
    )
    print(format_source_smoke_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
