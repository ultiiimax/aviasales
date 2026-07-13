from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.live_observations import GrantSource
from flight_hunter.application.personal_observations import PersonalObservationService
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import (
    LiveObservation,
    ObservationErrorCode,
    ObservationStatus,
)
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.policy import UserActionGrant
from flight_hunter.domain.search_results import BrowserObservedOffer, Confidence, DealCandidate
from flight_hunter.ops.worker import main, run_loop
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRecord,
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    DealCandidateRepository,
    DealDiscoveryJobRepository,
    HouseholdWatchRepository,
    LiveObservationRepository,
    NewDealCandidate,
    NewDealDiscoveryJob,
    NewWatch,
    PriceSnapshotRecord,
    PriceSnapshotRepository,
    SourceHealthEventRecord,
    SourceHealthEventRepository,
    WorkerControlRepository,
    WorkerHeartbeatRecord,
    WorkerHeartbeatRepository,
)
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverError,
    PersonalObserverErrorCode,
)

FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime.now(UTC)


def test_worker_processes_queued_browser_observation_jobs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_queued_job(database_url))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body == {
        "browser_jobs_seen": 1,
        "browser_jobs_succeeded": 1,
        "browser_jobs_retry_scheduled": 0,
        "browser_jobs_failed": 0,
        "browser_jobs_recovered_stale": 0,
        "source_health_events_recorded": 1,
        "watch_due_seen": 0,
        "watch_jobs_enqueued": 0,
        "watch_jobs_already_queued": 0,
        "watch_jobs_processed": 0,
        "watch_jobs_succeeded": 0,
        "watch_jobs_retry_scheduled": 0,
        "watch_jobs_failed": 0,
        "watch_jobs_recovered_stale": 0,
        "watch_watches_skipped": 0,
        "watch_provider_calls": 0,
        "watch_provider_failures": 0,
        "watch_snapshots_saved": 0,
        "watch_alerts_recorded": 0,
        "watch_telegram_notifications_enqueued": 0,
        "deal_jobs_processed": 0,
        "deal_jobs_succeeded": 0,
        "deal_jobs_retry_scheduled": 0,
        "deal_jobs_failed": 0,
        "deal_jobs_recovered_stale": 0,
        "deal_candidates_saved": 0,
        "telegram_notifications_seen": 0,
        "telegram_notifications_sent": 0,
        "telegram_notifications_retry_scheduled": 0,
        "telegram_notifications_failed": 0,
        "telegram_notifications_deferred_quiet_hours": 0,
        "telegram_notifications_recovered_stale": 0,
        "live_cleanup_grants_deleted": 0,
        "live_cleanup_observations_deleted": 0,
        "live_cleanup_offers_deleted": 0,
        "live_cleanup_idempotency_deleted": 0,
        "deal_candidates_deleted": 0,
    }
    offers = asyncio.run(_stored_offers(database_url))
    health_events = asyncio.run(_stored_health_events(database_url))
    heartbeats = asyncio.run(_stored_worker_heartbeats(database_url))
    assert len(offers) == 1
    assert offers[0].source_id == "tutu"
    assert len(health_events) == 1
    assert health_events[0].source_id == "tutu"
    assert health_events[0].status == "ok"
    assert len(heartbeats) == 1
    assert heartbeats[0].worker_id == "flight-hunter-worker"
    assert heartbeats[0].status == "stopped"
    assert '"browser_jobs_succeeded": 1' in heartbeats[0].last_summary_json


