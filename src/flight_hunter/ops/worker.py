from __future__ import annotations

import argparse
import asyncio
import json
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from flight_hunter.application.deal_discovery_jobs import (
    DealDiscoveryJobRunSummary,
    DealDiscoveryJobService,
)
from flight_hunter.application.personal_observations import (
    PersonalObservationRunDecision,
    PersonalObservationService,
)
from flight_hunter.application.telegram_notifications import (
    TelegramBotApiTransport,
    TelegramDeliverySummary,
    TelegramNotificationService,
    TelegramQuietHours,
)
from flight_hunter.application.watch_scans import WatchScanRunSummary, WatchScanService
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.deals import DealDiscoveryService
from flight_hunter.deals.crawl4ai_client import Crawl4AiMarkdownClient
from flight_hunter.deals.searxng_client import SearxngClient
from flight_hunter.notifications.alerts import AlertEvaluator
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.repositories import (
    AlertDedupeRepository,
    BrowserObservationJobRecord,
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    DealCandidateRepository,
    DealDiscoveryJobRepository,
    HouseholdWatchRepository,
    LiveObservationRepository,
    NewSourceHealthEvent,
    NewWorkerHeartbeat,
    PriceSnapshotRepository,
    SourceHealthEventRepository,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
    WatchScanJobRepository,
    WorkerControlRepository,
    WorkerHeartbeatRepository,
)
from flight_hunter.providers.aviasales_search.adapter import AviasalesSearchAdapter
from flight_hunter.providers.aviasales_search.client import AviasalesSearchClient
from flight_hunter.providers.fake import FakeFlightProvider
from flight_hunter.providers.personal_observer import (
    PersonalObserverConfig,
    PersonalObserverRunner,
    PersonalObserverRunnerAdapter,
    crawl4ai_browser_markdown_provider_from_settings,
)

DEFAULT_WORKER_ROLES = ("browser", "watch", "deal", "telegram", "maintenance")
_WORKER_ROLE_VALUES = frozenset(DEFAULT_WORKER_ROLES)


