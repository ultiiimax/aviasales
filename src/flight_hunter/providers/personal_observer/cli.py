from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import NoReturn
from uuid import UUID

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.persistence.repositories import BrowserObservedOfferRepository
from flight_hunter.providers.personal_observer.crawl4ai_diagnostics import (
    crawl4ai_browser_markdown_provider_from_settings,
)
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverConfig,
    PersonalObserverError,
    PersonalObserverResult,
    PersonalObserverRunner,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-observe",
        description="Run a user-action Personal Browser Observer check.",
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--depart", required=True)
    parser.add_argument("--return-date", default=None)
    parser.add_argument("--passengers", type=int, default=1)
    parser.add_argument("--adults", type=int, default=None)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--infants", type=int, default=0)
    parser.add_argument("--currency", default="RUB")
    parser.add_argument("--fixture-html", type=Path, default=None)
    parser.add_argument("--crawl4ai-markdown-fixture", type=Path, default=None)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--household-id", default=None)
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--search-id", default=None)
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
    runner = PersonalObserverRunner(
        config=PersonalObserverConfig.from_settings(settings),
        crawl4ai_markdown_provider=crawl4ai_browser_markdown_provider_from_settings(settings),
    )
    intent = SearchIntent(
        origin=args.origin,
        destination=args.destination,
        departure_date=args.depart,
        return_date=args.return_date,
        passengers=args.passengers,
        adults=args.adults,
        children=args.children,
        infants=args.infants,
        currency=args.currency,
    )
    try:
        result = runner.observe(
            source_id=args.source,
            intent=intent,
            user_action=args.interactive,
            fixture_html_path=args.fixture_html,
            crawl4ai_markdown_fixture_path=args.crawl4ai_markdown_fixture,
        )
    except PersonalObserverError as exc:
        _exit_with_error(exc)

    persisted_count = 0
    if args.persist:
        persisted_count = asyncio.run(
            _persist_result(
                result,
                database_url=args.database_url or settings.database_url,
                household_id=_required_uuid(args.household_id, "--household-id"),
                user_id=_required_uuid(args.user_id, "--user-id"),
                search_id=_required_text(args.search_id, "--search-id"),
                ttl_seconds=settings.personal_observer_result_ttl_seconds,
            )
        )

    print(
        json.dumps(
            {
                "source_id": result.source_id,
                "final_url": result.final_url,
                "confidence": result.extraction.confidence.value,
                "warnings": list(result.extraction.warnings),
                "persisted_count": persisted_count,
                "offers": [
                    {
                        "origin": offer.origin,
                        "destination": offer.destination,
                        "departure_date": offer.departure_date,
                        "return_date": offer.return_date,
                        "amount_minor": (
                            offer.total_price.minor_units if offer.total_price is not None else None
                        ),
                        "currency": (
                            offer.total_price.currency if offer.total_price is not None else None
                        ),
                        "observed_at": offer.observed_at.isoformat(),
                        "freshness": offer.freshness.value,
                        "parser_version": offer.parser_version,
                        "parser_warnings": list(offer.parser_warnings),
                        "requires_external_confirmation": offer.requires_external_confirmation,
                    }
                    for offer in result.extraction.offers
                ],
            },
            ensure_ascii=False,
        )
    )


def _exit_with_error(error: PersonalObserverError) -> NoReturn:
    print(
        json.dumps(
            {"code": error.code.value, "message": error.message},
            ensure_ascii=False,
        )
    )
    raise SystemExit(2)


async def _persist_result(
    result: PersonalObserverResult,
    *,
    database_url: str,
    household_id: UUID,
    user_id: UUID,
    search_id: str,
    ttl_seconds: int,
) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from flight_hunter.persistence.database import create_database_engine

    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        repository = BrowserObservedOfferRepository(session)
        for offer in result.extraction.offers:
            await repository.add_offer(
                household_id=household_id,
                user_id=user_id,
                search_id=search_id,
                offer=offer,
                expires_at=offer.observed_at + timedelta(seconds=ttl_seconds),
            )
        await session.commit()
    await engine.dispose()
    return len(result.extraction.offers)


def _required_uuid(value: str | None, name: str) -> UUID:
    if value is None or not value.strip():
        raise SystemExit(f"{name} is required with --persist")
    return UUID(value)


def _required_text(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise SystemExit(f"{name} is required with --persist")
    return value.strip()