def test_worker_fails_without_retry_when_playwright_runtime_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-playwright-unavailable.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_queued_job(database_url))
    monkeypatch.setattr(
        "flight_hunter.ops.worker.PersonalObserverRunner",
        WorkerPlaywrightUnavailableRunner,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--max-attempts",
            "2",
            "--retry-delay-seconds",
            "30",
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["browser_jobs_seen"] == 1
    assert body["browser_jobs_succeeded"] == 0
    assert body["browser_jobs_retry_scheduled"] == 0
    assert body["browser_jobs_failed"] == 1
    assert body["source_health_events_recorded"] == 1
    offers = asyncio.run(_stored_offers(database_url))
    job = asyncio.run(_stored_browser_job(database_url, idempotency_key="worker-idem-0"))
    health_events = asyncio.run(_stored_health_events(database_url))
    assert offers == ()
    assert job is not None
    assert job.status == ObservationStatus.FAILED
    assert job.error_code == ObservationErrorCode.BROWSER_RUNTIME_UNAVAILABLE
    assert job.next_retry_at is None
    assert len(health_events) == 1
    assert health_events[0].status == "failed"


def test_worker_respects_personal_observer_claim_limits(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-limits.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_queued_job(database_url, count=2))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PERSONAL_OBSERVER_MAX_CONCURRENT", "1")
    monkeypatch.setenv("PERSONAL_OBSERVER_MIN_GAP_SECONDS", "60")
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
            "--limit",
            "5",
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["browser_jobs_seen"] == 1
    assert body["browser_jobs_succeeded"] == 1
    assert body["source_health_events_recorded"] == 1


def test_worker_recovers_stale_browser_lock_before_claiming(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-stale.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_stale_claimed_job(database_url))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
            "--stale-lock-seconds",
            "900",
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["browser_jobs_recovered_stale"] == 1
    assert body["browser_jobs_seen"] == 1
    assert body["browser_jobs_succeeded"] == 1
    offers = asyncio.run(_stored_offers(database_url))
    assert len(offers) == 1


def test_worker_loop_can_stop_after_idle_iteration(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-loop.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_empty_database(database_url))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--loop",
            "--stop-after-iterations",
            "1",
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body == {
        "browser_jobs_seen": 0,
        "browser_jobs_succeeded": 0,
        "browser_jobs_retry_scheduled": 0,
        "browser_jobs_failed": 0,
        "browser_jobs_recovered_stale": 0,
        "source_health_events_recorded": 0,
        "watch_due_seen": 0,
        "watch_jobs_enqueued": 0,
        "watch_jobs_already_queued": 0,
        "watch_jobs_processed": 0,
        "watch_jobs_succeeded": 0,
        "watch_jobs_retry_scheduled": 0,
        "watch_jobs_failed": 0,
        "watch_jobs_recovered_stale": 0,
        "watch_watches_skipped": 0,
        "watch_provider_calls": 0,
        "watch_provider_failures": 0,
        "watch_snapshots_saved": 0,
        "watch_alerts_recorded": 0,
        "watch_telegram_notifications_enqueued": 0,
        "deal_jobs_processed": 0,
        "deal_jobs_succeeded": 0,
        "deal_jobs_retry_scheduled": 0,
        "deal_jobs_failed": 0,
        "deal_jobs_recovered_stale": 0,
        "deal_candidates_saved": 0,
        "telegram_notifications_seen": 0,
        "telegram_notifications_sent": 0,
        "telegram_notifications_retry_scheduled": 0,
        "telegram_notifications_failed": 0,
        "telegram_notifications_deferred_quiet_hours": 0,
        "telegram_notifications_recovered_stale": 0,
        "live_cleanup_grants_deleted": 0,
        "live_cleanup_observations_deleted": 0,
        "live_cleanup_offers_deleted": 0,
        "live_cleanup_idempotency_deleted": 0,
        "deal_candidates_deleted": 0,
    }


def test_worker_loop_stops_after_signal_aware_idle_sleep(tmp_path: Path) -> None:
    db_path = tmp_path / "worker-loop-stop.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_empty_database(database_url))
    stop_requested = False
    sleep_calls: list[float] = []

    async def sleep(seconds: float) -> None:
        nonlocal stop_requested
        sleep_calls.append(seconds)
        stop_requested = True

    summary = asyncio.run(
        run_loop(
            database_url=database_url,
            settings=_settings(),
            idle_sleep_seconds=0.25,
            process_watch_scans=False,
            cleanup_expired_live_observations=False,
            sleep=sleep,
            stop_requested=lambda: stop_requested,
        )
    )

    assert sleep_calls == [0.25]
    assert summary.browser_jobs_seen == 0
    assert summary.watch_jobs_processed == 0
    assert summary.telegram_notifications_seen == 0


def test_worker_processes_due_watch_scan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-watch.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_due_watch(database_url))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["browser_jobs_seen"] == 0
    assert body["watch_due_seen"] == 1
    assert body["watch_jobs_enqueued"] == 1
    assert body["watch_jobs_processed"] == 1
    assert body["watch_jobs_succeeded"] == 1
    assert body["watch_provider_calls"] == 1
    assert body["watch_snapshots_saved"] == 1
    assert body["source_health_events_recorded"] == 1
    history = asyncio.run(_stored_price_history(database_url))
    assert len(history) == 1
    assert history[0].provider_id == "fake"