@dataclass(frozen=True, slots=True)
class WorkerRunSummary:
    browser_jobs_seen: int
    browser_jobs_succeeded: int
    browser_jobs_retry_scheduled: int
    browser_jobs_failed: int
    browser_jobs_recovered_stale: int
    source_health_events_recorded: int
    watch_due_seen: int
    watch_jobs_enqueued: int
    watch_jobs_already_queued: int
    watch_jobs_processed: int
    watch_jobs_succeeded: int
    watch_jobs_retry_scheduled: int
    watch_jobs_failed: int
    watch_jobs_recovered_stale: int
    watch_watches_skipped: int
    watch_provider_calls: int
    watch_provider_failures: int
    watch_snapshots_saved: int
    watch_alerts_recorded: int
    watch_telegram_notifications_enqueued: int
    deal_jobs_processed: int
    deal_jobs_succeeded: int
    deal_jobs_retry_scheduled: int
    deal_jobs_failed: int
    deal_jobs_recovered_stale: int
    deal_candidates_saved: int
    telegram_notifications_seen: int
    telegram_notifications_sent: int
    telegram_notifications_retry_scheduled: int
    telegram_notifications_failed: int
    telegram_notifications_deferred_quiet_hours: int
    telegram_notifications_recovered_stale: int
    live_cleanup_grants_deleted: int
    live_cleanup_observations_deleted: int
    live_cleanup_offers_deleted: int
    live_cleanup_idempotency_deleted: int
    deal_candidates_deleted: int

    def merge(self, other: WorkerRunSummary) -> WorkerRunSummary:
        return WorkerRunSummary(
            browser_jobs_seen=self.browser_jobs_seen + other.browser_jobs_seen,
            browser_jobs_succeeded=self.browser_jobs_succeeded + other.browser_jobs_succeeded,
            browser_jobs_retry_scheduled=self.browser_jobs_retry_scheduled
            + other.browser_jobs_retry_scheduled,
            browser_jobs_failed=self.browser_jobs_failed + other.browser_jobs_failed,
            browser_jobs_recovered_stale=self.browser_jobs_recovered_stale
            + other.browser_jobs_recovered_stale,
            source_health_events_recorded=self.source_health_events_recorded
            + other.source_health_events_recorded,
            watch_due_seen=self.watch_due_seen + other.watch_due_seen,
            watch_jobs_enqueued=self.watch_jobs_enqueued + other.watch_jobs_enqueued,
            watch_jobs_already_queued=self.watch_jobs_already_queued
            + other.watch_jobs_already_queued,
            watch_jobs_processed=self.watch_jobs_processed + other.watch_jobs_processed,
            watch_jobs_succeeded=self.watch_jobs_succeeded + other.watch_jobs_succeeded,
            watch_jobs_retry_scheduled=self.watch_jobs_retry_scheduled
            + other.watch_jobs_retry_scheduled,
            watch_jobs_failed=self.watch_jobs_failed + other.watch_jobs_failed,
            watch_jobs_recovered_stale=self.watch_jobs_recovered_stale
            + other.watch_jobs_recovered_stale,
            watch_watches_skipped=self.watch_watches_skipped + other.watch_watches_skipped,
            watch_provider_calls=self.watch_provider_calls + other.watch_provider_calls,
            watch_provider_failures=self.watch_provider_failures + other.watch_provider_failures,
            watch_snapshots_saved=self.watch_snapshots_saved + other.watch_snapshots_saved,
            watch_alerts_recorded=self.watch_alerts_recorded + other.watch_alerts_recorded,
            watch_telegram_notifications_enqueued=(
                self.watch_telegram_notifications_enqueued
                + other.watch_telegram_notifications_enqueued
            ),
            deal_jobs_processed=self.deal_jobs_processed + other.deal_jobs_processed,
            deal_jobs_succeeded=self.deal_jobs_succeeded + other.deal_jobs_succeeded,
            deal_jobs_retry_scheduled=self.deal_jobs_retry_scheduled
            + other.deal_jobs_retry_scheduled,
            deal_jobs_failed=self.deal_jobs_failed + other.deal_jobs_failed,
            deal_jobs_recovered_stale=self.deal_jobs_recovered_stale
            + other.deal_jobs_recovered_stale,
            deal_candidates_saved=self.deal_candidates_saved + other.deal_candidates_saved,
            telegram_notifications_seen=self.telegram_notifications_seen
            + other.telegram_notifications_seen,
            telegram_notifications_sent=self.telegram_notifications_sent
            + other.telegram_notifications_sent,
            telegram_notifications_retry_scheduled=(
                self.telegram_notifications_retry_scheduled
                + other.telegram_notifications_retry_scheduled
            ),
            telegram_notifications_failed=self.telegram_notifications_failed
            + other.telegram_notifications_failed,
            telegram_notifications_deferred_quiet_hours=(
                self.telegram_notifications_deferred_quiet_hours
                + other.telegram_notifications_deferred_quiet_hours
            ),
            telegram_notifications_recovered_stale=(
                self.telegram_notifications_recovered_stale
                + other.telegram_notifications_recovered_stale
            ),
            live_cleanup_grants_deleted=self.live_cleanup_grants_deleted
            + other.live_cleanup_grants_deleted,
            live_cleanup_observations_deleted=self.live_cleanup_observations_deleted
            + other.live_cleanup_observations_deleted,
            live_cleanup_offers_deleted=self.live_cleanup_offers_deleted
            + other.live_cleanup_offers_deleted,
            live_cleanup_idempotency_deleted=self.live_cleanup_idempotency_deleted
            + other.live_cleanup_idempotency_deleted,
            deal_candidates_deleted=self.deal_candidates_deleted + other.deal_candidates_deleted,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "browser_jobs_seen": self.browser_jobs_seen,
            "browser_jobs_succeeded": self.browser_jobs_succeeded,
            "browser_jobs_retry_scheduled": self.browser_jobs_retry_scheduled,
            "browser_jobs_failed": self.browser_jobs_failed,
            "browser_jobs_recovered_stale": self.browser_jobs_recovered_stale,
            "source_health_events_recorded": self.source_health_events_recorded,
            "watch_due_seen": self.watch_due_seen,
            "watch_jobs_enqueued": self.watch_jobs_enqueued,
            "watch_jobs_already_queued": self.watch_jobs_already_queued,
            "watch_jobs_processed": self.watch_jobs_processed,
            "watch_jobs_succeeded": self.watch_jobs_succeeded,
            "watch_jobs_retry_scheduled": self.watch_jobs_retry_scheduled,
            "watch_jobs_failed": self.watch_jobs_failed,
            "watch_jobs_recovered_stale": self.watch_jobs_recovered_stale,
            "watch_watches_skipped": self.watch_watches_skipped,
            "watch_provider_calls": self.watch_provider_calls,
            "watch_provider_failures": self.watch_provider_failures,
            "watch_snapshots_saved": self.watch_snapshots_saved,
            "watch_alerts_recorded": self.watch_alerts_recorded,
            "watch_telegram_notifications_enqueued": self.watch_telegram_notifications_enqueued,
            "deal_jobs_processed": self.deal_jobs_processed,
            "deal_jobs_succeeded": self.deal_jobs_succeeded,
            "deal_jobs_retry_scheduled": self.deal_jobs_retry_scheduled,
            "deal_jobs_failed": self.deal_jobs_failed,
            "deal_jobs_recovered_stale": self.deal_jobs_recovered_stale,
            "deal_candidates_saved": self.deal_candidates_saved,
            "telegram_notifications_seen": self.telegram_notifications_seen,
            "telegram_notifications_sent": self.telegram_notifications_sent,
            "telegram_notifications_retry_scheduled": self.telegram_notifications_retry_scheduled,
            "telegram_notifications_failed": self.telegram_notifications_failed,
            "telegram_notifications_deferred_quiet_hours": (
                self.telegram_notifications_deferred_quiet_hours
            ),
            "telegram_notifications_recovered_stale": self.telegram_notifications_recovered_stale,
            "live_cleanup_grants_deleted": self.live_cleanup_grants_deleted,
            "live_cleanup_observations_deleted": self.live_cleanup_observations_deleted,
            "live_cleanup_offers_deleted": self.live_cleanup_offers_deleted,
            "live_cleanup_idempotency_deleted": self.live_cleanup_idempotency_deleted,
            "deal_candidates_deleted": self.deal_candidates_deleted,
        }


