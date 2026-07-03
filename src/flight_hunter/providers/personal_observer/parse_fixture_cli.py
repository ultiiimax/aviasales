from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import NoReturn

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverConfig,
    PersonalObserverError,
    PersonalObserverResult,
    PersonalObserverRunner,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="flight-hunter-parse-fixture",
        description=(
            "Parse a sanitized Personal Browser Observer HTML fixture without live browser work."
        ),
    )
    parser.add_argument("fixture_html", type=Path)
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
    parser.add_argument("--crawl4ai-markdown-fixture", type=Path, default=None)
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
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
        result = PersonalObserverRunner(
            config=PersonalObserverConfig.from_settings(settings),
        ).observe(
            source_id=args.source,
            intent=intent,
            user_action=True,
            fixture_html_path=args.fixture_html,
            crawl4ai_markdown_fixture_path=args.crawl4ai_markdown_fixture,
        )
    except PersonalObserverError as exc:
        _exit_with_error(exc)
    print(format_fixture_parse_result(result))


def format_fixture_parse_result(result: PersonalObserverResult) -> str:
    return json.dumps(
        {
            "source_id": result.source_id,
            "final_url": result.final_url,
            "confidence": result.extraction.confidence.value,
            "warnings": list(result.extraction.warnings),
            "raw_price_candidate_count": len(result.extraction.raw_price_candidates),
            "offers": [
                {
                    "observation_id": str(offer.observation_id),
                    "provider_offer_id": offer.provider_offer_id,
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


def _exit_with_error(error: PersonalObserverError) -> NoReturn:
    print(
        json.dumps(
            {"code": error.code.value, "message": error.message},
            ensure_ascii=False,
        )
    )
    raise SystemExit(2)