def test_worker_processes_queued_deal_discovery_job(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-deals.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_deal_discovery_job(database_url))
    monkeypatch.setattr(
        "flight_hunter.ops.worker._deal_discovery_service",
        lambda _settings: WorkerDealDiscovery(),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["deal_jobs_processed"] == 1
    assert body["deal_jobs_succeeded"] == 1
    assert body["deal_jobs_retry_scheduled"] == 0
    assert body["deal_jobs_failed"] == 0
    assert body["deal_candidates_saved"] == 1
    assert body["source_health_events_recorded"] == 1
    candidates = asyncio.run(_stored_deal_candidates(database_url))
    health_events = asyncio.run(_stored_health_events(database_url, source_id="deal_discovery"))
    assert len(candidates) == 1
    assert candidates[0].source_id == "deal_discovery"
    assert candidates[0].requires_manual_verification is True
    assert candidates[0].expires_at is not None
    assert len(health_events) == 1
    assert health_events[0].event_type == "deal_discovery_job"
    assert health_events[0].status == "ok"


def test_worker_role_deal_only_skips_watch_lane(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-deal-role.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_due_watch(database_url))
    asyncio.run(_create_deal_discovery_job(database_url))
    monkeypatch.setattr(
        "flight_hunter.ops.worker._deal_discovery_service",
        lambda _settings: WorkerDealDiscovery(),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--role",
            "deal",
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["deal_jobs_processed"] == 1
    assert body["deal_jobs_succeeded"] == 1
    assert body["watch_due_seen"] == 0
    assert body["watch_jobs_processed"] == 0
    assert body["watch_snapshots_saved"] == 0
    history = asyncio.run(_stored_price_history(database_url))
    heartbeats = asyncio.run(_stored_worker_heartbeats(database_url))
    assert history == ()
    assert heartbeats[0].worker_id == "flight-hunter-deal-worker"
    assert heartbeats[0].role == "deal"
    assert heartbeats[0].current_job_kind is None
    assert heartbeats[0].current_job_id is None


def test_worker_cleans_expired_live_observation_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-cleanup.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_expired_live_state(database_url))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body == {
        "browser_jobs_seen": 0,
        "browser_jobs_succeeded": 0,
        "browser_jobs_retry_scheduled": 0,
        "browser_jobs_failed": 0,
        "browser_jobs_recovered_stale": 0,
        "source_health_events_recorded": 0,
        "watch_due_seen": 0,
        "watch_jobs_enqueued": 0,
        "watch_jobs_already_queued": 0,
        "watch_jobs_processed": 0,
        "watch_jobs_succeeded": 0,
        "watch_jobs_retry_scheduled": 0,
        "watch_jobs_failed": 0,
        "watch_jobs_recovered_stale": 0,
        "watch_watches_skipped": 0,
        "watch_provider_calls": 0,
        "watch_provider_failures": 0,
        "watch_snapshots_saved": 0,
        "watch_alerts_recorded": 0,
        "watch_telegram_notifications_enqueued": 0,
        "deal_jobs_processed": 0,
        "deal_jobs_succeeded": 0,
        "deal_jobs_retry_scheduled": 0,
        "deal_jobs_failed": 0,
        "deal_jobs_recovered_stale": 0,
        "deal_candidates_saved": 0,
        "telegram_notifications_seen": 0,
        "telegram_notifications_sent": 0,
        "telegram_notifications_retry_scheduled": 0,
        "telegram_notifications_failed": 0,
        "telegram_notifications_deferred_quiet_hours": 0,
        "telegram_notifications_recovered_stale": 0,
        "live_cleanup_grants_deleted": 1,
        "live_cleanup_observations_deleted": 1,
        "live_cleanup_offers_deleted": 1,
        "live_cleanup_idempotency_deleted": 1,
        "deal_candidates_deleted": 1,
    }


def test_worker_drain_skips_new_claims_but_runs_maintenance(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "worker-drain.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_queued_job(database_url))
    asyncio.run(_create_expired_live_state(database_url))
    asyncio.run(_set_worker_drain(database_url))
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-worker",
            "--database-url",
            database_url,
            "--fixture-html",
            str(FIXTURE),
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    queued = asyncio.run(_queued_browser_jobs(database_url))
    offers = asyncio.run(_stored_offers(database_url))
    assert body["browser_jobs_seen"] == 0
    assert body["browser_jobs_succeeded"] == 0
    assert body["browser_jobs_recovered_stale"] == 0
    assert body["watch_jobs_processed"] == 0
    assert body["deal_jobs_processed"] == 0
    assert body["telegram_notifications_seen"] == 0
    assert body["live_cleanup_grants_deleted"] == 1
    assert body["live_cleanup_observations_deleted"] == 1
    assert body["deal_candidates_deleted"] == 1
    assert len(queued) == 1
    assert queued[0].status == ObservationStatus.QUEUED
    assert offers == ()


async def _create_empty_database(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    await engine.dispose()


async def _set_worker_drain(database_url: str) -> None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await WorkerControlRepository(session).set_drain(
            drain_requested=True,
            reason="deploy window",
            requested_by_household_id=HOUSEHOLD_ID,
            requested_by_user_id=USER_ID,
            changed_at=datetime.now(UTC),
        )
        await session.commit()
    await engine.dispose()


async def _create_expired_live_state(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        repository = LiveObservationRepository(session)
        grant = UserActionGrant(
            id=UUID("55555555-5555-5555-5555-555555555555"),
            user_id=USER_ID,
            provider_id="demo_browser",
            action_type="live_observation",
            request_fingerprint="sha256:intent",
            issued_at=datetime(2020, 1, 1, tzinfo=UTC),
            expires_at=datetime(2020, 1, 1, 0, 5, tzinfo=UTC),
            source="web_click",
            consumed_at=None,
        )
        observation_id = UUID("66666666-6666-6666-6666-666666666666")
        await repository.add_grant(grant)
        await repository.add_observation(
            LiveObservation(
                observation_id=observation_id,
                grant_id=grant.id,
                user_id=USER_ID,
                source_id="demo_browser",
                search_intent_hash="sha256:intent",
                status=ObservationStatus.SUCCEEDED,
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
                started_at=datetime(2020, 1, 1, 0, 1, tzinfo=UTC),
                completed_at=datetime(2020, 1, 1, 0, 1, tzinfo=UTC),
                expires_at=datetime(2020, 1, 1, 0, 5, tzinfo=UTC),
                offers=(_live_offer(observation_id),),
                error_code=None,
                error_message=None,
            )
        )
        await repository.record_idempotency(
            user_id=USER_ID,
            idempotency_key="expired-idem",
            observation_id=observation_id,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        await DealCandidateRepository(session).add_candidate(
            NewDealCandidate(
                id=UUID("77777777-7777-7777-7777-777777777777"),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                search_id="sha256:intent",
                candidate=DealCandidate(
                    source_id="deal_discovery",
                    url="https://example.com/expired-deal",
                    title="Expired deal",
                    summary_ru="Manual verification required.",
                    extracted_price=Money(1_842_000, "RUB"),
                    extracted_origin="MOW",
                    extracted_destination="IST",
                    extracted_date_window="2026-09",
                    confidence=Confidence.LOW,
                    discovered_at=datetime(2020, 1, 1, tzinfo=UTC),
                    expires_at=datetime(2020, 1, 1, 0, 5, tzinfo=UTC),
                ),
                expires_at=datetime(2020, 1, 1, 0, 5, tzinfo=UTC),
            )
        )
        await session.commit()
    await engine.dispose()


async def _create_queued_job(database_url: str, *, count: int = 1) -> None:
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
            clock=lambda: NOW,
            result_ttl=timedelta(minutes=5),
        )
        for index in range(count):
            grant = await service.issue_grant(
                user_id=USER_ID,
                source_id="tutu",
                search_intent=_intent(),
                source=GrantSource.WEB_CLICK,
            )
            await service.create_job(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                source_id="tutu",
                search_id="sha256:search",
                search_intent=_intent(),
                grant_token=grant.grant_token or "",
                idempotency_key=f"worker-idem-{index}",
            )
        await session.commit()
    await engine.dispose()


async def _create_stale_claimed_job(database_url: str) -> None:
    await _create_queued_job(database_url)
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await BrowserObservationJobRepository(session).claim_queued(
            now=datetime.now(UTC) - timedelta(minutes=30),
            limit=10,
            worker_id="crashed-worker",
        )
        await session.commit()
    await engine.dispose()


async def _create_due_watch(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await HouseholdWatchRepository(session).add_watch(
            NewWatch(
                id=UUID("77777777-7777-7777-7777-777777777777"),
                household_id=HOUSEHOLD_ID,
                owner_user_id=USER_ID,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date="2026-10-19",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                passengers=1,
                currency="RUB",
                next_eligible_at=datetime(2026, 1, 1, tzinfo=UTC),
                scan_interval_seconds=3600,
            )
        )
        await session.commit()
    await engine.dispose()


async def _create_deal_discovery_job(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await DealDiscoveryJobRepository(session).enqueue_job(
            NewDealDiscoveryJob(
                id=UUID("88888888-8888-8888-8888-888888888888"),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                search_id="sha256:search",
                idempotency_key="deal-discovery:worker-test",
                status="queued",
                attempts=0,
                max_attempts=3,
                deadline_at=datetime.now(UTC) + timedelta(minutes=5),
                created_at=datetime.now(UTC) - timedelta(minutes=1),
                search_intent_json=(
                    '{"origin":"MOW","destination":"IST","departure_date":"2026-09-10",'
                    '"return_date":"2026-09-20","passengers":1,"currency":"RUB"}'
                ),
                limit=3,
            )
        )
        await session.commit()
    await engine.dispose()


async def _stored_offers(database_url: str) -> tuple[BrowserObservedOffer, ...]:
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


async def _queued_browser_jobs(
    database_url: str,
    *,
    now: datetime | None = None,
) -> tuple[BrowserObservationJobRecord, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        jobs = await BrowserObservationJobRepository(session).list_queued(
            now=now or datetime.now(UTC),
            limit=10,
        )
    await engine.dispose()
    return jobs


async def _stored_browser_job(
    database_url: str,
    *,
    idempotency_key: str,
) -> BrowserObservationJobRecord | None:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        repository = BrowserObservationJobRepository(session)
        job_id = await repository.get_idempotent_job_id(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            idempotency_key=idempotency_key,
        )
        job = await repository.get_job_by_id(job_id) if job_id is not None else None
    await engine.dispose()
    return job


async def _stored_price_history(database_url: str) -> tuple[PriceSnapshotRecord, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        history = await PriceSnapshotRepository(session).list_history(
            HOUSEHOLD_ID,
            UUID("77777777-7777-7777-7777-777777777777"),
        )
    await engine.dispose()
    return history


async def _stored_health_events(
    database_url: str,
    *,
    source_id: str = "tutu",
) -> tuple[SourceHealthEventRecord, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        events = await SourceHealthEventRepository(session).list_recent(source_id=source_id)
    await engine.dispose()
    return events


async def _stored_deal_candidates(database_url: str) -> tuple[DealCandidate, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        candidates = await DealCandidateRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=datetime(2026, 1, 1, tzinfo=UTC),
        )
    await engine.dispose()
    return candidates


async def _stored_worker_heartbeats(database_url: str) -> tuple[WorkerHeartbeatRecord, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        heartbeats = await WorkerHeartbeatRepository(session).list_recent(limit=10)
    await engine.dispose()
    return heartbeats


def _intent() -> SearchIntent:
    return SearchIntent(
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        passengers=1,
        currency="RUB",
    )


class WorkerDealDiscovery:
    async def discover(self, intent: SearchIntent, *, limit: int = 5) -> tuple[DealCandidate, ...]:
        assert intent.origin == "MOW"
        return (
            DealCandidate(
                source_id="deal_discovery",
                url="https://example.com/worker-deal?utm_source=test",
                title="MOW IST worker deal",
                summary_ru="Manual verification required.",
                extracted_price=Money(1_842_000, "RUB"),
                extracted_origin="MOW",
                extracted_destination="IST",
                extracted_date_window="2026-09",
                confidence=Confidence.MEDIUM,
                discovered_at=datetime.now(UTC),
                requires_manual_verification=True,
            ),
        )


class WorkerPlaywrightUnavailableRunner:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ):
        raise PersonalObserverError(
            PersonalObserverErrorCode.PLAYWRIGHT_UNAVAILABLE,
            "playwright is not installed; sync the scraping dependency group",
        )


def _live_offer(observation_id: UUID) -> FlightOffer:
    return FlightOffer(
        provider_id="demo_browser",
        provider_offer_id=f"offer-{observation_id}",
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        total_price=Money(1_842_000, "RUB"),
        passengers=1,
        observed_at=datetime(2020, 1, 1, 0, 1, tzinfo=UTC),
        freshness=Freshness.LIVE_OBSERVED,
        requires_live_confirmation=True,
        baggage_summary=None,
    )


def _settings() -> AppSettings:
    return AppSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        aviasales_search_enabled=False,
        aviasales_search_signature=None,
        aviasales_search_marker=None,
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
    )