def main() -> None:
    parser = argparse.ArgumentParser(prog="flight-hunter-worker")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--fixture-html", type=Path, default=None)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--idle-sleep-seconds", type=float, default=5.0)
    parser.add_argument("--stop-after-iterations", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=60.0)
    parser.add_argument("--stale-lock-seconds", type=float, default=900.0)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--role",
        action="append",
        choices=sorted(_WORKER_ROLE_VALUES),
        default=None,
        help="Worker lane to enable; repeat for multiple lanes. Defaults to all lanes.",
    )
    parser.add_argument(
        "--roles",
        default=None,
        help="Comma-separated worker lanes: browser,watch,deal,telegram,maintenance",
    )
    parser.add_argument("--skip-live-cleanup", action="store_true")
    parser.add_argument("--skip-watch-scans", action="store_true")
    args = parser.parse_args()
    try:
        worker_roles = _cli_worker_roles(args.role, args.roles)
    except ValueError as exc:
        parser.error(str(exc))
    worker_id = args.worker_id or _default_worker_id(worker_roles)

    load_env_file()
    settings = AppSettings.from_env()
    database_url = args.database_url or settings.database_url
    if args.loop:
        summary = asyncio.run(
            _run_loop_from_cli(
                database_url=database_url,
                settings=settings,
                limit=args.limit,
                fixture_html_path=args.fixture_html,
                idle_sleep_seconds=args.idle_sleep_seconds,
                stop_after_iterations=args.stop_after_iterations,
                max_attempts=args.max_attempts,
                retry_delay_seconds=args.retry_delay_seconds,
                stale_lock_seconds=args.stale_lock_seconds,
                worker_id=worker_id,
                worker_roles=worker_roles,
                cleanup_expired_live_observations=not args.skip_live_cleanup,
                process_watch_scans=not args.skip_watch_scans,
            )
        )
    else:
        summary = asyncio.run(
            run_once(
                database_url=database_url,
                settings=settings,
                limit=args.limit,
                fixture_html_path=args.fixture_html,
                max_attempts=args.max_attempts,
                retry_delay_seconds=args.retry_delay_seconds,
                stale_lock_seconds=args.stale_lock_seconds,
                worker_id=worker_id,
                worker_roles=worker_roles,
                cleanup_expired_live_observations=not args.skip_live_cleanup,
                process_watch_scans=not args.skip_watch_scans,
            )
        )
    print(json.dumps(summary.to_dict(), ensure_ascii=False))


async def run_once(
    *,
    database_url: str,
    settings: AppSettings,
    limit: int = 5,
    fixture_html_path: Path | None = None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 60.0,
    stale_lock_seconds: float = 900.0,
    worker_id: str = "flight-hunter-worker",
    worker_roles: tuple[str, ...] = DEFAULT_WORKER_ROLES,
    worker_started_at: datetime | None = None,
    heartbeat_final_status: str = "stopped",
    cleanup_expired_live_observations: bool = True,
    process_watch_scans: bool = True,
) -> WorkerRunSummary:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    roles = _effective_worker_roles(
        worker_roles,
        process_watch_scans=process_watch_scans,
        cleanup_expired_live_observations=cleanup_expired_live_observations,
    )
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        heartbeat_repository = WorkerHeartbeatRepository(session)
        started_at = worker_started_at or datetime.now(UTC)
        heartbeat_role = _worker_heartbeat_role(roles)
        await _record_worker_heartbeat(
            heartbeat_repository,
            worker_id=worker_id,
            role=heartbeat_role,
            status="running",
            current_phase="claiming",
            started_at=started_at,
            seen_at=datetime.now(UTC),
        )
        await session.commit()
        worker_control = await WorkerControlRepository(session).get_state()
        worker_drained = worker_control.drain_requested
        jobs = BrowserObservationJobRepository(session)
        live_observations = LiveObservationRepository(session)
        source_health_events = SourceHealthEventRepository(session)
        outbox = TelegramNotificationOutboxRepository(session)
        now = datetime.now(UTC)
        stale_before = now - timedelta(seconds=stale_lock_seconds)
        browser_recovered_stale = 0
        claimed: tuple[BrowserObservationJobRecord, ...] = ()
        service: PersonalObservationService | None = None
        if "browser" in roles and not worker_drained:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="browser_claiming",
                current_job_kind="browser_observation",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            browser_recovery = await jobs.recover_stale_running(
                now=now,
                stale_before=stale_before,
                limit=limit,
            )
            browser_recovered_stale = browser_recovery.requeued + browser_recovery.failed
            claimed = await jobs.claim_queued(
                now=now,
                limit=limit,
                worker_id=worker_id,
                max_concurrent=settings.personal_observer_max_concurrent,
                min_gap_seconds=settings.personal_observer_min_gap_seconds,
            )
            service = PersonalObservationService(
                jobs=jobs,
                grants=live_observations,
                observed_offers=BrowserObservedOfferRepository(session),
                runner=PersonalObserverRunnerAdapter(
                    PersonalObserverRunner(
                        config=PersonalObserverConfig.from_settings(settings),
                        crawl4ai_markdown_provider=(
                            crawl4ai_browser_markdown_provider_from_settings(settings)
                        ),
                    )
                ),
                observer_enabled=settings.personal_observer_enabled,
                result_ttl=timedelta(seconds=settings.personal_observer_result_ttl_seconds),
                max_attempts=max_attempts,
                retry_delay=timedelta(seconds=retry_delay_seconds),
                runtime_status_committer=session.commit,
            )
        succeeded = 0
        retry_scheduled = 0
        failed = 0
        health_events_recorded = 0
        for job in claimed:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="browser_observation",
                current_job_kind="browser_observation",
                current_job_id=str(job.id),
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            if service is None:
                continue
            decision = await service.run_claimed_job(
                job,
                fixture_html_path=fixture_html_path,
            )
            if decision.accepted:
                succeeded += 1
            elif decision.retry_scheduled:
                retry_scheduled += 1
            else:
                failed += 1
            await _record_browser_job_health(
                source_health_events,
                job=job,
                decision=decision,
                observed_at=datetime.now(UTC),
            )
            health_events_recorded += 1
        telegram_service = TelegramNotificationService(
            links=TelegramLinkRepository(session),
            outbox=outbox,
            transport=_telegram_transport(settings),
        )
        telegram_recovered_stale = 0
        if "telegram" in roles and not worker_drained:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="telegram_claiming",
                current_job_kind="telegram_notification",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            telegram_recovered_stale = await outbox.recover_stale_sending(
                now=datetime.now(UTC),
                stale_before=stale_before,
                limit=limit,
            )
        watch_summary = WatchScanRunSummary()
        watch_recovered_stale = 0
        if "watch" in roles and settings.watch_scan_enabled and not worker_drained:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="watch_scans",
                current_job_kind="watch_scan",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            watch_jobs = WatchScanJobRepository(session)
            watch_recovery = await watch_jobs.recover_stale_running(
                now=datetime.now(UTC),
                stale_before=stale_before,
                limit=limit,
            )
            watch_recovered_stale = watch_recovery.requeued + watch_recovery.failed
            watch_service = WatchScanService(
                watches=HouseholdWatchRepository(session),
                jobs=watch_jobs,
                snapshots=PriceSnapshotRepository(session),
                alert_dedupe=AlertDedupeRepository(session),
                source_health_events=source_health_events,
                providers=_watch_scan_providers(settings),
                alert_evaluator=AlertEvaluator(
                    drop_threshold_percent=settings.watch_alert_drop_threshold_percent,
                    cooldown=timedelta(seconds=settings.watch_alert_cooldown_seconds),
                ),
                telegram_outbox=telegram_service,
            )
            watch_summary = await watch_service.enqueue_due_watches(
                limit=limit,
                max_attempts=max_attempts,
                job_deadline=timedelta(seconds=settings.watch_scan_job_deadline_seconds),
            )
            claimed_watch_jobs = await watch_jobs.claim_queued(
                now=datetime.now(UTC),
                limit=limit,
                worker_id=worker_id,
            )
            watch_summary = watch_summary.merge(
                WatchScanRunSummary(jobs_processed=len(claimed_watch_jobs))
            )
            for watch_job in claimed_watch_jobs:
                await _record_worker_heartbeat(
                    heartbeat_repository,
                    worker_id=worker_id,
                    role=heartbeat_role,
                    status="running",
                    current_phase="watch_scan",
                    current_job_kind="watch_scan",
                    current_job_id=str(watch_job.id),
                    started_at=started_at,
                    seen_at=datetime.now(UTC),
                )
                await session.commit()
                watch_summary = watch_summary.merge(
                    await watch_service.run_job(
                        watch_job,
                        retry_delay=timedelta(seconds=retry_delay_seconds),
                        worker_id=worker_id,
                    )
                )
        deal_jobs = DealDiscoveryJobRepository(session)
        deal_recovered_stale = 0
        deal_summary = DealDiscoveryJobRunSummary()
        if "deal" in roles and not worker_drained:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="deal_discovery",
                current_job_kind="deal_discovery_job",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            deal_recovery = await deal_jobs.recover_stale_running(
                now=datetime.now(UTC),
                stale_before=stale_before,
                limit=limit,
            )
            deal_recovered_stale = deal_recovery.requeued + deal_recovery.failed
            deal_service = DealDiscoveryJobService(
                jobs=deal_jobs,
                candidates=DealCandidateRepository(session),
                source_health_events=source_health_events,
                discovery=_deal_discovery_service(settings),
                candidate_ttl=timedelta(seconds=max(1, settings.deal_candidate_ttl_seconds)),
            )
            claimed_deal_jobs = await deal_jobs.claim_queued(
                now=datetime.now(UTC),
                limit=limit,
                worker_id=worker_id,
            )
            deal_summary = DealDiscoveryJobRunSummary(jobs_processed=len(claimed_deal_jobs))
            for deal_job in claimed_deal_jobs:
                await _record_worker_heartbeat(
                    heartbeat_repository,
                    worker_id=worker_id,
                    role=heartbeat_role,
                    status="running",
                    current_phase="deal_discovery_job",
                    current_job_kind="deal_discovery_job",
                    current_job_id=str(deal_job.id),
                    started_at=started_at,
                    seen_at=datetime.now(UTC),
                )
                await session.commit()
                deal_summary = deal_summary.merge(
                    await deal_service.run_job(
                        deal_job,
                        retry_delay=timedelta(seconds=retry_delay_seconds),
                    )
                )
        telegram_summary = TelegramDeliverySummary()
        if "telegram" in roles and not worker_drained:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="telegram_delivery",
                current_job_kind="telegram_notification",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
            due_notifications = await outbox.claim_due(
                now=datetime.now(UTC),
                limit=limit,
                worker_id=worker_id,
            )
            telegram_summary = TelegramDeliverySummary(notifications_seen=len(due_notifications))
            for notification in due_notifications:
                await _record_worker_heartbeat(
                    heartbeat_repository,
                    worker_id=worker_id,
                    role=heartbeat_role,
                    status="running",
                    current_phase="telegram_notification",
                    current_job_kind="telegram_notification",
                    current_job_id=str(notification.id),
                    started_at=started_at,
                    seen_at=datetime.now(UTC),
                )
                await session.commit()
                result = await telegram_service.deliver_claimed(
                    notification,
                    max_attempts=max_attempts,
                    retry_delay=timedelta(seconds=retry_delay_seconds),
                    quiet_hours=_telegram_quiet_hours(settings),
                )
                telegram_summary = TelegramDeliverySummary(
                    notifications_seen=telegram_summary.notifications_seen,
                    sent=telegram_summary.sent + result.sent,
                    retry_scheduled=telegram_summary.retry_scheduled + result.retry_scheduled,
                    failed=telegram_summary.failed + result.failed,
                    deferred_quiet_hours=(
                        telegram_summary.deferred_quiet_hours + result.deferred_quiet_hours
                    ),
                )
        if "maintenance" in roles:
            await _record_worker_heartbeat(
                heartbeat_repository,
                worker_id=worker_id,
                role=heartbeat_role,
                status="running",
                current_phase="maintenance",
                current_job_kind="cleanup",
                started_at=started_at,
                seen_at=datetime.now(UTC),
            )
            await session.commit()
        cleanup_result = (
            await live_observations.cleanup_expired_live_observation_state(
                now=datetime.now(UTC),
            )
            if "maintenance" in roles
            else None
        )
        deal_candidates_deleted = (
            await DealCandidateRepository(session).cleanup_expired(now=datetime.now(UTC))
            if "maintenance" in roles
            else 0
        )
        summary = WorkerRunSummary(
            browser_jobs_seen=len(claimed),
            browser_jobs_succeeded=succeeded,
            browser_jobs_retry_scheduled=retry_scheduled,
            browser_jobs_failed=failed,
            browser_jobs_recovered_stale=browser_recovered_stale,
            source_health_events_recorded=(
                health_events_recorded
                + watch_summary.health_events_recorded
                + deal_summary.health_events_recorded
            ),
            watch_due_seen=watch_summary.due_watches_seen,
            watch_jobs_enqueued=watch_summary.jobs_enqueued,
            watch_jobs_already_queued=watch_summary.jobs_already_queued,
            watch_jobs_processed=watch_summary.jobs_processed,
            watch_jobs_succeeded=watch_summary.jobs_succeeded,
            watch_jobs_retry_scheduled=watch_summary.jobs_retry_scheduled,
            watch_jobs_failed=watch_summary.jobs_failed,
            watch_jobs_recovered_stale=watch_recovered_stale,
            watch_watches_skipped=watch_summary.watches_skipped,
            watch_provider_calls=watch_summary.provider_calls,
            watch_provider_failures=watch_summary.provider_failures,
            watch_snapshots_saved=watch_summary.snapshots_saved,
            watch_alerts_recorded=watch_summary.alerts_recorded,
            watch_telegram_notifications_enqueued=watch_summary.telegram_notifications_enqueued,
            deal_jobs_processed=deal_summary.jobs_processed,
            deal_jobs_succeeded=deal_summary.jobs_succeeded,
            deal_jobs_retry_scheduled=deal_summary.jobs_retry_scheduled,
            deal_jobs_failed=deal_summary.jobs_failed,
            deal_jobs_recovered_stale=deal_recovered_stale,
            deal_candidates_saved=deal_summary.candidates_saved,
            telegram_notifications_seen=telegram_summary.notifications_seen,
            telegram_notifications_sent=telegram_summary.sent,
            telegram_notifications_retry_scheduled=telegram_summary.retry_scheduled,
            telegram_notifications_failed=telegram_summary.failed,
            telegram_notifications_deferred_quiet_hours=telegram_summary.deferred_quiet_hours,
            telegram_notifications_recovered_stale=telegram_recovered_stale,
            live_cleanup_grants_deleted=(
                cleanup_result.grants_deleted if cleanup_result is not None else 0
            ),
            live_cleanup_observations_deleted=(
                cleanup_result.observations_deleted if cleanup_result is not None else 0
            ),
            live_cleanup_offers_deleted=(
                cleanup_result.offers_deleted if cleanup_result is not None else 0
            ),
            live_cleanup_idempotency_deleted=(
                cleanup_result.idempotency_deleted if cleanup_result is not None else 0
            ),
            deal_candidates_deleted=deal_candidates_deleted,
        )
        await _record_worker_heartbeat(
            heartbeat_repository,
            worker_id=worker_id,
            role=heartbeat_role,
            status=heartbeat_final_status,
            current_phase="idle" if heartbeat_final_status == "idle" else "stopped",
            started_at=started_at,
            seen_at=datetime.now(UTC),
            summary=summary,
        )
        await session.commit()
    await engine.dispose()
    return summary


