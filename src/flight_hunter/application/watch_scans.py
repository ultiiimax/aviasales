from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from flight_hunter.application.watch_scheduler import (
    ProviderRuntimeState,
    SchedulerProviderRegistry,
    WatchSchedulerPlanner,
    WatchScheduleState,
)
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.policy import ExecutionContext, ProviderPolicy
from flight_hunter.notifications.alerts import AlertEvaluator, PriceAlert, PriceObservation
from flight_hunter.persistence.repositories import (
    AlertDedupeRepository,
    HouseholdWatchRepository,
    NewPriceSnapshot,
    NewSourceHealthEvent,
    NewWatchScanJob,
    PriceSnapshotRecord,
    PriceSnapshotRepository,
    SourceHealthEventRepository,
    WatchRecord,
    WatchScanJobRecord,
    WatchScanJobRepository,
)


class WatchScanJobStatus(StrEnum):
    QUEUED = "queued"
    RETRY_SCHEDULED = "retry_scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WatchScanProvider(Protocol):
    policy: ProviderPolicy

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]: ...


class PriceAlertOutbox(Protocol):
    async def enqueue_price_alert(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        alert: PriceAlert,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class WatchScanRunSummary:
    due_watches_seen: int = 0
    jobs_enqueued: int = 0
    jobs_already_queued: int = 0
    jobs_processed: int = 0
    jobs_succeeded: int = 0
    jobs_retry_scheduled: int = 0
    jobs_failed: int = 0
    watches_skipped: int = 0
    provider_calls: int = 0
    provider_failures: int = 0
    snapshots_saved: int = 0
    alerts_recorded: int = 0
    telegram_notifications_enqueued: int = 0
    health_events_recorded: int = 0

    def merge(self, other: WatchScanRunSummary) -> WatchScanRunSummary:
        return WatchScanRunSummary(
            due_watches_seen=self.due_watches_seen + other.due_watches_seen,
            jobs_enqueued=self.jobs_enqueued + other.jobs_enqueued,
            jobs_already_queued=self.jobs_already_queued + other.jobs_already_queued,
            jobs_processed=self.jobs_processed + other.jobs_processed,
            jobs_succeeded=self.jobs_succeeded + other.jobs_succeeded,
            jobs_retry_scheduled=self.jobs_retry_scheduled + other.jobs_retry_scheduled,
            jobs_failed=self.jobs_failed + other.jobs_failed,
            watches_skipped=self.watches_skipped + other.watches_skipped,
            provider_calls=self.provider_calls + other.provider_calls,
            provider_failures=self.provider_failures + other.provider_failures,
            snapshots_saved=self.snapshots_saved + other.snapshots_saved,
            alerts_recorded=self.alerts_recorded + other.alerts_recorded,
            telegram_notifications_enqueued=self.telegram_notifications_enqueued
            + other.telegram_notifications_enqueued,
            health_events_recorded=self.health_events_recorded + other.health_events_recorded,
        )


@dataclass(frozen=True, slots=True)
class _ProviderRunResult:
    provider_calls: int
    provider_failures: int
    snapshots_saved: int
    alerts_recorded: int
    telegram_notifications_enqueued: int
    health_events_recorded: int
    error_code: str | None
    error_message: str | None


class WatchScanService:
    def __init__(
        self,
        *,
        watches: HouseholdWatchRepository,
        jobs: WatchScanJobRepository,
        snapshots: PriceSnapshotRepository,
        alert_dedupe: AlertDedupeRepository,
        source_health_events: SourceHealthEventRepository,
        providers: Mapping[str, WatchScanProvider],
        alert_evaluator: AlertEvaluator,
        telegram_outbox: PriceAlertOutbox | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._watches = watches
        self._jobs = jobs
        self._snapshots = snapshots
        self._alert_dedupe = alert_dedupe
        self._source_health_events = source_health_events
        self._providers = dict(providers)
        self._alert_evaluator = alert_evaluator
        self._telegram_outbox = telegram_outbox
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory
        self._planner = WatchSchedulerPlanner(clock=self._clock)

    async def run_once(
        self,
        *,
        due_limit: int,
        job_limit: int,
        max_attempts: int,
        retry_delay: timedelta,
        job_deadline: timedelta,
        worker_id: str,
    ) -> WatchScanRunSummary:
        enqueue_summary = await self.enqueue_due_watches(
            limit=due_limit,
            max_attempts=max_attempts,
            job_deadline=job_deadline,
        )
        run_summary = await self.run_queued_jobs(
            limit=job_limit,
            retry_delay=retry_delay,
            worker_id=worker_id,
        )
        return enqueue_summary.merge(run_summary)

    async def enqueue_due_watches(
        self,
        *,
        limit: int,
        max_attempts: int,
        job_deadline: timedelta,
    ) -> WatchScanRunSummary:
        now = self._clock()
        due_watches = await self._watches.list_due_watches(now=now, limit=limit)
        runtime_providers, registration_denials = self._scheduler_providers()
        jobs_enqueued = 0
        jobs_already_queued = 0
        watches_skipped = 0
        health_events_recorded = 0

        for watch in due_watches:
            decision = self._planner.decide(
                _schedule_state(watch),
                providers=runtime_providers,
            )
            provider_denials = {**registration_denials, **decision.provider_denials}
            if not decision.eligible:
                watches_skipped += 1
                error_code = _skip_code(decision.blocked_reasons, provider_denials)
                await self._record_watch_result(
                    watch,
                    status="skipped",
                    error_code=error_code,
                    scanned_at=now,
                )
                await self._record_health_event(
                    source_id=f"watch:{watch.id}",
                    status="skipped",
                    message=f"watch scan skipped; code={error_code}",
                    observed_at=now,
                )
                health_events_recorded += 1
                continue

            created = await self._jobs.enqueue_job(
                NewWatchScanJob(
                    id=self._id_factory(),
                    household_id=watch.household_id,
                    watch_id=watch.id,
                    idempotency_key=_scan_idempotency_key(watch),
                    status=WatchScanJobStatus.QUEUED.value,
                    attempts=0,
                    max_attempts=max_attempts,
                    deadline_at=now + job_deadline,
                    created_at=now,
                    provider_ids=decision.provider_ids,
                    provider_denials=provider_denials,
                )
            )
            if created:
                jobs_enqueued += 1
            else:
                jobs_already_queued += 1

        return WatchScanRunSummary(
            due_watches_seen=len(due_watches),
            jobs_enqueued=jobs_enqueued,
            jobs_already_queued=jobs_already_queued,
            watches_skipped=watches_skipped,
            health_events_recorded=health_events_recorded,
        )

    async def run_queued_jobs(
        self,
        *,
        limit: int,
        retry_delay: timedelta,
        worker_id: str,
    ) -> WatchScanRunSummary:
        now = self._clock()
        claimed_jobs = await self._jobs.claim_queued(
            now=now,
            limit=limit,
            worker_id=worker_id,
        )
        summary = WatchScanRunSummary(jobs_processed=len(claimed_jobs))
        for job in claimed_jobs:
            summary = summary.merge(
                await self.run_job(
                    job,
                    retry_delay=retry_delay,
                    worker_id=worker_id,
                )
            )
        return summary

    async def run_job(
        self,
        job: WatchScanJobRecord,
        *,
        retry_delay: timedelta,
        worker_id: str,
    ) -> WatchScanRunSummary:
        started_at = self._clock()
        running_job = job
        if job.status != WatchScanJobStatus.RUNNING.value:
            await self._jobs.mark_running(
                job_id=job.id,
                worker_id=worker_id,
                started_at=started_at,
            )
            refreshed_job = await self._jobs.get_job(job.id)
            if refreshed_job is None:
                return WatchScanRunSummary(jobs_failed=1)
            running_job = refreshed_job
        if running_job is None:
            return WatchScanRunSummary(jobs_failed=1)
        if running_job.deadline_at <= started_at:
            await self._jobs.mark_failed(
                job_id=running_job.id,
                completed_at=started_at,
                error_code="deadline_exceeded",
                error_message="watch scan job deadline elapsed before execution",
            )
            return WatchScanRunSummary(jobs_failed=1)

        watch = await self._watches.get_watch(running_job.household_id, running_job.watch_id)
        if watch is None or not watch.enabled:
            await self._jobs.mark_failed(
                job_id=running_job.id,
                completed_at=started_at,
                error_code="watch_unavailable",
                error_message="watch is missing or disabled",
            )
            return WatchScanRunSummary(jobs_failed=1)

        intent = _intent_from_watch(watch)
        provider_result = await self._run_providers(
            running_job,
            watch=watch,
            intent=intent,
        )
        finished_at = self._clock()

        if provider_result.error_code is None:
            status = "succeeded" if provider_result.snapshots_saved > 0 else "empty"
            await self._jobs.mark_succeeded(job_id=running_job.id, completed_at=finished_at)
            await self._record_watch_result(
                watch,
                status=status,
                error_code=None,
                scanned_at=finished_at,
            )
            return WatchScanRunSummary(
                jobs_succeeded=1,
                provider_calls=provider_result.provider_calls,
                provider_failures=provider_result.provider_failures,
                snapshots_saved=provider_result.snapshots_saved,
                alerts_recorded=provider_result.alerts_recorded,
                telegram_notifications_enqueued=(provider_result.telegram_notifications_enqueued),
                health_events_recorded=provider_result.health_events_recorded,
            )

        if running_job.attempts < running_job.max_attempts:
            await self._jobs.mark_retry_scheduled(
                job_id=running_job.id,
                retry_at=finished_at + retry_delay,
                error_code=provider_result.error_code,
                error_message=provider_result.error_message or "watch scan provider failed",
            )
            return WatchScanRunSummary(
                jobs_retry_scheduled=1,
                provider_calls=provider_result.provider_calls,
                provider_failures=provider_result.provider_failures,
                snapshots_saved=provider_result.snapshots_saved,
                alerts_recorded=provider_result.alerts_recorded,
                telegram_notifications_enqueued=(provider_result.telegram_notifications_enqueued),
                health_events_recorded=provider_result.health_events_recorded,
            )

        await self._jobs.mark_failed(
            job_id=running_job.id,
            completed_at=finished_at,
            error_code=provider_result.error_code,
            error_message=provider_result.error_message or "watch scan provider failed",
        )
        await self._record_watch_result(
            watch,
            status="failed",
            error_code=provider_result.error_code,
            scanned_at=finished_at,
        )
        return WatchScanRunSummary(
            jobs_failed=1,
            provider_calls=provider_result.provider_calls,
            provider_failures=provider_result.provider_failures,
            snapshots_saved=provider_result.snapshots_saved,
            alerts_recorded=provider_result.alerts_recorded,
            telegram_notifications_enqueued=provider_result.telegram_notifications_enqueued,
            health_events_recorded=provider_result.health_events_recorded,
        )

    def _scheduler_providers(self) -> tuple[tuple[ProviderRuntimeState, ...], dict[str, str]]:
        registry = SchedulerProviderRegistry()
        for provider in self._providers.values():
            registry.register(ProviderRuntimeState(policy=provider.policy))
        return registry.providers, registry.denials

    async def _run_providers(
        self,
        job: WatchScanJobRecord,
        *,
        watch: WatchRecord,
        intent: SearchIntent,
    ) -> _ProviderRunResult:
        provider_calls = 0
        provider_failures = 0
        snapshots_saved = 0
        alerts_recorded = 0
        telegram_notifications_enqueued = 0
        health_events_recorded = 0
        first_error_code: str | None = None
        first_error_message: str | None = None

        for provider_id in job.provider_ids:
            provider = self._providers.get(provider_id)
            if provider is None:
                provider_failures += 1
                first_error_code = first_error_code or "provider_unavailable"
                first_error_message = first_error_message or "provider is not configured"
                await self._record_health_event(
                    source_id=provider_id,
                    status="failed",
                    message="watch scan provider unavailable",
                    observed_at=self._clock(),
                )
                health_events_recorded += 1
                continue

            provider_calls += 1
            try:
                offers = provider.search(
                    intent,
                    request_fingerprint=f"watch_scan:{job.idempotency_key}:{provider_id}",
                    context=ExecutionContext.SCHEDULER,
                )
            except Exception as exc:
                provider_failures += 1
                error_code = _provider_error_code(exc)
                first_error_code = first_error_code or error_code
                first_error_message = first_error_message or _provider_error_message(exc)
                await self._record_health_event(
                    source_id=provider_id,
                    status="failed",
                    message=f"watch scan provider failed; code={error_code}",
                    observed_at=self._clock(),
                )
                health_events_recorded += 1
                continue

            saved_for_provider = 0
            provider_had_error = False
            for offer in offers:
                if not _offer_matches_watch(offer, watch):
                    provider_failures += 1
                    provider_had_error = True
                    first_error_code = first_error_code or "provider_offer_mismatch"
                    first_error_message = first_error_message or (
                        "provider returned mismatched offer"
                    )
                    continue
                saved, alert_recorded, telegram_enqueued = await self._persist_offer(
                    job, watch=watch, offer=offer
                )
                if saved:
                    saved_for_provider += 1
                    snapshots_saved += 1
                if alert_recorded:
                    alerts_recorded += 1
                if telegram_enqueued:
                    telegram_notifications_enqueued += 1

            status = "failed" if provider_had_error else "ok" if saved_for_provider > 0 else "empty"
            message = (
                f"watch scan provider completed; offers={len(offers)} saved={saved_for_provider}"
            )
            await self._record_health_event(
                source_id=provider_id,
                status=status,
                message=message,
                observed_at=self._clock(),
            )
            health_events_recorded += 1

        return _ProviderRunResult(
            provider_calls=provider_calls,
            provider_failures=provider_failures,
            snapshots_saved=snapshots_saved,
            alerts_recorded=alerts_recorded,
            telegram_notifications_enqueued=telegram_notifications_enqueued,
            health_events_recorded=health_events_recorded,
            error_code=first_error_code,
            error_message=first_error_message,
        )

    async def _persist_offer(
        self,
        job: WatchScanJobRecord,
        *,
        watch: WatchRecord,
        offer: FlightOffer,
    ) -> tuple[bool, bool, bool]:
        itinerary_fingerprint = _itinerary_fingerprint(offer)
        previous_best = await self._snapshots.get_best_before(
            household_id=watch.household_id,
            watch_id=watch.id,
            itinerary_fingerprint=itinerary_fingerprint,
            observed_at=offer.observed_at,
        )
        inserted = await self._snapshots.add_snapshot_once(
            NewPriceSnapshot(
                id=_snapshot_id(job, offer),
                household_id=watch.household_id,
                watch_id=watch.id,
                provider_id=offer.provider_id,
                itinerary_fingerprint=itinerary_fingerprint,
                observed_at=offer.observed_at,
                price=offer.total_price,
                freshness=offer.freshness,
                requires_live_confirmation=offer.requires_live_confirmation,
            )
        )
        if not inserted or previous_best is None or offer.freshness == Freshness.STALE:
            return inserted, False, False

        alert_recorded, telegram_enqueued = await self._evaluate_alert(
            household_id=watch.household_id,
            user_id=watch.owner_user_id,
            watch_id=watch.id,
            itinerary_fingerprint=itinerary_fingerprint,
            previous_best=previous_best,
            current_offer=offer,
        )
        return inserted, alert_recorded, telegram_enqueued

    async def _evaluate_alert(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        watch_id: UUID,
        itinerary_fingerprint: str,
        previous_best: PriceSnapshotRecord,
        current_offer: FlightOffer,
    ) -> tuple[bool, bool]:
        state = await self._alert_dedupe.load_state(household_id, watch_id)
        result = self._alert_evaluator.evaluate(
            previous_best=PriceObservation(
                watch_id=str(watch_id),
                itinerary_fingerprint=itinerary_fingerprint,
                observed_at=previous_best.observed_at,
                price=previous_best.price,
            ),
            current=PriceObservation(
                watch_id=str(watch_id),
                itinerary_fingerprint=itinerary_fingerprint,
                observed_at=current_offer.observed_at,
                price=current_offer.total_price,
            ),
            state=state,
        )
        if result.alert is None:
            return False, False
        alert_recorded = await self._alert_dedupe.record_alert(household_id, result.alert)
        if not alert_recorded or self._telegram_outbox is None:
            return alert_recorded, False
        telegram_enqueued = await self._telegram_outbox.enqueue_price_alert(
            household_id=household_id,
            user_id=user_id,
            alert=result.alert,
        )
        return alert_recorded, telegram_enqueued

    async def _record_watch_result(
        self,
        watch: WatchRecord,
        *,
        status: str,
        error_code: str | None,
        scanned_at: datetime,
    ) -> None:
        await self._watches.record_scan_result(
            household_id=watch.household_id,
            watch_id=watch.id,
            scanned_at=scanned_at,
            next_eligible_at=scanned_at + timedelta(seconds=watch.scan_interval_seconds),
            status=status,
            error_code=error_code,
        )

    async def _record_health_event(
        self,
        *,
        source_id: str,
        status: str,
        message: str,
        observed_at: datetime,
    ) -> None:
        await self._source_health_events.add_event(
            NewSourceHealthEvent(
                id=self._id_factory(),
                source_id=source_id,
                event_type="watch_scan",
                status=status,
                message=message,
                observed_at=observed_at,
            )
        )


def _schedule_state(watch: WatchRecord) -> WatchScheduleState:
    return WatchScheduleState(
        watch_id=watch.id,
        enabled=watch.enabled,
        paused_until=watch.paused_until,
        departure_date=date.fromisoformat(watch.departure_date),
        next_eligible_at=watch.next_eligible_at,
        cache_fresh_until=None,
        allowed_provider_ids=watch.allowed_provider_ids,
    )


def _intent_from_watch(watch: WatchRecord) -> SearchIntent:
    return SearchIntent(
        origin=watch.origin,
        destination=watch.destination,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        passengers=watch.passengers,
        currency=watch.currency,
        origin_kind=watch.origin_kind,
        destination_kind=watch.destination_kind,
        origin_airport_codes=watch.origin_airport_codes,
        destination_airport_codes=watch.destination_airport_codes,
        directory_version=watch.directory_version,
        origin_membership_version=watch.origin_membership_version,
        destination_membership_version=watch.destination_membership_version,
    )


def _scan_idempotency_key(watch: WatchRecord) -> str:
    route_facts = {
        "origin": watch.origin,
        "destination": watch.destination,
        "origin_kind": watch.origin_kind.value,
        "destination_kind": watch.destination_kind.value,
        "origin_airport_codes": list(watch.origin_airport_codes),
        "destination_airport_codes": list(watch.destination_airport_codes),
        "directory_version": watch.directory_version,
        "origin_membership_version": watch.origin_membership_version,
        "destination_membership_version": watch.destination_membership_version,
    }
    route_digest = hashlib.sha256(
        json.dumps(route_facts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"watch_scan:{watch.id}:{watch.next_eligible_at.isoformat()}:{route_digest}"


def _snapshot_id(job: WatchScanJobRecord, offer: FlightOffer) -> UUID:
    raw = f"flight-hunter:watch-scan:{job.id}:{offer.provider_id}:{offer.provider_offer_id}"
    return uuid5(NAMESPACE_URL, raw)


def _itinerary_fingerprint(offer: FlightOffer) -> str:
    return "|".join(
        (
            offer.provider_id,
            offer.provider_offer_id,
            offer.origin,
            offer.destination,
            offer.departure_date,
            offer.return_date or "",
            str(offer.passengers),
            offer.total_price.currency,
        )
    )


def _offer_matches_watch(offer: FlightOffer, watch: WatchRecord) -> bool:
    return (
        offer.origin == watch.origin
        and offer.destination == watch.destination
        and offer.departure_date == watch.departure_date
        and offer.return_date == watch.return_date
        and offer.passengers == watch.passengers
        and offer.total_price.currency == watch.currency
    )


def _skip_code(blocked_reasons: tuple[str, ...], provider_denials: dict[str, str]) -> str:
    if blocked_reasons:
        return blocked_reasons[0]
    if provider_denials:
        return sorted(set(provider_denials.values()))[0]
    return "no_allowed_provider"


def _provider_error_code(exc: Exception) -> str:
    name = exc.__class__.__name__.lower()
    text = str(exc).lower()
    if "rate" in name and "limit" in name:
        return "rate_limited"
    if "rate_limited" in text:
        return "rate_limited"
    if "timeout" in name or "timed_out" in text:
        return "provider_timeout"
    return "provider_error"


def _provider_error_message(exc: Exception) -> str:
    return f"{exc.__class__.__name__} during watch scan provider call"
