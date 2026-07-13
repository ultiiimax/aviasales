from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from flight_hunter.application.personal_observations import PersonalObservationService
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    LiveObservationRepository,
)
from flight_hunter.providers.personal_observer.adapter import PersonalObserverRunnerAdapter
from flight_hunter.providers.personal_observer.crawl4ai_diagnostics import (
    crawl4ai_browser_markdown_provider_from_settings,
)
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverConfig,
    PersonalObserverRunner,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="flight-hunter-run-personal-observation")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--fixture-html", type=Path, default=None)
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
    try:
        job_id = UUID(args.job_id)
    except ValueError as exc:
        raise SystemExit("--job-id must be a UUID") from exc

    result = asyncio.run(
        _run_job(
            job_id=job_id,
            database_url=args.database_url or settings.database_url,
            settings=settings,
            fixture_html_path=args.fixture_html,
        )
    )
    print(json.dumps(result, ensure_ascii=False))
    if not result["accepted"]:
        raise SystemExit(2)


async def _run_job(
    *,
    job_id: UUID,
    database_url: str,
    settings: AppSettings,
    fixture_html_path: Path | None,
) -> dict[str, object]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from flight_hunter.persistence.database import create_database_engine

    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        runner = PersonalObserverRunnerAdapter(
            PersonalObserverRunner(
                config=PersonalObserverConfig.from_settings(settings),
                crawl4ai_markdown_provider=crawl4ai_browser_markdown_provider_from_settings(
                    settings
                ),
            )
        )
        service = PersonalObservationService(
            jobs=BrowserObservationJobRepository(session),
            grants=LiveObservationRepository(session),
            observed_offers=BrowserObservedOfferRepository(session),
            runner=runner,
            observer_enabled=settings.personal_observer_enabled,
            result_ttl=timedelta(seconds=settings.personal_observer_result_ttl_seconds),
            runtime_status_committer=session.commit,
        )
        decision = await service.run_job(job_id=job_id, fixture_html_path=fixture_html_path)
        await session.commit()
    await engine.dispose()
    job = decision.job
    return {
        "accepted": decision.accepted,
        "code": decision.code.value,
        "message": decision.message,
        "job_id": str(job_id),
        "status": job.status.value if job is not None else None,
        "offers_persisted": decision.offers_persisted,
    }