async def run_loop(
    *,
    database_url: str,
    settings: AppSettings,
    limit: int = 5,
    fixture_html_path: Path | None = None,
    idle_sleep_seconds: float = 5.0,
    stop_after_iterations: int | None = None,
    max_attempts: int = 3,
    retry_delay_seconds: float = 60.0,
    stale_lock_seconds: float = 900.0,
    worker_id: str = "flight-hunter-worker",
    worker_roles: tuple[str, ...] = DEFAULT_WORKER_ROLES,
    cleanup_expired_live_observations: bool = True,
    process_watch_scans: bool = True,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop_requested: Callable[[], bool] | None = None,
) -> WorkerRunSummary:
    iterations = 0
    total = _empty_worker_summary()
    should_stop = stop_requested or (lambda: False)
    worker_started_at = datetime.now(UTC)
    while True:
        if should_stop():
            return total
        summary = await run_once(
            database_url=database_url,
            settings=settings,
            limit=limit,
            fixture_html_path=fixture_html_path,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            stale_lock_seconds=stale_lock_seconds,
            worker_id=worker_id,
            worker_roles=worker_roles,
            worker_started_at=worker_started_at,
            heartbeat_final_status="idle",
            cleanup_expired_live_observations=cleanup_expired_live_observations,
            process_watch_scans=process_watch_scans,
        )
        total = total.merge(summary)
        iterations += 1
        if (
            stop_after_iterations is not None and iterations >= stop_after_iterations
        ) or should_stop():
            return total
        if (
            summary.browser_jobs_seen == 0
            and summary.browser_jobs_recovered_stale == 0
            and summary.watch_jobs_processed == 0
            and summary.watch_jobs_recovered_stale == 0
            and summary.deal_jobs_processed == 0
            and summary.deal_jobs_recovered_stale == 0
            and summary.telegram_notifications_seen == 0
            and summary.telegram_notifications_recovered_stale == 0
        ):
            await sleep(idle_sleep_seconds)


async def _run_loop_from_cli(
    *,
    database_url: str,
    settings: AppSettings,
    limit: int,
    fixture_html_path: Path | None,
    idle_sleep_seconds: float,
    stop_after_iterations: int | None,
    max_attempts: int,
    retry_delay_seconds: float,
    stale_lock_seconds: float,
    worker_id: str,
    worker_roles: tuple[str, ...],
    cleanup_expired_live_observations: bool,
    process_watch_scans: bool,
) -> WorkerRunSummary:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    summary = await run_loop(
        database_url=database_url,
        settings=settings,
        limit=limit,
        fixture_html_path=fixture_html_path,
        idle_sleep_seconds=idle_sleep_seconds,
        stop_after_iterations=stop_after_iterations,
        max_attempts=max_attempts,
        retry_delay_seconds=retry_delay_seconds,
        stale_lock_seconds=stale_lock_seconds,
        worker_id=worker_id,
        worker_roles=worker_roles,
        cleanup_expired_live_observations=cleanup_expired_live_observations,
        process_watch_scans=process_watch_scans,
        sleep=lambda seconds: _sleep_or_stop(stop_event, seconds),
        stop_requested=stop_event.is_set,
    )
    await _record_worker_stopped(
        database_url=database_url,
        worker_id=worker_id,
        role=_worker_heartbeat_role(
            _effective_worker_roles(
                worker_roles,
                process_watch_scans=process_watch_scans,
                cleanup_expired_live_observations=cleanup_expired_live_observations,
            )
        ),
        summary=summary,
    )
    return summary


async def _sleep_or_stop(stop_event: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        loop.call_soon_threadsafe(stop_event.set)

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_number, stop_event.set)
        except RuntimeError:
            signal.signal(signal_number, lambda _signum, _frame: request_stop())


def _cli_worker_roles(
    repeated_roles: list[str] | None,
    comma_roles: str | None,
) -> tuple[str, ...]:
    if repeated_roles:
        return tuple(dict.fromkeys(repeated_roles))
    if comma_roles is not None:
        return _parse_worker_roles(comma_roles)
    return DEFAULT_WORKER_ROLES


def _parse_worker_roles(raw: str) -> tuple[str, ...]:
    roles = tuple(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))
    unknown = tuple(role for role in roles if role not in _WORKER_ROLE_VALUES)
    if unknown:
        allowed = ", ".join(sorted(_WORKER_ROLE_VALUES))
        raise ValueError(f"unknown worker role(s): {', '.join(unknown)}; allowed: {allowed}")
    if not roles:
        raise ValueError("at least one worker role is required")
    return roles


def _effective_worker_roles(
    roles: tuple[str, ...],
    *,
    process_watch_scans: bool,
    cleanup_expired_live_observations: bool,
) -> tuple[str, ...]:
    effective = roles
    if not process_watch_scans:
        effective = tuple(role for role in effective if role != "watch")
    if not cleanup_expired_live_observations:
        effective = tuple(role for role in effective if role != "maintenance")
    return effective


def _default_worker_id(roles: tuple[str, ...]) -> str:
    if roles == DEFAULT_WORKER_ROLES:
        return "flight-hunter-worker"
    if len(roles) == 1:
        return f"flight-hunter-{roles[0]}-worker"
    return "flight-hunter-multi-worker"


def _worker_heartbeat_role(roles: tuple[str, ...]) -> str:
    if roles == DEFAULT_WORKER_ROLES:
        return "flight_hunter_worker"
    if len(roles) == 1:
        return roles[0]
    return "multi"


def _empty_worker_summary() -> WorkerRunSummary:
    return WorkerRunSummary(
        browser_jobs_seen=0,
        browser_jobs_succeeded=0,
        browser_jobs_retry_scheduled=0,
        browser_jobs_failed=0,
        browser_jobs_recovered_stale=0,
        source_health_events_recorded=0,
        watch_due_seen=0,
        watch_jobs_enqueued=0,
        watch_jobs_already_queued=0,
        watch_jobs_processed=0,
        watch_jobs_succeeded=0,
        watch_jobs_retry_scheduled=0,
        watch_jobs_failed=0,
        watch_jobs_recovered_stale=0,
        watch_watches_skipped=0,
        watch_provider_calls=0,
        watch_provider_failures=0,
        watch_snapshots_saved=0,
        watch_alerts_recorded=0,
        watch_telegram_notifications_enqueued=0,
        deal_jobs_processed=0,
        deal_jobs_succeeded=0,
        deal_jobs_retry_scheduled=0,
        deal_jobs_failed=0,
        deal_jobs_recovered_stale=0,
        deal_candidates_saved=0,
        telegram_notifications_seen=0,
        telegram_notifications_sent=0,
        telegram_notifications_retry_scheduled=0,
        telegram_notifications_failed=0,
        telegram_notifications_deferred_quiet_hours=0,
        telegram_notifications_recovered_stale=0,
        live_cleanup_grants_deleted=0,
        live_cleanup_observations_deleted=0,
        live_cleanup_offers_deleted=0,
        live_cleanup_idempotency_deleted=0,
        deal_candidates_deleted=0,
    )


async def _record_worker_heartbeat(
    repository: WorkerHeartbeatRepository,
    *,
    worker_id: str,
    role: str = "flight_hunter_worker",
    status: str,
    current_phase: str,
    started_at: datetime,
    seen_at: datetime,
    current_job_kind: str | None = None,
    current_job_id: str | None = None,
    summary: WorkerRunSummary | None = None,
) -> None:
    await repository.upsert(
        NewWorkerHeartbeat(
            worker_id=worker_id,
            role=role,
            status=status,
            current_phase=current_phase,
            current_job_kind=current_job_kind,
            current_job_id=current_job_id,
            started_at=started_at,
            last_seen_at=seen_at,
            stopped_at=seen_at if status == "stopped" else None,
            stopping_at=seen_at if status == "stopping" else None,
            last_summary_json=json.dumps(
                summary.to_dict() if summary is not None else {},
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    )


async def _record_worker_stopped(
    *,
    database_url: str,
    worker_id: str,
    role: str = "flight_hunter_worker",
    summary: WorkerRunSummary,
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        repository = WorkerHeartbeatRepository(session)
        existing = await repository.list_recent(limit=100)
        started_at = next(
            (heartbeat.started_at for heartbeat in existing if heartbeat.worker_id == worker_id),
            datetime.now(UTC),
        )
        await _record_worker_heartbeat(
            repository,
            worker_id=worker_id,
            role=role,
            status="stopped",
            current_phase="stopped",
            started_at=started_at,
            seen_at=datetime.now(UTC),
            summary=summary,
        )
        await session.commit()
    await engine.dispose()


async def _record_browser_job_health(
    repository: SourceHealthEventRepository,
    *,
    job: BrowserObservationJobRecord,
    decision: PersonalObservationRunDecision,
    observed_at: datetime,
) -> None:
    status = _health_status(decision)
    await repository.add_event(
        NewSourceHealthEvent(
            id=uuid4(),
            source_id=job.source_id,
            event_type="browser_observation",
            status=status,
            message=_health_message(decision, status=status),
            observed_at=observed_at,
            cooldown_until=(
                decision.job.next_retry_at
                if decision.retry_scheduled and decision.job is not None
                else None
            ),
        )
    )


def _health_status(decision: PersonalObservationRunDecision) -> str:
    if decision.accepted:
        return "ok"
    if decision.retry_scheduled:
        return "retry_scheduled"
    return "failed"


def _health_message(decision: PersonalObservationRunDecision, *, status: str) -> str:
    if decision.accepted:
        return f"browser observation succeeded; offers={decision.offers_persisted}"
    if decision.retry_scheduled:
        return f"browser observation retry scheduled; code={decision.code.value}"
    return f"browser observation failed; code={decision.code.value}"


def _watch_scan_providers(
    settings: AppSettings,
) -> dict[str, AviasalesSearchAdapter | FakeFlightProvider]:
    if settings.aviasales_search_enabled and settings.aviasales_search_credentials_present:
        return {
            "aviasales_search": AviasalesSearchAdapter(
                client=AviasalesSearchClient(
                    signature=settings.aviasales_search_signature or "",
                    marker=settings.aviasales_search_marker or "",
                ),
                enabled=settings.aviasales_search_enabled,
                credentials_present=settings.aviasales_search_credentials_present,
                internal_rpm=settings.aviasales_search_internal_rpm,
            )
        }
    return {"fake": FakeFlightProvider()}


def _deal_discovery_service(settings: AppSettings) -> DealDiscoveryService | None:
    if not settings.searxng_enabled or not settings.crawl4ai_enabled:
        return None
    return DealDiscoveryService(
        search_client=SearxngClient(
            base_url=settings.searxng_base_url,
            timeout_seconds=settings.searxng_timeout_seconds,
        ),
        markdown_client=Crawl4AiMarkdownClient(
            enabled=settings.crawl4ai_enabled,
            mode=settings.crawl4ai_mode,
            base_url=settings.crawl4ai_base_url,
            api_token=settings.crawl4ai_api_token,
            timeout_seconds=settings.crawl4ai_timeout_seconds,
        ),
    )


def _telegram_transport(settings: AppSettings) -> TelegramBotApiTransport | None:
    if not settings.telegram_enabled or settings.telegram_bot_token is None:
        return None
    return TelegramBotApiTransport(token=settings.telegram_bot_token)


def _telegram_quiet_hours(settings: AppSettings) -> TelegramQuietHours | None:
    if settings.telegram_quiet_hours_start is None or settings.telegram_quiet_hours_end is None:
        return None
    return TelegramQuietHours(
        start=_parse_hhmm(settings.telegram_quiet_hours_start),
        end=_parse_hhmm(settings.telegram_quiet_hours_end),
    )


def _parse_hhmm(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))
