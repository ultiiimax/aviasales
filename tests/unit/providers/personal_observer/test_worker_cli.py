from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.live_observations import GrantSource
from flight_hunter.application.personal_observations import PersonalObservationService
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    LiveObservationRepository,
)
from flight_hunter.providers.personal_observer.worker_cli import main

FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 6, 29, 19, 0, tzinfo=UTC)


def test_worker_cli_runs_queued_fixture_job_and_persists_offer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "observer-worker.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    job_id = asyncio.run(_create_queued_job(database_url))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-run-personal-observation",
            "--job-id",
            str(job_id),
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["accepted"] is True
    assert body["status"] == "succeeded"
    assert body["offers_persisted"] == 1

    offers = asyncio.run(_stored_offers(database_url))
    assert len(offers) == 1
    assert offers[0].source_id == "tutu"


def test_worker_cli_marks_expired_job_without_running_observer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "observer-worker-expired.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    job_id = asyncio.run(
        _create_queued_job(
            database_url,
            clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            result_ttl=timedelta(minutes=1),
        )
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-run-personal-observation",
            "--job-id",
            str(job_id),
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["accepted"] is False
    assert body["code"] == "job_expired"
    assert body["status"] == "expired"
    assert body["offers_persisted"] == 0

    offers = asyncio.run(_stored_offers(database_url))
    job = asyncio.run(_stored_job(database_url, job_id))
    assert offers == ()
    assert job is not None
    assert job.status == ObservationStatus.EXPIRED


async def _create_queued_job(
    database_url: str,
    *,
    clock: Callable[[], datetime] | None = None,
    result_ttl: timedelta = timedelta(minutes=5),
) -> UUID:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        service = PersonalObservationService(
            jobs=BrowserObservationJobRepository(session),
            grants=LiveObservationRepository(session),
            observed_offers=BrowserObservedOfferRepository(session),
            runner=None,
            observer_enabled=True,
            clock=clock or (lambda: NOW),
            result_ttl=result_ttl,
        )
        grant = await service.issue_grant(
            user_id=USER_ID,
            source_id="tutu",
            search_intent=_intent(),
            source=GrantSource.WEB_CLICK,
        )
        created = await service.create_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            source_id="tutu",
            search_id="sha256:search",
            search_intent=_intent(),
            grant_token=grant.grant_token or "",
            idempotency_key="worker-idem",
        )
        await session.commit()
    await engine.dispose()
    assert created.job_id is not None
    return created.job_id


async def _stored_offers(database_url: str):
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        offers = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    await engine.dispose()
    return offers


async def _stored_job(database_url: str, job_id: UUID):
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        job = await BrowserObservationJobRepository(session).get_job(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            job_id=job_id,
        )
    await engine.dispose()
    return job


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )
