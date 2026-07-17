from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, insert, or_, select, true, update
from sqlalchemy.engine import CursorResult, RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from flight_hunter.domain.auth import AuthSession, HouseholdRole
from flight_hunter.domain.manual_confirmation import (
    ManualConfirmationStatus,
    ManualPriceConfirmation,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import (
    LiveObservation,
    ObservationErrorCode,
    ObservationStatus,
)
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.places import PlaceKind
from flight_hunter.domain.policy import UserActionGrant, require_aware_datetime
from flight_hunter.domain.search_results import (
    BrowserObservedOffer,
    Confidence,
    DealCandidate,
    ResultKind,
)
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportImportBatch,
    AirportImportRun,
    AirportType,
    freeze_airport_catalog,
)
from flight_hunter.notifications.alerts import AlertEvaluationState, PriceAlert
from flight_hunter.persistence.models import (
    agent_audit_events_table,
    airport_import_runs_table,
    airports_table,
    alert_dedupe_entries_table,
    audit_events_table,
    auth_invitations_table,
    auth_sessions_table,
    browser_observation_jobs_table,
    browser_observed_offers_table,
    deal_candidates_table,
    deal_discovery_jobs_table,
    household_memberships_table,
    households_table,
    live_observation_idempotency_table,
    live_observation_offers_table,
    live_observations_table,
    manual_price_confirmations_table,
    price_snapshots_table,
    source_health_events_table,
    telegram_accounts_table,
    telegram_link_codes_table,
    telegram_notification_outbox_table,
    telegram_update_dedupe_table,
    user_action_grants_table,
    users_table,
    watch_scan_jobs_table,
    watches_table,
    worker_control_table,
    worker_heartbeats_table,
)

WatchMutationStatus = Literal[
    "updated",
    "archived",
    "deleted",
    "not_found",
    "version_conflict",
]

# Exactly 80% is accepted; lower full snapshots are rejected before mutation.
MIN_OURAIRPORTS_SNAPSHOT_RETENTION_RATIO = Decimal("0.80")

_BROWSER_ACTIVE_STATUSES = (
    ObservationStatus.RUNNING.value,
    ObservationStatus.OPENING_BROWSER.value,
    ObservationStatus.WAITING_FOR_USER.value,
    ObservationStatus.CAPTURING_DOM.value,
    ObservationStatus.PARSING.value,
)


@dataclass(frozen=True, slots=True)
class HouseholdRecord:
    id: UUID
    name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    display_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class HouseholdMembershipRecord:
    household_id: UUID
    user_id: UUID
    role: HouseholdRole
    created_at: datetime
    disabled_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthInvitationRecord:
    id: UUID
    household_id: UUID
    invited_by_user_id: UUID | None
    role: HouseholdRole
    code_hash: str
    recipient_label: str | None
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None
    accepted_by_user_id: UUID | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuthSessionRecord:
    id: UUID
    household_id: UUID
    user_id: UUID
    token_hash: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewWatch:
    id: UUID
    household_id: UUID
    owner_user_id: UUID
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    created_at: datetime
    passengers: int = 1
    currency: str = "RUB"
    paused_until: datetime | None = None
    next_eligible_at: datetime | None = None
    scan_interval_seconds: int = 21_600
    allowed_provider_ids: tuple[str, ...] = ()
    updated_at: datetime | None = None
    origin_kind: PlaceKind = PlaceKind.CITY
    destination_kind: PlaceKind = PlaceKind.CITY
    origin_airport_codes: tuple[str, ...] = ()
    destination_airport_codes: tuple[str, ...] = ()
    directory_version: str = "legacy-provider-city-v1"
    origin_membership_version: str | None = None
    destination_membership_version: str | None = None


@dataclass(frozen=True, slots=True)
class WatchRecord:
    id: UUID
    household_id: UUID
    owner_user_id: UUID
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    currency: str
    enabled: bool
    paused_until: datetime | None
    next_eligible_at: datetime
    scan_interval_seconds: int
    allowed_provider_ids: tuple[str, ...]
    last_scanned_at: datetime | None
    last_scan_status: str | None
    last_scan_error_code: str | None
    created_at: datetime
    updated_at: datetime
    version: int
    archived_at: datetime | None
    archived_by_user_id: UUID | None
    deleted_at: datetime | None
    deleted_by_user_id: UUID | None
    origin_kind: PlaceKind = PlaceKind.CITY
    destination_kind: PlaceKind = PlaceKind.CITY
    origin_airport_codes: tuple[str, ...] = ()
    destination_airport_codes: tuple[str, ...] = ()
    directory_version: str = "legacy-provider-city-v1"
    origin_membership_version: str | None = None
    destination_membership_version: str | None = None


@dataclass(frozen=True, slots=True)
class WatchMutationResult:
    status: WatchMutationStatus
    watch: WatchRecord | None
    current_version: int | None


@dataclass(frozen=True, slots=True)
class NewAuditEvent:
    id: UUID
    household_id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    summary: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuditEventRecord:
    id: UUID
    household_id: UUID
    actor_user_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    summary: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewPriceSnapshot:
    id: UUID
    household_id: UUID
    watch_id: UUID
    provider_id: str
    itinerary_fingerprint: str
    observed_at: datetime
    price: Money
    freshness: Freshness
    requires_live_confirmation: bool


@dataclass(frozen=True, slots=True)
class PriceSnapshotRecord:
    id: UUID
    household_id: UUID
    watch_id: UUID
    provider_id: str
    itinerary_fingerprint: str
    observed_at: datetime
    price: Money
    freshness: Freshness
    requires_live_confirmation: bool


@dataclass(frozen=True, slots=True)
class NewWatchScanJob:
    id: UUID
    household_id: UUID
    watch_id: UUID
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    deadline_at: datetime
    created_at: datetime
    provider_ids: tuple[str, ...]
    provider_denials: dict[str, str]
    next_retry_at: datetime | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class WatchScanJobRecord:
    id: UUID
    household_id: UUID
    watch_id: UUID
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    deadline_at: datetime
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    provider_ids: tuple[str, ...]
    provider_denials: dict[str, str]
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class NewTelegramLinkCode:
    code: str
    household_id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TelegramLinkCodeRecord:
    code: str
    household_id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None


@dataclass(frozen=True, slots=True)
class TelegramAccountRecord:
    user_id: UUID
    household_id: UUID
    telegram_user_id: int
    chat_id: int
    linked_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class NewTelegramNotification:
    id: UUID
    household_id: UUID
    user_id: UUID
    chat_id: int | None
    kind: str
    dedupe_key: str
    payload_json: str
    status: str
    attempts: int
    created_at: datetime
    next_retry_at: datetime | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    sent_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramNotificationRecord:
    id: UUID
    household_id: UUID
    user_id: UUID
    chat_id: int | None
    kind: str
    dedupe_key: str
    payload_json: str
    status: str
    attempts: int
    next_retry_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    created_at: datetime
    sent_at: datetime | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True, slots=True)
class LiveObservationCleanupResult:
    grants_deleted: int
    observations_deleted: int
    offers_deleted: int
    idempotency_deleted: int


@dataclass(frozen=True, slots=True)
class AirportSearchMatch:
    airport: Airport
    label: str


@dataclass(frozen=True, slots=True)
class NewAgentAuditEvent:
    id: UUID
    household_id: UUID | None
    user_id: UUID | None
    event_type: str
    tool_name: str
    summary: str
    policy_decision: str
    related_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentAuditRecord:
    id: UUID
    household_id: UUID | None
    user_id: UUID | None
    event_type: str
    tool_name: str
    summary: str
    policy_decision: str
    related_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NewSourceHealthEvent:
    id: UUID
    source_id: str
    event_type: str
    status: str
    message: str
    observed_at: datetime
    cooldown_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceHealthEventRecord:
    id: UUID
    source_id: str
    event_type: str
    status: str
    message: str
    observed_at: datetime
    cooldown_until: datetime | None


@dataclass(frozen=True, slots=True)
class NewWorkerHeartbeat:
    worker_id: str
    role: str
    status: str
    current_phase: str
    started_at: datetime
    last_seen_at: datetime
    current_job_kind: str | None = None
    current_job_id: str | None = None
    stopping_at: datetime | None = None
    stopped_at: datetime | None = None
    last_summary_json: str = "{}"


@dataclass(frozen=True, slots=True)
class WorkerHeartbeatRecord:
    worker_id: str
    role: str
    status: str
    current_phase: str
    current_job_kind: str | None
    current_job_id: str | None
    started_at: datetime
    last_seen_at: datetime
    stopping_at: datetime | None
    stopped_at: datetime | None
    last_summary_json: str


@dataclass(frozen=True, slots=True)
class WorkerControlRecord:
    drain_requested: bool
    reason: str | None
    requested_by_household_id: UUID | None
    requested_by_user_id: UUID | None
    requested_at: datetime | None
    cleared_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkerQueueHealthRecord:
    lane: str
    status_counts: Mapping[str, int]
    due_count: int
    delayed_count: int
    stale_count: int
    expired_count: int
    oldest_queued_at: datetime | None
    oldest_locked_at: datetime | None


@dataclass(frozen=True, slots=True)
class StaleLeaseRecoveryResult:
    requeued: int
    failed: int = 0


@dataclass(frozen=True, slots=True)
class NewBrowserObservationJob:
    id: UUID
    household_id: UUID
    user_id: UUID
    source_id: str
    search_id: str
    search_intent_hash: str
    idempotency_key: str
    grant_id: UUID
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    adults: int
    children: int
    infants: int
    trip_type: str
    currency: str
    status: ObservationStatus
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class BrowserObservationJobRecord:
    id: UUID
    household_id: UUID
    user_id: UUID
    source_id: str
    search_id: str
    search_intent_hash: str
    idempotency_key: str
    grant_id: UUID
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    adults: int
    children: int
    infants: int
    trip_type: str
    currency: str
    status: ObservationStatus
    attempts: int
    last_attempted_at: datetime | None
    next_retry_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    created_at: datetime
    started_at: datetime | None
    waiting_since: datetime | None
    operator_resume_requested_at: datetime | None
    operator_abort_requested_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime
    error_code: ObservationErrorCode | None
    error_message: str | None

    @property
    def search_intent(self) -> SearchIntent:
        return SearchIntent(
            origin=self.origin,
            destination=self.destination,
            departure_date=self.departure_date,
            return_date=self.return_date,
            passengers=self.passengers,
            adults=self.adults,
            children=self.children,
            infants=self.infants,
            trip_type=self.trip_type,
            currency=self.currency,
        )


@dataclass(frozen=True, slots=True)
class NewDealCandidate:
    id: UUID
    household_id: UUID
    user_id: UUID
    search_id: str
    candidate: DealCandidate
    expires_at: datetime
    raw_ref: str | None = None


@dataclass(frozen=True, slots=True)
class NewDealDiscoveryJob:
    id: UUID
    household_id: UUID
    user_id: UUID
    search_id: str
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    deadline_at: datetime
    created_at: datetime
    search_intent_json: str
    limit: int
    next_retry_at: datetime | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result_count: int = 0
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class DealDiscoveryJobRecord:
    id: UUID
    household_id: UUID
    user_id: UUID
    search_id: str
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    deadline_at: datetime
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    search_intent_json: str
    limit: int
    result_count: int
    error_code: str | None
    error_message: str | None


class BrowserObservationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_job(self, job: NewBrowserObservationJob) -> None:
        require_aware_datetime(job.created_at, "created_at")
        require_aware_datetime(job.expires_at, "expires_at")
        await self._session.execute(
            insert(browser_observation_jobs_table).values(
                id=str(job.id),
                household_id=str(job.household_id),
                user_id=str(job.user_id),
                source_id=job.source_id,
                search_id=job.search_id,
                search_intent_hash=job.search_intent_hash,
                idempotency_key=job.idempotency_key,
                grant_id=str(job.grant_id),
                origin=job.origin,
                destination=job.destination,
                departure_date=job.departure_date,
                return_date=job.return_date,
                passengers=job.passengers,
                adults=job.adults,
                children=job.children,
                infants=job.infants,
                trip_type=job.trip_type,
                currency=job.currency,
                status=job.status.value,
                attempts=0,
                last_attempted_at=None,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                created_at=job.created_at,
                started_at=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                completed_at=None,
                expires_at=job.expires_at,
                error_code=None,
                error_message=None,
            )
        )

    async def get_job(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
    ) -> BrowserObservationJobRecord | None:
        result = await self._session.execute(
            select(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.household_id == str(household_id))
            .where(browser_observation_jobs_table.c.user_id == str(user_id))
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .limit(1)
        )
        row = result.fetchone()
        return _browser_observation_job(row._mapping) if row is not None else None

    async def get_job_by_id(self, job_id: UUID) -> BrowserObservationJobRecord | None:
        result = await self._session.execute(
            select(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .limit(1)
        )
        row = result.fetchone()
        return _browser_observation_job(row._mapping) if row is not None else None

    async def get_idempotent_job_id(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        idempotency_key: str,
    ) -> UUID | None:
        result = await self._session.execute(
            select(browser_observation_jobs_table.c.id)
            .where(browser_observation_jobs_table.c.household_id == str(household_id))
            .where(browser_observation_jobs_table.c.user_id == str(user_id))
            .where(browser_observation_jobs_table.c.idempotency_key == idempotency_key)
            .limit(1)
        )
        row = result.fetchone()
        return UUID(row._mapping["id"]) if row is not None else None

    async def list_queued(
        self,
        *,
        now: datetime,
        limit: int = 10,
    ) -> tuple[BrowserObservationJobRecord, ...]:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.status == ObservationStatus.QUEUED.value)
            .where(browser_observation_jobs_table.c.expires_at > now)
            .where(
                or_(
                    browser_observation_jobs_table.c.next_retry_at.is_(None),
                    browser_observation_jobs_table.c.next_retry_at <= now,
                )
            )
            .order_by(
                browser_observation_jobs_table.c.next_retry_at,
                browser_observation_jobs_table.c.created_at,
                browser_observation_jobs_table.c.id,
            )
            .limit(limit)
        )
        return tuple(_browser_observation_job(row._mapping) for row in result.fetchall())

    async def claim_queued(
        self,
        *,
        now: datetime,
        limit: int = 10,
        worker_id: str,
        max_concurrent: int | None = None,
        min_gap_seconds: int | float | None = None,
    ) -> tuple[BrowserObservationJobRecord, ...]:
        require_aware_datetime(now, "now")
        claimed: list[BrowserObservationJobRecord] = []
        candidates = await self.list_queued(now=now, limit=limit)
        for candidate in candidates:
            statement = (
                update(browser_observation_jobs_table)
                .where(browser_observation_jobs_table.c.id == str(candidate.id))
                .where(browser_observation_jobs_table.c.status == ObservationStatus.QUEUED.value)
                .where(browser_observation_jobs_table.c.expires_at > now)
                .where(
                    or_(
                        browser_observation_jobs_table.c.next_retry_at.is_(None),
                        browser_observation_jobs_table.c.next_retry_at <= now,
                    )
                )
                .values(
                    status=ObservationStatus.RUNNING.value,
                    attempts=browser_observation_jobs_table.c.attempts + 1,
                    last_attempted_at=now,
                    next_retry_at=None,
                    locked_at=now,
                    locked_by=worker_id,
                    started_at=now,
                    waiting_since=None,
                    operator_resume_requested_at=None,
                    operator_abort_requested_at=None,
                    completed_at=None,
                    error_code=None,
                    error_message=None,
                )
            )
            if max_concurrent is not None:
                running = browser_observation_jobs_table.alias("browser_running_jobs")
                running_count = (
                    select(func.count())
                    .select_from(running)
                    .where(running.c.status.in_(_BROWSER_ACTIVE_STATUSES))
                    .where(running.c.expires_at > now)
                    .scalar_subquery()
                )
                statement = statement.where(running_count < max_concurrent)
            if min_gap_seconds is not None and min_gap_seconds > 0:
                recent = browser_observation_jobs_table.alias("browser_recent_source_jobs")
                recent_after = now - timedelta(seconds=min_gap_seconds)
                recent_source_attempts = (
                    select(func.count())
                    .select_from(recent)
                    .where(recent.c.source_id == candidate.source_id)
                    .where(recent.c.last_attempted_at.is_not(None))
                    .where(recent.c.last_attempted_at > recent_after)
                    .scalar_subquery()
                )
                statement = statement.where(recent_source_attempts == 0)
            result = await self._session.execute(statement)
            if cast(CursorResult[Any], result).rowcount != 1:
                continue
            record = await self.get_job_by_id(candidate.id)
            if record is not None:
                claimed.append(record)
        return tuple(claimed)

    async def recover_stale_running(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> StaleLeaseRecoveryResult:
        require_aware_datetime(now, "now")
        require_aware_datetime(stale_before, "stale_before")
        stale_ids = await self._browser_stale_running_ids(stale_before=stale_before, limit=limit)
        requeued = 0
        failed = 0
        for job_id in stale_ids:
            requeue_result = await self._session.execute(
                update(browser_observation_jobs_table)
                .where(browser_observation_jobs_table.c.id == str(job_id))
                .where(browser_observation_jobs_table.c.status.in_(_BROWSER_ACTIVE_STATUSES))
                .where(browser_observation_jobs_table.c.locked_at <= stale_before)
                .where(browser_observation_jobs_table.c.expires_at > now)
                .values(
                    status=ObservationStatus.QUEUED.value,
                    next_retry_at=now,
                    locked_at=None,
                    locked_by=None,
                    waiting_since=None,
                    operator_resume_requested_at=None,
                    operator_abort_requested_at=None,
                    completed_at=now,
                    error_code=ObservationErrorCode.TIMED_OUT.value,
                    error_message="worker lease expired; job requeued",
                )
            )
            if cast(CursorResult[Any], requeue_result).rowcount == 1:
                requeued += 1
                continue
            fail_result = await self._session.execute(
                update(browser_observation_jobs_table)
                .where(browser_observation_jobs_table.c.id == str(job_id))
                .where(browser_observation_jobs_table.c.status.in_(_BROWSER_ACTIVE_STATUSES))
                .where(browser_observation_jobs_table.c.locked_at <= stale_before)
                .where(browser_observation_jobs_table.c.expires_at <= now)
                .values(
                    status=ObservationStatus.EXPIRED.value,
                    next_retry_at=None,
                    locked_at=None,
                    locked_by=None,
                    waiting_since=None,
                    operator_resume_requested_at=None,
                    operator_abort_requested_at=None,
                    completed_at=now,
                    error_code=ObservationErrorCode.EXPIRED.value,
                    error_message="worker lease recovered after job deadline",
                )
            )
            if cast(CursorResult[Any], fail_result).rowcount == 1:
                failed += 1
        return StaleLeaseRecoveryResult(requeued=requeued, failed=failed)

    async def _browser_stale_running_ids(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        result = await self._session.execute(
            select(browser_observation_jobs_table.c.id)
            .where(browser_observation_jobs_table.c.status.in_(_BROWSER_ACTIVE_STATUSES))
            .where(browser_observation_jobs_table.c.locked_at.is_not(None))
            .where(browser_observation_jobs_table.c.locked_at <= stale_before)
            .order_by(
                browser_observation_jobs_table.c.locked_at, browser_observation_jobs_table.c.id
            )
            .limit(limit)
        )
        return tuple(UUID(row._mapping["id"]) for row in result.fetchall())

    async def mark_running(self, *, job_id: UUID, started_at: datetime) -> None:
        require_aware_datetime(started_at, "started_at")
        await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .values(
                status=ObservationStatus.RUNNING.value,
                attempts=browser_observation_jobs_table.c.attempts + 1,
                last_attempted_at=started_at,
                next_retry_at=None,
                locked_at=started_at,
                locked_by="direct-runner",
                started_at=started_at,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                completed_at=None,
            )
        )

    async def mark_runtime_status(
        self,
        *,
        job_id: UUID,
        status: ObservationStatus,
        observed_at: datetime,
    ) -> None:
        require_aware_datetime(observed_at, "observed_at")
        if status.value not in _BROWSER_ACTIVE_STATUSES:
            raise ValueError("browser runtime status must be active")
        await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .where(browser_observation_jobs_table.c.status.in_(_BROWSER_ACTIVE_STATUSES))
            .values(
                status=status.value,
                locked_at=observed_at,
                waiting_since=(
                    observed_at if status == ObservationStatus.WAITING_FOR_USER else None
                ),
                operator_resume_requested_at=(
                    None
                    if status != ObservationStatus.WAITING_FOR_USER
                    else browser_observation_jobs_table.c.operator_resume_requested_at
                ),
                operator_abort_requested_at=(
                    None
                    if status != ObservationStatus.WAITING_FOR_USER
                    else browser_observation_jobs_table.c.operator_abort_requested_at
                ),
                completed_at=None,
                error_code=None,
                error_message=None,
            )
        )

    async def request_operator_resume(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
        requested_at: datetime,
    ) -> BrowserObservationJobRecord | None:
        require_aware_datetime(requested_at, "requested_at")
        result = await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .where(browser_observation_jobs_table.c.household_id == str(household_id))
            .where(browser_observation_jobs_table.c.user_id == str(user_id))
            .where(
                browser_observation_jobs_table.c.status == ObservationStatus.WAITING_FOR_USER.value
            )
            .where(browser_observation_jobs_table.c.operator_abort_requested_at.is_(None))
            .values(
                operator_resume_requested_at=requested_at,
                locked_at=requested_at,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            return None
        return await self.get_job(household_id=household_id, user_id=user_id, job_id=job_id)

    async def request_operator_abort(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        job_id: UUID,
        requested_at: datetime,
    ) -> BrowserObservationJobRecord | None:
        require_aware_datetime(requested_at, "requested_at")
        result = await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .where(browser_observation_jobs_table.c.household_id == str(household_id))
            .where(browser_observation_jobs_table.c.user_id == str(user_id))
            .where(
                browser_observation_jobs_table.c.status == ObservationStatus.WAITING_FOR_USER.value
            )
            .where(browser_observation_jobs_table.c.operator_resume_requested_at.is_(None))
            .values(
                operator_abort_requested_at=requested_at,
                locked_at=requested_at,
            )
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            return None
        return await self.get_job(household_id=household_id, user_id=user_id, job_id=job_id)

    async def mark_succeeded(self, *, job_id: UUID, completed_at: datetime) -> None:
        require_aware_datetime(completed_at, "completed_at")
        await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .values(
                status=ObservationStatus.SUCCEEDED.value,
                completed_at=completed_at,
                locked_at=None,
                locked_by=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                error_code=None,
                error_message=None,
            )
        )

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        status: ObservationStatus,
        error_code: ObservationErrorCode,
        error_message: str,
    ) -> None:
        require_aware_datetime(completed_at, "completed_at")
        await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .values(
                status=status.value,
                completed_at=completed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                error_code=error_code.value,
                error_message=error_message,
            )
        )

    async def mark_retry_scheduled(
        self,
        *,
        job_id: UUID,
        attempted_at: datetime,
        next_retry_at: datetime,
        error_code: ObservationErrorCode,
        error_message: str,
    ) -> None:
        require_aware_datetime(attempted_at, "attempted_at")
        require_aware_datetime(next_retry_at, "next_retry_at")
        await self._session.execute(
            update(browser_observation_jobs_table)
            .where(browser_observation_jobs_table.c.id == str(job_id))
            .values(
                status=ObservationStatus.QUEUED.value,
                completed_at=attempted_at,
                next_retry_at=next_retry_at,
                locked_at=None,
                locked_by=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                error_code=error_code.value,
                error_message=error_message,
            )
        )


class BrowserObservedOfferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_offer(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        search_id: str,
        offer: BrowserObservedOffer,
        expires_at: datetime,
    ) -> None:
        require_aware_datetime(offer.observed_at, "observed_at")
        require_aware_datetime(expires_at, "expires_at")
        await self._session.execute(
            insert(browser_observed_offers_table).values(
                id=str(offer.observation_id),
                household_id=str(household_id),
                user_id=str(user_id),
                search_id=search_id,
                source_id=offer.source_id,
                source_name=offer.source_name,
                provider_offer_id=offer.provider_offer_id,
                origin=offer.origin,
                destination=offer.destination,
                departure_date=offer.departure_date,
                return_date=offer.return_date,
                amount_minor=(
                    offer.total_price.minor_units if offer.total_price is not None else None
                ),
                currency=offer.total_price.currency if offer.total_price is not None else None,
                passengers=offer.passengers,
                observed_at=offer.observed_at,
                final_url=offer.final_url,
                display_url=offer.display_url,
                freshness=offer.freshness.value,
                confidence=Confidence(offer.confidence).value,
                parser_version=offer.parser_version,
                parser_warnings_json=json.dumps(list(offer.parser_warnings), ensure_ascii=False),
                airline_name=offer.airline_name,
                airline_iata=offer.airline_iata,
                flight_number=offer.flight_number,
                departure_time_local=offer.departure_time_local,
                arrival_time_local=offer.arrival_time_local,
                duration_minutes=offer.duration_minutes,
                stops=offer.stops,
                baggage_summary=offer.baggage_summary,
                seller_name=offer.seller_name,
                requires_external_confirmation=offer.requires_external_confirmation,
                expires_at=expires_at,
            )
        )

    async def list_recent(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        search_id: str,
        now: datetime,
    ) -> tuple[BrowserObservedOffer, ...]:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(browser_observed_offers_table)
            .where(browser_observed_offers_table.c.household_id == str(household_id))
            .where(browser_observed_offers_table.c.user_id == str(user_id))
            .where(browser_observed_offers_table.c.search_id == search_id)
            .where(browser_observed_offers_table.c.expires_at > now)
            .order_by(
                browser_observed_offers_table.c.observed_at.desc(),
                browser_observed_offers_table.c.id,
            )
        )
        return tuple(_browser_observed_offer(row._mapping) for row in result.fetchall())

    async def list_for_export(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> tuple[BrowserObservedOffer, ...]:
        bounded_limit = min(max(limit, 1), 1_000)
        result = await self._session.execute(
            select(browser_observed_offers_table)
            .where(browser_observed_offers_table.c.household_id == str(household_id))
            .where(browser_observed_offers_table.c.user_id == str(user_id))
            .order_by(
                browser_observed_offers_table.c.observed_at.desc(),
                browser_observed_offers_table.c.id,
            )
            .limit(bounded_limit)
        )
        return tuple(_browser_observed_offer(row._mapping) for row in result.fetchall())


class DealCandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_candidate(self, candidate: NewDealCandidate) -> None:
        require_aware_datetime(candidate.candidate.discovered_at, "discovered_at")
        require_aware_datetime(candidate.expires_at, "expires_at")
        if candidate.expires_at <= candidate.candidate.discovered_at:
            raise ValueError("expires_at must be after discovered_at")
        price = candidate.candidate.extracted_price
        await self._session.execute(
            insert(deal_candidates_table).values(
                id=str(candidate.id),
                household_id=str(candidate.household_id),
                user_id=str(candidate.user_id),
                search_id=candidate.search_id,
                source_id=candidate.candidate.source_id,
                discovered_url=candidate.candidate.url,
                title=candidate.candidate.title,
                summary=candidate.candidate.summary_ru,
                extracted_origin=candidate.candidate.extracted_origin,
                extracted_destination=candidate.candidate.extracted_destination,
                extracted_departure_window=candidate.candidate.extracted_date_window,
                extracted_price_minor_units=price.minor_units if price is not None else None,
                currency=price.currency if price is not None else None,
                confidence=Confidence(candidate.candidate.confidence).value,
                discovered_at=candidate.candidate.discovered_at,
                expires_at=candidate.expires_at,
                requires_manual_verification=candidate.candidate.requires_manual_verification,
                raw_ref=candidate.raw_ref,
            )
        )

    async def add_candidate_once(self, candidate: NewDealCandidate) -> bool:
        existing = await self._session.execute(
            select(deal_candidates_table.c.id)
            .where(deal_candidates_table.c.id == str(candidate.id))
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False
        await self.add_candidate(candidate)
        return True

    async def list_recent(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        search_id: str,
        now: datetime,
    ) -> tuple[DealCandidate, ...]:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(deal_candidates_table)
            .where(deal_candidates_table.c.household_id == str(household_id))
            .where(deal_candidates_table.c.user_id == str(user_id))
            .where(deal_candidates_table.c.search_id == search_id)
            .where(deal_candidates_table.c.expires_at > now)
            .order_by(
                deal_candidates_table.c.discovered_at.desc(),
                deal_candidates_table.c.id,
            )
        )
        return tuple(_deal_candidate(row._mapping) for row in result.fetchall())

    async def list_for_export(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> tuple[DealCandidate, ...]:
        bounded_limit = min(max(limit, 1), 1_000)
        result = await self._session.execute(
            select(deal_candidates_table)
            .where(deal_candidates_table.c.household_id == str(household_id))
            .where(deal_candidates_table.c.user_id == str(user_id))
            .order_by(
                deal_candidates_table.c.discovered_at.desc(),
                deal_candidates_table.c.id,
            )
            .limit(bounded_limit)
        )
        return tuple(_deal_candidate(row._mapping) for row in result.fetchall())

    async def cleanup_expired(self, *, now: datetime) -> int:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            delete(deal_candidates_table).where(deal_candidates_table.c.expires_at <= now)
        )
        return cast(CursorResult[Any], result).rowcount or 0


class DealDiscoveryJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_job(self, job: NewDealDiscoveryJob) -> bool:
        require_aware_datetime(job.created_at, "created_at")
        require_aware_datetime(job.deadline_at, "deadline_at")
        existing = await self._session.execute(
            select(deal_discovery_jobs_table.c.id)
            .where(deal_discovery_jobs_table.c.idempotency_key == job.idempotency_key)
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False
        await self._session.execute(
            insert(deal_discovery_jobs_table).values(
                id=str(job.id),
                household_id=str(job.household_id),
                user_id=str(job.user_id),
                search_id=job.search_id,
                idempotency_key=job.idempotency_key,
                status=job.status,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                next_retry_at=job.next_retry_at,
                locked_at=job.locked_at,
                locked_by=job.locked_by,
                deadline_at=job.deadline_at,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                search_intent_json=job.search_intent_json,
                limit=job.limit,
                result_count=job.result_count,
                error_code=job.error_code,
                error_message=job.error_message,
            )
        )
        return True

    async def get_job(self, job_id: UUID) -> DealDiscoveryJobRecord | None:
        result = await self._session.execute(
            select(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.id == str(job_id))
            .limit(1)
        )
        row = result.fetchone()
        return _deal_discovery_job_record(row._mapping) if row is not None else None

    async def get_idempotent_job(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        idempotency_key: str,
    ) -> DealDiscoveryJobRecord | None:
        result = await self._session.execute(
            select(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.household_id == str(household_id))
            .where(deal_discovery_jobs_table.c.user_id == str(user_id))
            .where(deal_discovery_jobs_table.c.idempotency_key == idempotency_key)
            .limit(1)
        )
        row = result.fetchone()
        return _deal_discovery_job_record(row._mapping) if row is not None else None

    async def list_queued(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[DealDiscoveryJobRecord, ...]:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.status.in_(("queued", "retry_scheduled")))
            .where(
                or_(
                    deal_discovery_jobs_table.c.next_retry_at.is_(None),
                    deal_discovery_jobs_table.c.next_retry_at <= now,
                )
            )
            .where(deal_discovery_jobs_table.c.deadline_at > now)
            .order_by(deal_discovery_jobs_table.c.created_at, deal_discovery_jobs_table.c.id)
            .limit(limit)
        )
        return tuple(_deal_discovery_job_record(row._mapping) for row in result.fetchall())

    async def claim_queued(
        self,
        *,
        now: datetime,
        limit: int,
        worker_id: str,
    ) -> tuple[DealDiscoveryJobRecord, ...]:
        require_aware_datetime(now, "now")
        claimed: list[DealDiscoveryJobRecord] = []
        candidates = await self.list_queued(now=now, limit=limit)
        for candidate in candidates:
            result = await self._session.execute(
                update(deal_discovery_jobs_table)
                .where(deal_discovery_jobs_table.c.id == str(candidate.id))
                .where(deal_discovery_jobs_table.c.status.in_(("queued", "retry_scheduled")))
                .where(
                    or_(
                        deal_discovery_jobs_table.c.next_retry_at.is_(None),
                        deal_discovery_jobs_table.c.next_retry_at <= now,
                    )
                )
                .where(deal_discovery_jobs_table.c.deadline_at > now)
                .values(
                    status="running",
                    attempts=deal_discovery_jobs_table.c.attempts + 1,
                    next_retry_at=None,
                    locked_at=now,
                    locked_by=worker_id,
                    started_at=now,
                    completed_at=None,
                    error_code=None,
                    error_message=None,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                continue
            record = await self.get_job(candidate.id)
            if record is not None:
                claimed.append(record)
        return tuple(claimed)

    async def recover_stale_running(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> StaleLeaseRecoveryResult:
        require_aware_datetime(now, "now")
        require_aware_datetime(stale_before, "stale_before")
        stale_ids = await self._stale_running_ids(stale_before=stale_before, limit=limit)
        requeued = 0
        failed = 0
        for job_id in stale_ids:
            retry_result = await self._session.execute(
                update(deal_discovery_jobs_table)
                .where(deal_discovery_jobs_table.c.id == str(job_id))
                .where(deal_discovery_jobs_table.c.status == "running")
                .where(deal_discovery_jobs_table.c.locked_at <= stale_before)
                .where(deal_discovery_jobs_table.c.deadline_at > now)
                .where(
                    deal_discovery_jobs_table.c.attempts < deal_discovery_jobs_table.c.max_attempts
                )
                .values(
                    status="retry_scheduled",
                    next_retry_at=now,
                    locked_at=None,
                    locked_by=None,
                    completed_at=now,
                    error_code="worker_lease_expired",
                    error_message="worker lease expired; deal discovery requeued",
                )
            )
            if cast(CursorResult[Any], retry_result).rowcount == 1:
                requeued += 1
                continue
            fail_result = await self._session.execute(
                update(deal_discovery_jobs_table)
                .where(deal_discovery_jobs_table.c.id == str(job_id))
                .where(deal_discovery_jobs_table.c.status == "running")
                .where(deal_discovery_jobs_table.c.locked_at <= stale_before)
                .values(
                    status="failed",
                    next_retry_at=None,
                    locked_at=None,
                    locked_by=None,
                    completed_at=now,
                    error_code="worker_lease_expired",
                    error_message="worker lease expired after retries or deadline",
                )
            )
            if cast(CursorResult[Any], fail_result).rowcount == 1:
                failed += 1
        return StaleLeaseRecoveryResult(requeued=requeued, failed=failed)

    async def mark_succeeded(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        result_count: int,
    ) -> None:
        await self._session.execute(
            update(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.id == str(job_id))
            .values(
                status="succeeded",
                completed_at=completed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                result_count=max(0, result_count),
                error_code=None,
                error_message=None,
            )
        )

    async def mark_retry_scheduled(
        self,
        *,
        job_id: UUID,
        retry_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.id == str(job_id))
            .values(
                status="retry_scheduled",
                next_retry_at=retry_at,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(deal_discovery_jobs_table)
            .where(deal_discovery_jobs_table.c.id == str(job_id))
            .values(
                status="failed",
                completed_at=completed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def _stale_running_ids(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        result = await self._session.execute(
            select(deal_discovery_jobs_table.c.id)
            .where(deal_discovery_jobs_table.c.status == "running")
            .where(deal_discovery_jobs_table.c.locked_at.is_not(None))
            .where(deal_discovery_jobs_table.c.locked_at <= stale_before)
            .order_by(deal_discovery_jobs_table.c.locked_at, deal_discovery_jobs_table.c.id)
            .limit(limit)
        )
        return tuple(UUID(row._mapping["id"]) for row in result.fetchall())


class ManualPriceConfirmationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_confirmation(self, confirmation: ManualPriceConfirmation) -> None:
        require_aware_datetime(confirmation.confirmed_at, "confirmed_at")
        price = confirmation.confirmed_price
        await self._session.execute(
            insert(manual_price_confirmations_table).values(
                id=str(confirmation.id),
                household_id=str(confirmation.household_id),
                user_id=str(confirmation.user_id),
                target_kind=ResultKind(confirmation.target_kind).value,
                target_id=confirmation.target_id,
                source_id=confirmation.source_id,
                status=ManualConfirmationStatus(confirmation.status).value,
                amount_minor=price.minor_units if price is not None else None,
                currency=price.currency if price is not None else None,
                note=confirmation.note,
                confirmed_at=confirmation.confirmed_at,
            )
        )

    async def list_recent(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        limit: int = 50,
        target_kind: str | None = None,
        target_id: str | None = None,
    ) -> tuple[ManualPriceConfirmation, ...]:
        bounded_limit = min(max(limit, 1), 100)
        statement = (
            select(manual_price_confirmations_table)
            .where(manual_price_confirmations_table.c.household_id == str(household_id))
            .where(manual_price_confirmations_table.c.user_id == str(user_id))
            .order_by(
                manual_price_confirmations_table.c.confirmed_at.desc(),
                manual_price_confirmations_table.c.id,
            )
            .limit(bounded_limit)
        )
        if target_kind is not None:
            statement = statement.where(
                manual_price_confirmations_table.c.target_kind == target_kind
            )
        if target_id is not None:
            statement = statement.where(manual_price_confirmations_table.c.target_id == target_id)
        result = await self._session.execute(statement)
        return tuple(_manual_price_confirmation(row._mapping) for row in result.fetchall())

    async def list_for_export(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        limit: int,
    ) -> tuple[ManualPriceConfirmation, ...]:
        bounded_limit = min(max(limit, 1), 1_000)
        result = await self._session.execute(
            select(manual_price_confirmations_table)
            .where(manual_price_confirmations_table.c.household_id == str(household_id))
            .where(manual_price_confirmations_table.c.user_id == str(user_id))
            .order_by(
                manual_price_confirmations_table.c.confirmed_at.desc(),
                manual_price_confirmations_table.c.id,
            )
            .limit(bounded_limit)
        )
        return tuple(_manual_price_confirmation(row._mapping) for row in result.fetchall())


class IdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_household(
        self,
        *,
        household_id: UUID,
        name: str,
        created_at: datetime,
    ) -> None:
        require_aware_datetime(created_at, "created_at")
        await self._session.execute(
            insert(households_table).values(
                id=str(household_id),
                name=name,
                created_at=created_at,
            )
        )

    async def add_user(
        self,
        *,
        user_id: UUID,
        display_name: str,
        created_at: datetime,
    ) -> None:
        require_aware_datetime(created_at, "created_at")
        await self._session.execute(
            insert(users_table).values(
                id=str(user_id),
                display_name=display_name,
                created_at=created_at,
            )
        )

    async def add_membership(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        role: HouseholdRole | str,
        created_at: datetime,
    ) -> None:
        require_aware_datetime(created_at, "created_at")
        await self._session.execute(
            insert(household_memberships_table).values(
                household_id=str(household_id),
                user_id=str(user_id),
                role=HouseholdRole(role).value,
                created_at=created_at,
                disabled_at=None,
            )
        )

    async def add_invitation(
        self,
        *,
        invitation_id: UUID,
        household_id: UUID,
        role: HouseholdRole | str,
        code_hash: str,
        created_at: datetime,
        expires_at: datetime,
        invited_by_user_id: UUID | None = None,
        recipient_label: str | None = None,
    ) -> None:
        require_aware_datetime(created_at, "created_at")
        require_aware_datetime(expires_at, "expires_at")
        await self._session.execute(
            insert(auth_invitations_table).values(
                id=str(invitation_id),
                household_id=str(household_id),
                invited_by_user_id=(
                    str(invited_by_user_id) if invited_by_user_id is not None else None
                ),
                role=HouseholdRole(role).value,
                code_hash=code_hash,
                recipient_label=recipient_label,
                created_at=created_at,
                expires_at=expires_at,
                accepted_at=None,
                accepted_by_user_id=None,
                revoked_at=None,
            )
        )

    async def invitation_by_code_hash(self, code_hash: str) -> AuthInvitationRecord | None:
        result = await self._session.execute(
            select(auth_invitations_table)
            .where(auth_invitations_table.c.code_hash == code_hash)
            .limit(1)
        )
        row = result.fetchone()
        if row is None:
            return None
        return _auth_invitation_record(row._mapping)

    async def mark_invitation_accepted(
        self,
        *,
        invitation_id: UUID,
        accepted_by_user_id: UUID,
        accepted_at: datetime,
    ) -> bool:
        require_aware_datetime(accepted_at, "accepted_at")
        result = await self._session.execute(
            update(auth_invitations_table)
            .where(auth_invitations_table.c.id == str(invitation_id))
            .where(auth_invitations_table.c.accepted_at.is_(None))
            .where(auth_invitations_table.c.revoked_at.is_(None))
            .values(
                accepted_at=accepted_at,
                accepted_by_user_id=str(accepted_by_user_id),
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def add_session(
        self,
        *,
        session_id: UUID,
        household_id: UUID,
        user_id: UUID,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        require_aware_datetime(created_at, "created_at")
        require_aware_datetime(expires_at, "expires_at")
        await self._session.execute(
            insert(auth_sessions_table).values(
                id=str(session_id),
                household_id=str(household_id),
                user_id=str(user_id),
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
                last_seen_at=None,
                revoked_at=None,
            )
        )

    async def session_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> AuthSession | None:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(
                auth_sessions_table.c.id,
                auth_sessions_table.c.household_id,
                auth_sessions_table.c.user_id,
                auth_sessions_table.c.created_at,
                auth_sessions_table.c.expires_at,
                household_memberships_table.c.role.label("membership_role"),
            )
            .join(
                household_memberships_table,
                (auth_sessions_table.c.household_id == household_memberships_table.c.household_id)
                & (auth_sessions_table.c.user_id == household_memberships_table.c.user_id),
            )
            .where(auth_sessions_table.c.token_hash == token_hash)
            .where(auth_sessions_table.c.revoked_at.is_(None))
            .where(auth_sessions_table.c.expires_at > now)
            .where(household_memberships_table.c.disabled_at.is_(None))
            .limit(1)
        )
        row = result.fetchone()
        if row is None:
            return None
        return _auth_session(row._mapping)

    async def revoke_sessions(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        revoked_at: datetime,
    ) -> int:
        require_aware_datetime(revoked_at, "revoked_at")
        result = await self._session.execute(
            update(auth_sessions_table)
            .where(auth_sessions_table.c.household_id == str(household_id))
            .where(auth_sessions_table.c.user_id == str(user_id))
            .where(auth_sessions_table.c.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        return cast(CursorResult[Any], result).rowcount or 0

    async def disable_membership(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        disabled_at: datetime,
    ) -> bool:
        require_aware_datetime(disabled_at, "disabled_at")
        result = await self._session.execute(
            update(household_memberships_table)
            .where(household_memberships_table.c.household_id == str(household_id))
            .where(household_memberships_table.c.user_id == str(user_id))
            .where(household_memberships_table.c.disabled_at.is_(None))
            .values(disabled_at=disabled_at)
        )
        return cast(CursorResult[Any], result).rowcount == 1


class AirportReferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def import_airports(
        self,
        batch: AirportImportBatch,
        *,
        imported_at: datetime,
        source: str = "ourairports",
    ) -> AirportImportRun:
        require_aware_datetime(imported_at, "imported_at")
        if source == "ourairports" and batch.observed_iata_codes is not None:
            await self._validate_ourairports_snapshot(batch)
        missing_evidence = tuple(
            airport.iata_code
            for airport in batch.airports
            if airport.scheduled_service is None or airport.commercial_provenance is None
        )
        if missing_evidence:
            raise ValueError(
                "airport imports require explicit commercial evidence: "
                + ", ".join(missing_evidence)
            )
        for airport in batch.airports:
            values = {
                "iata_code": airport.iata_code,
                "name": airport.name,
                "municipality": airport.municipality,
                "country_code": airport.country_code,
                "latitude": airport.latitude,
                "longitude": airport.longitude,
                "airport_type": airport.airport_type.value,
                "active": airport.active,
                "scheduled_service": airport.scheduled_service,
                "commercial_provenance": airport.commercial_provenance,
                "keywords": ", ".join(airport.keywords),
                "imported_at": imported_at,
            }
            existing = await self._session.execute(
                select(airports_table.c.iata_code)
                .where(airports_table.c.iata_code == airport.iata_code)
                .limit(1)
            )
            if existing.fetchone() is None:
                await self._session.execute(insert(airports_table).values(**values))
            else:
                await self._session.execute(
                    update(airports_table)
                    .where(airports_table.c.iata_code == airport.iata_code)
                    .values(**values)
                )

        if source == "ourairports" and batch.observed_iata_codes is not None:
            observed_codes = set(batch.observed_iata_codes)
            searchable_codes = {
                airport.iata_code for airport in batch.airports if airport.is_searchable
            }
            filtered_codes = observed_codes - searchable_codes
            stale_ourairports_condition = or_(
                airports_table.c.iata_code.in_(filtered_codes),
                airports_table.c.iata_code.not_in(observed_codes),
            )
            await self._session.execute(
                update(airports_table)
                .where(
                    or_(
                        and_(
                            airports_table.c.commercial_provenance
                            == "ourairports.scheduled_service",
                            stale_ourairports_condition,
                        ),
                        and_(
                            airports_table.c.commercial_provenance == "legacy_import_filter",
                            airports_table.c.iata_code.in_(filtered_codes),
                        ),
                    )
                )
                .values(active=False, imported_at=imported_at)
            )

        import_run = AirportImportRun(
            source=source,
            source_path=str(batch.source_path),
            imported_at=imported_at,
            rows_seen=batch.rows_seen,
            rows_imported=batch.rows_imported,
        )
        await self._session.execute(
            insert(airport_import_runs_table).values(
                id=str(uuid4()),
                source=import_run.source,
                source_path=import_run.source_path,
                imported_at=import_run.imported_at,
                rows_seen=import_run.rows_seen,
                rows_imported=import_run.rows_imported,
            )
        )
        return import_run

    async def _validate_ourairports_snapshot(self, batch: AirportImportBatch) -> None:
        observed_iata_codes = batch.observed_iata_codes
        assert observed_iata_codes is not None
        if not observed_iata_codes:
            raise ValueError("ourairports_snapshot_has_no_valid_iata")
        if len(observed_iata_codes) > batch.rows_seen:
            raise ValueError("ourairports_snapshot_observed_iata_exceeds_rows_seen")

        result = await self._session.execute(
            select(airport_import_runs_table.c.rows_seen)
            .where(airport_import_runs_table.c.source == "ourairports")
            .order_by(airport_import_runs_table.c.imported_at.desc())
            .limit(1)
        )
        previous_rows_seen = result.scalar_one_or_none()
        if (
            previous_rows_seen is not None
            and Decimal(batch.rows_seen)
            < Decimal(previous_rows_seen) * MIN_OURAIRPORTS_SNAPSHOT_RETENTION_RATIO
        ):
            raise ValueError("ourairports_snapshot_retention_below_0.80")

    async def search(self, query: str, *, limit: int = 8) -> tuple[AirportSearchMatch, ...]:
        normalized_query = _normalize_airport_query(query)
        if len(normalized_query) < 2:
            return ()

        pattern = f"%{normalized_query}%"
        result = await self._session.execute(
            select(airports_table).where(
                or_(
                    func.lower(airports_table.c.iata_code).like(pattern),
                    func.lower(airports_table.c.name).like(pattern),
                    func.lower(airports_table.c.municipality).like(pattern),
                    func.lower(airports_table.c.keywords).like(pattern),
                )
            )
        )
        matches = tuple(_airport_search_match(row._mapping) for row in result.fetchall())
        return tuple(
            sorted(
                matches,
                key=lambda match: _airport_search_sort_key(match.airport, normalized_query),
            )[:limit]
        )

    async def get(self, iata_code: str) -> Airport | None:
        result = await self._session.execute(
            select(airports_table)
            .where(airports_table.c.iata_code == iata_code.strip().upper())
            .limit(1)
        )
        row = result.fetchone()
        return _airport_from_row(row._mapping) if row is not None else None

    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        result = await self._session.execute(
            select(airports_table).order_by(airports_table.c.iata_code)
        )
        airports = tuple(_airport_from_row(row._mapping) for row in result.fetchall())
        return freeze_airport_catalog(airports)

    async def latest_import_run(self) -> AirportImportRun | None:
        result = await self._session.execute(
            select(airport_import_runs_table)
            .order_by(airport_import_runs_table.c.imported_at.desc())
            .limit(1)
        )
        row = result.fetchone()
        if row is None:
            return None
        mapping = row._mapping
        return AirportImportRun(
            source=mapping["source"],
            source_path=mapping["source_path"],
            imported_at=mapping["imported_at"],
            rows_seen=mapping["rows_seen"],
            rows_imported=mapping["rows_imported"],
        )


class AgentAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, event: NewAgentAuditEvent) -> None:
        require_aware_datetime(event.created_at, "created_at")
        await self._session.execute(
            insert(agent_audit_events_table).values(
                id=str(event.id),
                household_id=str(event.household_id) if event.household_id is not None else None,
                user_id=str(event.user_id) if event.user_id is not None else None,
                event_type=event.event_type,
                tool_name=event.tool_name,
                summary=event.summary,
                policy_decision=event.policy_decision,
                related_id=event.related_id,
                created_at=event.created_at,
            )
        )

    async def list_events(self, household_id: UUID) -> tuple[AgentAuditRecord, ...]:
        result = await self._session.execute(
            select(agent_audit_events_table)
            .where(agent_audit_events_table.c.household_id == str(household_id))
            .order_by(agent_audit_events_table.c.created_at, agent_audit_events_table.c.id)
        )
        return tuple(_agent_audit_record(row._mapping) for row in result.fetchall())


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, event: NewAuditEvent) -> None:
        require_aware_datetime(event.created_at, "created_at")
        await self._session.execute(
            insert(audit_events_table).values(
                id=str(event.id),
                household_id=str(event.household_id),
                actor_user_id=(
                    str(event.actor_user_id) if event.actor_user_id is not None else None
                ),
                action=event.action,
                entity_type=event.entity_type,
                entity_id=str(event.entity_id),
                summary=event.summary,
                created_at=event.created_at,
            )
        )

    async def list_events(self, household_id: UUID) -> tuple[AuditEventRecord, ...]:
        result = await self._session.execute(
            select(audit_events_table)
            .where(audit_events_table.c.household_id == str(household_id))
            .order_by(audit_events_table.c.created_at, audit_events_table.c.id)
        )
        return tuple(_audit_event_record(row._mapping) for row in result.fetchall())

    async def list_recent(
        self,
        household_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[AuditEventRecord, ...]:
        result = await self._session.execute(
            select(audit_events_table)
            .where(audit_events_table.c.household_id == str(household_id))
            .order_by(audit_events_table.c.created_at.desc(), audit_events_table.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return tuple(_audit_event_record(row._mapping) for row in result.fetchall())


class SourceHealthEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, event: NewSourceHealthEvent) -> None:
        require_aware_datetime(event.observed_at, "observed_at")
        if event.cooldown_until is not None:
            require_aware_datetime(event.cooldown_until, "cooldown_until")
        await self._session.execute(
            insert(source_health_events_table).values(
                id=str(event.id),
                source_id=event.source_id,
                event_type=event.event_type,
                status=event.status,
                message=event.message[:500],
                observed_at=event.observed_at,
                cooldown_until=event.cooldown_until,
            )
        )

    async def list_recent(
        self,
        *,
        source_id: str | None = None,
        limit: int = 20,
    ) -> tuple[SourceHealthEventRecord, ...]:
        statement = select(source_health_events_table)
        if source_id is not None:
            statement = statement.where(source_health_events_table.c.source_id == source_id)
        statement = statement.order_by(
            source_health_events_table.c.observed_at.desc(),
            source_health_events_table.c.id,
        ).limit(limit)
        result = await self._session.execute(statement)
        return tuple(_source_health_event_record(row._mapping) for row in result.fetchall())


class WorkerHeartbeatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, heartbeat: NewWorkerHeartbeat) -> None:
        require_aware_datetime(heartbeat.started_at, "started_at")
        require_aware_datetime(heartbeat.last_seen_at, "last_seen_at")
        if heartbeat.stopping_at is not None:
            require_aware_datetime(heartbeat.stopping_at, "stopping_at")
        if heartbeat.stopped_at is not None:
            require_aware_datetime(heartbeat.stopped_at, "stopped_at")
        existing = await self._session.execute(
            select(worker_heartbeats_table.c.worker_id)
            .where(worker_heartbeats_table.c.worker_id == heartbeat.worker_id)
            .limit(1)
        )
        values = {
            "role": heartbeat.role,
            "status": heartbeat.status,
            "current_phase": heartbeat.current_phase,
            "current_job_kind": heartbeat.current_job_kind,
            "current_job_id": heartbeat.current_job_id,
            "started_at": heartbeat.started_at,
            "last_seen_at": heartbeat.last_seen_at,
            "stopping_at": heartbeat.stopping_at,
            "stopped_at": heartbeat.stopped_at,
            "last_summary_json": heartbeat.last_summary_json[:4000],
        }
        if existing.fetchone() is None:
            await self._session.execute(
                insert(worker_heartbeats_table).values(worker_id=heartbeat.worker_id, **values)
            )
            return
        await self._session.execute(
            update(worker_heartbeats_table)
            .where(worker_heartbeats_table.c.worker_id == heartbeat.worker_id)
            .values(**values)
        )

    async def list_recent(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[WorkerHeartbeatRecord, ...]:
        result = await self._session.execute(
            select(worker_heartbeats_table)
            .order_by(
                worker_heartbeats_table.c.last_seen_at.desc(),
                worker_heartbeats_table.c.worker_id,
            )
            .limit(limit)
            .offset(offset)
        )
        return tuple(_worker_heartbeat_record(row._mapping) for row in result.fetchall())


class WorkerQueueHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def queue_health(
        self,
        *,
        now: datetime,
        stale_after: timedelta,
    ) -> tuple[WorkerQueueHealthRecord, ...]:
        require_aware_datetime(now, "now")
        stale_before = now - stale_after
        return (
            await self._aggregate_queue(
                lane="browser",
                table=browser_observation_jobs_table,
                queued_statuses=(ObservationStatus.QUEUED.value,),
                active_statuses=_BROWSER_ACTIVE_STATUSES,
                now=now,
                stale_before=stale_before,
                expiry_column=browser_observation_jobs_table.c.expires_at,
            ),
            await self._aggregate_queue(
                lane="watch",
                table=watch_scan_jobs_table,
                queued_statuses=("queued", "retry_scheduled"),
                active_statuses=("running",),
                now=now,
                stale_before=stale_before,
                deadline_column=watch_scan_jobs_table.c.deadline_at,
            ),
            await self._aggregate_queue(
                lane="deal",
                table=deal_discovery_jobs_table,
                queued_statuses=("queued", "retry_scheduled"),
                active_statuses=("running",),
                now=now,
                stale_before=stale_before,
                deadline_column=deal_discovery_jobs_table.c.deadline_at,
            ),
            await self._aggregate_queue(
                lane="telegram",
                table=telegram_notification_outbox_table,
                queued_statuses=("queued", "retry_scheduled"),
                active_statuses=("sending",),
                now=now,
                stale_before=stale_before,
            ),
        )

    async def _aggregate_queue(
        self,
        *,
        lane: str,
        table: Any,
        queued_statuses: tuple[str, ...],
        active_statuses: tuple[str, ...],
        now: datetime,
        stale_before: datetime,
        deadline_column: Any | None = None,
        expiry_column: Any | None = None,
    ) -> WorkerQueueHealthRecord:
        status_counts = await self._status_counts(table)
        claimable_guard = _claimable_guard(table, deadline_column, expiry_column, now)
        due_count = await self._count_where(
            table,
            table.c.status.in_(queued_statuses),
            _due_retry_guard(table, now),
            claimable_guard,
        )
        delayed_count = await self._count_where(
            table,
            table.c.status.in_(queued_statuses),
            table.c.next_retry_at.is_not(None),
            table.c.next_retry_at > now,
            claimable_guard,
        )
        stale_count = await self._count_where(
            table,
            table.c.status.in_(active_statuses),
            table.c.locked_at.is_not(None),
            table.c.locked_at <= stale_before,
            claimable_guard,
        )
        expired_count = await self._expired_count(
            table=table,
            statuses=queued_statuses + active_statuses,
            deadline_column=deadline_column,
            expiry_column=expiry_column,
            now=now,
        )
        oldest_queued_at = await self._min_datetime(
            table,
            table.c.created_at,
            table.c.status.in_(queued_statuses),
        )
        oldest_locked_at = await self._min_datetime(
            table,
            table.c.locked_at,
            table.c.status.in_(active_statuses),
            table.c.locked_at.is_not(None),
        )
        return WorkerQueueHealthRecord(
            lane=lane,
            status_counts=status_counts,
            due_count=due_count,
            delayed_count=delayed_count,
            stale_count=stale_count,
            expired_count=expired_count,
            oldest_queued_at=oldest_queued_at,
            oldest_locked_at=oldest_locked_at,
        )

    async def _status_counts(self, table: Any) -> Mapping[str, int]:
        result = await self._session.execute(
            select(table.c.status, func.count()).select_from(table).group_by(table.c.status)
        )
        return {str(status): int(count) for status, count in result.all()}

    async def _count_where(self, table: Any, *conditions: Any) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(table).where(*conditions)
        )
        return int(result.scalar_one())

    async def _expired_count(
        self,
        *,
        table: Any,
        statuses: tuple[str, ...],
        deadline_column: Any | None,
        expiry_column: Any | None,
        now: datetime,
    ) -> int:
        if deadline_column is None and expiry_column is None:
            return 0
        column = deadline_column if deadline_column is not None else expiry_column
        assert column is not None
        return await self._count_where(table, table.c.status.in_(statuses), column <= now)

    async def _min_datetime(self, table: Any, column: Any, *conditions: Any) -> datetime | None:
        result = await self._session.execute(
            select(func.min(column)).select_from(table).where(*conditions)
        )
        value = result.scalar_one()
        return _aware_datetime_or_none(cast(datetime | None, value))


def _due_retry_guard(table: Any, now: datetime) -> Any:
    return or_(table.c.next_retry_at.is_(None), table.c.next_retry_at <= now)


def _claimable_guard(
    table: Any,
    deadline_column: Any | None,
    expiry_column: Any | None,
    now: datetime,
) -> Any:
    del table
    conditions: list[Any] = []
    if deadline_column is not None:
        conditions.append(deadline_column > now)
    if expiry_column is not None:
        conditions.append(expiry_column > now)
    return and_(*conditions) if conditions else true()


def _aware_datetime_or_none(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class WorkerControlRepository:
    _ROW_ID = "global"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_state(self) -> WorkerControlRecord:
        result = await self._session.execute(
            select(worker_control_table).where(worker_control_table.c.id == self._ROW_ID).limit(1)
        )
        row = result.fetchone()
        if row is None:
            return WorkerControlRecord(
                drain_requested=False,
                reason=None,
                requested_by_household_id=None,
                requested_by_user_id=None,
                requested_at=None,
                cleared_at=None,
                updated_at=None,
            )
        return _worker_control_record(row._mapping)

    async def set_drain(
        self,
        *,
        drain_requested: bool,
        reason: str | None,
        requested_by_household_id: UUID | None,
        requested_by_user_id: UUID | None,
        changed_at: datetime,
    ) -> WorkerControlRecord:
        require_aware_datetime(changed_at, "changed_at")
        normalized_reason = reason.strip()[:500] if reason is not None and reason.strip() else None
        values = {
            "drain_requested": drain_requested,
            "reason": normalized_reason if drain_requested else None,
            "requested_by_household_id": (
                str(requested_by_household_id)
                if drain_requested and requested_by_household_id
                else None
            ),
            "requested_by_user_id": (
                str(requested_by_user_id) if drain_requested and requested_by_user_id else None
            ),
            "requested_at": changed_at if drain_requested else None,
            "cleared_at": None if drain_requested else changed_at,
            "updated_at": changed_at,
        }
        existing = await self._session.execute(
            select(worker_control_table.c.id)
            .where(worker_control_table.c.id == self._ROW_ID)
            .limit(1)
        )
        if existing.fetchone() is None:
            await self._session.execute(
                insert(worker_control_table).values(id=self._ROW_ID, **values)
            )
        else:
            await self._session.execute(
                update(worker_control_table)
                .where(worker_control_table.c.id == self._ROW_ID)
                .values(**values)
            )
        return await self.get_state()


class HouseholdWatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_watch(self, watch: NewWatch) -> None:
        updated_at = watch.updated_at or watch.created_at
        await self._session.execute(
            insert(watches_table).values(
                id=str(watch.id),
                household_id=str(watch.household_id),
                owner_user_id=str(watch.owner_user_id),
                origin=watch.origin.upper(),
                destination=watch.destination.upper(),
                origin_kind=watch.origin_kind.value,
                destination_kind=watch.destination_kind.value,
                origin_airport_codes_json=_dump_airport_codes(watch.origin_airport_codes),
                destination_airport_codes_json=_dump_airport_codes(watch.destination_airport_codes),
                directory_version=watch.directory_version,
                origin_membership_version=watch.origin_membership_version,
                destination_membership_version=watch.destination_membership_version,
                departure_date=watch.departure_date,
                return_date=watch.return_date,
                passengers=watch.passengers,
                currency=watch.currency.upper(),
                enabled=True,
                paused_until=watch.paused_until,
                next_eligible_at=watch.next_eligible_at or watch.created_at,
                scan_interval_seconds=watch.scan_interval_seconds,
                allowed_provider_ids=_join_csv(watch.allowed_provider_ids),
                last_scanned_at=None,
                last_scan_status=None,
                last_scan_error_code=None,
                created_at=watch.created_at,
                updated_at=updated_at,
                version=1,
                archived_at=None,
                archived_by_user_id=None,
                deleted_at=None,
                deleted_by_user_id=None,
            )
        )

    async def list_watches(self, household_id: UUID) -> tuple[WatchRecord, ...]:
        result = await self._session.execute(
            select(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .order_by(watches_table.c.created_at, watches_table.c.id)
        )
        return tuple(_watch_record(row._mapping) for row in result.fetchall())

    async def list_watches_for_export(
        self,
        household_id: UUID,
        *,
        limit: int,
    ) -> tuple[WatchRecord, ...]:
        bounded_limit = min(max(limit, 1), 1_000)
        result = await self._session.execute(
            select(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .order_by(watches_table.c.created_at, watches_table.c.id)
            .limit(bounded_limit)
        )
        return tuple(_watch_record(row._mapping) for row in result.fetchall())

    async def list_active_watches_for_owner(
        self,
        *,
        household_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[WatchRecord, ...]:
        result = await self._session.execute(
            select(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.owner_user_id == str(owner_user_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .order_by(watches_table.c.created_at, watches_table.c.id)
        )
        return tuple(_watch_record(row._mapping) for row in result.fetchall())

    async def get_watch(self, household_id: UUID, watch_id: UUID) -> WatchRecord | None:
        result = await self._session.execute(
            select(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .limit(1)
        )
        row = result.fetchone()
        return _watch_record(row._mapping) if row is not None else None

    async def pause_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        paused_until: datetime,
        updated_at: datetime,
    ) -> WatchRecord | None:
        require_aware_datetime(paused_until, "paused_until")
        require_aware_datetime(updated_at, "updated_at")
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .values(
                enabled=True,
                paused_until=paused_until,
                next_eligible_at=paused_until,
                updated_at=updated_at,
                version=watches_table.c.version + 1,
            )
        )
        return await self.get_watch(household_id, watch_id)

    async def resume_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        resumed_at: datetime,
    ) -> WatchRecord | None:
        require_aware_datetime(resumed_at, "resumed_at")
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .values(
                enabled=True,
                paused_until=None,
                next_eligible_at=resumed_at,
                updated_at=resumed_at,
                version=watches_table.c.version + 1,
            )
        )
        return await self.get_watch(household_id, watch_id)

    async def update_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        expected_version: int,
        updated_at: datetime,
        updates: Mapping[str, object],
    ) -> WatchMutationResult:
        require_aware_datetime(updated_at, "updated_at")
        current_version = await self._active_watch_version(household_id, watch_id)
        if current_version is None:
            return WatchMutationResult(status="not_found", watch=None, current_version=None)
        if current_version != expected_version:
            return WatchMutationResult(
                status="version_conflict",
                watch=await self.get_watch(household_id, watch_id),
                current_version=current_version,
            )

        values = self._watch_update_values(updates)
        if not values:
            current = await self.get_watch(household_id, watch_id)
            return WatchMutationResult(
                status="updated",
                watch=current,
                current_version=current.version if current is not None else current_version,
            )
        values["updated_at"] = updated_at
        values["version"] = watches_table.c.version + 1
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .where(watches_table.c.version == expected_version)
            .values(**values)
        )
        watch = await self.get_watch(household_id, watch_id)
        return WatchMutationResult(
            status="updated",
            watch=watch,
            current_version=watch.version if watch is not None else current_version + 1,
        )

    async def archive_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        expected_version: int,
        archived_at: datetime,
        archived_by_user_id: UUID,
    ) -> WatchMutationResult:
        require_aware_datetime(archived_at, "archived_at")
        current_version = await self._active_watch_version(household_id, watch_id)
        if current_version is None:
            return WatchMutationResult(status="not_found", watch=None, current_version=None)
        if current_version != expected_version:
            return WatchMutationResult(
                status="version_conflict",
                watch=await self.get_watch(household_id, watch_id),
                current_version=current_version,
            )
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .where(watches_table.c.version == expected_version)
            .values(
                enabled=False,
                archived_at=archived_at,
                archived_by_user_id=str(archived_by_user_id),
                updated_at=archived_at,
                version=watches_table.c.version + 1,
            )
        )
        return WatchMutationResult(
            status="archived",
            watch=None,
            current_version=current_version + 1,
        )

    async def delete_watch(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        expected_version: int,
        deleted_at: datetime,
        deleted_by_user_id: UUID,
    ) -> WatchMutationResult:
        require_aware_datetime(deleted_at, "deleted_at")
        current_version = await self._active_watch_version(household_id, watch_id)
        if current_version is None:
            return WatchMutationResult(status="not_found", watch=None, current_version=None)
        if current_version != expected_version:
            return WatchMutationResult(
                status="version_conflict",
                watch=await self.get_watch(household_id, watch_id),
                current_version=current_version,
            )
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .where(watches_table.c.version == expected_version)
            .values(
                enabled=False,
                deleted_at=deleted_at,
                deleted_by_user_id=str(deleted_by_user_id),
                updated_at=deleted_at,
                version=watches_table.c.version + 1,
            )
        )
        return WatchMutationResult(
            status="deleted",
            watch=None,
            current_version=current_version + 1,
        )

    async def list_due_watches(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[WatchRecord, ...]:
        result = await self._session.execute(
            select(watches_table)
            .where(watches_table.c.enabled.is_(True))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .where(
                or_(
                    watches_table.c.paused_until.is_(None),
                    watches_table.c.paused_until <= now,
                )
            )
            .where(watches_table.c.departure_date >= now.date().isoformat())
            .where(
                or_(
                    watches_table.c.next_eligible_at.is_(None),
                    watches_table.c.next_eligible_at <= now,
                )
            )
            .order_by(watches_table.c.next_eligible_at, watches_table.c.created_at)
            .limit(limit)
        )
        return tuple(_watch_record(row._mapping) for row in result.fetchall())

    async def record_scan_result(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        scanned_at: datetime,
        next_eligible_at: datetime,
        status: str,
        error_code: str | None,
    ) -> None:
        await self._session.execute(
            update(watches_table)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .values(
                last_scanned_at=scanned_at,
                next_eligible_at=next_eligible_at,
                last_scan_status=status,
                last_scan_error_code=error_code,
            )
        )

    async def _active_watch_version(self, household_id: UUID, watch_id: UUID) -> int | None:
        result = await self._session.execute(
            select(watches_table.c.version)
            .where(watches_table.c.household_id == str(household_id))
            .where(watches_table.c.id == str(watch_id))
            .where(watches_table.c.archived_at.is_(None))
            .where(watches_table.c.deleted_at.is_(None))
            .limit(1)
        )
        row = result.fetchone()
        return int(row._mapping["version"]) if row is not None else None

    @staticmethod
    def _watch_update_values(updates: Mapping[str, object]) -> dict[str, object]:
        values: dict[str, object] = {}
        for field, value in updates.items():
            if field in {"origin", "destination", "currency"} and isinstance(value, str):
                values[field] = value.upper()
            elif field in {"origin_kind", "destination_kind"}:
                values[field] = PlaceKind(cast(PlaceKind | str, value)).value
            elif field in {"origin_airport_codes", "destination_airport_codes"}:
                values[f"{field}_json"] = _dump_airport_codes(cast(tuple[str, ...], value))
            elif field == "allowed_provider_ids":
                values[field] = _join_csv(cast(tuple[str, ...], value))
            elif field in {
                "departure_date",
                "return_date",
                "passengers",
                "enabled",
                "paused_until",
                "next_eligible_at",
                "scan_interval_seconds",
                "directory_version",
                "origin_membership_version",
                "destination_membership_version",
            }:
                values[field] = value
        return values


class PriceSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_snapshot(self, snapshot: NewPriceSnapshot) -> None:
        await self._session.execute(
            insert(price_snapshots_table).values(
                id=str(snapshot.id),
                household_id=str(snapshot.household_id),
                watch_id=str(snapshot.watch_id),
                provider_id=snapshot.provider_id,
                itinerary_fingerprint=snapshot.itinerary_fingerprint,
                observed_at=snapshot.observed_at,
                amount_minor=snapshot.price.minor_units,
                currency=snapshot.price.currency,
                freshness=snapshot.freshness.value,
                requires_live_confirmation=snapshot.requires_live_confirmation,
            )
        )

    async def add_snapshot_once(self, snapshot: NewPriceSnapshot) -> bool:
        existing = await self._session.execute(
            select(price_snapshots_table.c.id)
            .where(price_snapshots_table.c.id == str(snapshot.id))
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False
        await self.add_snapshot(snapshot)
        return True

    async def list_history(
        self,
        household_id: UUID,
        watch_id: UUID,
    ) -> tuple[PriceSnapshotRecord, ...]:
        result = await self._session.execute(
            select(price_snapshots_table)
            .where(price_snapshots_table.c.household_id == str(household_id))
            .where(price_snapshots_table.c.watch_id == str(watch_id))
            .order_by(price_snapshots_table.c.observed_at, price_snapshots_table.c.id)
        )
        return tuple(_price_snapshot_record(row._mapping) for row in result.fetchall())

    async def get_best_before(
        self,
        *,
        household_id: UUID,
        watch_id: UUID,
        itinerary_fingerprint: str,
        observed_at: datetime,
    ) -> PriceSnapshotRecord | None:
        result = await self._session.execute(
            select(price_snapshots_table)
            .where(price_snapshots_table.c.household_id == str(household_id))
            .where(price_snapshots_table.c.watch_id == str(watch_id))
            .where(price_snapshots_table.c.itinerary_fingerprint == itinerary_fingerprint)
            .where(price_snapshots_table.c.observed_at < observed_at)
            .order_by(
                price_snapshots_table.c.amount_minor,
                price_snapshots_table.c.observed_at.desc(),
                price_snapshots_table.c.id,
            )
            .limit(1)
        )
        row = result.fetchone()
        return _price_snapshot_record(row._mapping) if row is not None else None


class WatchScanJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_job(self, job: NewWatchScanJob) -> bool:
        existing = await self._session.execute(
            select(watch_scan_jobs_table.c.id)
            .where(watch_scan_jobs_table.c.idempotency_key == job.idempotency_key)
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False
        await self._session.execute(
            insert(watch_scan_jobs_table).values(
                id=str(job.id),
                household_id=str(job.household_id),
                watch_id=str(job.watch_id),
                idempotency_key=job.idempotency_key,
                status=job.status,
                attempts=job.attempts,
                max_attempts=job.max_attempts,
                next_retry_at=job.next_retry_at,
                locked_at=job.locked_at,
                locked_by=job.locked_by,
                deadline_at=job.deadline_at,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                provider_ids=_join_csv(job.provider_ids),
                provider_denials=json.dumps(job.provider_denials, sort_keys=True),
                error_code=job.error_code,
                error_message=job.error_message,
            )
        )
        return True

    async def list_queued(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[WatchScanJobRecord, ...]:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(watch_scan_jobs_table)
            .where(watch_scan_jobs_table.c.status.in_(("queued", "retry_scheduled")))
            .where(
                or_(
                    watch_scan_jobs_table.c.next_retry_at.is_(None),
                    watch_scan_jobs_table.c.next_retry_at <= now,
                )
            )
            .where(watch_scan_jobs_table.c.deadline_at > now)
            .order_by(watch_scan_jobs_table.c.created_at, watch_scan_jobs_table.c.id)
            .limit(limit)
        )
        return tuple(_watch_scan_job_record(row._mapping) for row in result.fetchall())

    async def claim_queued(
        self,
        *,
        now: datetime,
        limit: int,
        worker_id: str,
    ) -> tuple[WatchScanJobRecord, ...]:
        require_aware_datetime(now, "now")
        claimed: list[WatchScanJobRecord] = []
        candidates = await self.list_queued(now=now, limit=limit)
        for candidate in candidates:
            result = await self._session.execute(
                update(watch_scan_jobs_table)
                .where(watch_scan_jobs_table.c.id == str(candidate.id))
                .where(watch_scan_jobs_table.c.status.in_(("queued", "retry_scheduled")))
                .where(
                    or_(
                        watch_scan_jobs_table.c.next_retry_at.is_(None),
                        watch_scan_jobs_table.c.next_retry_at <= now,
                    )
                )
                .where(watch_scan_jobs_table.c.deadline_at > now)
                .values(
                    status="running",
                    attempts=watch_scan_jobs_table.c.attempts + 1,
                    next_retry_at=None,
                    locked_at=now,
                    locked_by=worker_id,
                    started_at=now,
                    completed_at=None,
                    error_code=None,
                    error_message=None,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                continue
            record = await self.get_job(candidate.id)
            if record is not None:
                claimed.append(record)
        return tuple(claimed)

    async def recover_stale_running(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> StaleLeaseRecoveryResult:
        require_aware_datetime(now, "now")
        require_aware_datetime(stale_before, "stale_before")
        stale_ids = await self._watch_stale_running_ids(stale_before=stale_before, limit=limit)
        requeued = 0
        failed = 0
        for job_id in stale_ids:
            retry_result = await self._session.execute(
                update(watch_scan_jobs_table)
                .where(watch_scan_jobs_table.c.id == str(job_id))
                .where(watch_scan_jobs_table.c.status == "running")
                .where(watch_scan_jobs_table.c.locked_at <= stale_before)
                .where(watch_scan_jobs_table.c.deadline_at > now)
                .where(watch_scan_jobs_table.c.attempts < watch_scan_jobs_table.c.max_attempts)
                .values(
                    status="retry_scheduled",
                    next_retry_at=now,
                    locked_at=None,
                    locked_by=None,
                    completed_at=now,
                    error_code="worker_lease_expired",
                    error_message="worker lease expired; watch scan requeued",
                )
            )
            if cast(CursorResult[Any], retry_result).rowcount == 1:
                requeued += 1
                continue
            fail_result = await self._session.execute(
                update(watch_scan_jobs_table)
                .where(watch_scan_jobs_table.c.id == str(job_id))
                .where(watch_scan_jobs_table.c.status == "running")
                .where(watch_scan_jobs_table.c.locked_at <= stale_before)
                .values(
                    status="failed",
                    next_retry_at=None,
                    locked_at=None,
                    locked_by=None,
                    completed_at=now,
                    error_code="worker_lease_expired",
                    error_message="worker lease expired after retries or deadline",
                )
            )
            if cast(CursorResult[Any], fail_result).rowcount == 1:
                failed += 1
        return StaleLeaseRecoveryResult(requeued=requeued, failed=failed)

    async def _watch_stale_running_ids(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        result = await self._session.execute(
            select(watch_scan_jobs_table.c.id)
            .where(watch_scan_jobs_table.c.status == "running")
            .where(watch_scan_jobs_table.c.locked_at.is_not(None))
            .where(watch_scan_jobs_table.c.locked_at <= stale_before)
            .order_by(watch_scan_jobs_table.c.locked_at, watch_scan_jobs_table.c.id)
            .limit(limit)
        )
        return tuple(UUID(row._mapping["id"]) for row in result.fetchall())

    async def get_job(self, job_id: UUID) -> WatchScanJobRecord | None:
        result = await self._session.execute(
            select(watch_scan_jobs_table).where(watch_scan_jobs_table.c.id == str(job_id)).limit(1)
        )
        row = result.fetchone()
        return _watch_scan_job_record(row._mapping) if row is not None else None

    async def mark_running(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        started_at: datetime,
    ) -> None:
        await self._session.execute(
            update(watch_scan_jobs_table)
            .where(watch_scan_jobs_table.c.id == str(job_id))
            .values(
                status="running",
                attempts=watch_scan_jobs_table.c.attempts + 1,
                next_retry_at=None,
                locked_at=started_at,
                locked_by=worker_id,
                started_at=started_at,
                completed_at=None,
            )
        )

    async def mark_succeeded(self, *, job_id: UUID, completed_at: datetime) -> None:
        await self._session.execute(
            update(watch_scan_jobs_table)
            .where(watch_scan_jobs_table.c.id == str(job_id))
            .values(
                status="succeeded",
                completed_at=completed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                error_code=None,
                error_message=None,
            )
        )

    async def mark_retry_scheduled(
        self,
        *,
        job_id: UUID,
        retry_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(watch_scan_jobs_table)
            .where(watch_scan_jobs_table.c.id == str(job_id))
            .values(
                status="retry_scheduled",
                next_retry_at=retry_at,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def mark_failed(
        self,
        *,
        job_id: UUID,
        completed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(watch_scan_jobs_table)
            .where(watch_scan_jobs_table.c.id == str(job_id))
            .values(
                status="failed",
                completed_at=completed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )


class AlertDedupeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_state(
        self,
        household_id: UUID,
        watch_id: UUID,
    ) -> AlertEvaluationState:
        result = await self._session.execute(
            select(alert_dedupe_entries_table)
            .where(alert_dedupe_entries_table.c.household_id == str(household_id))
            .where(alert_dedupe_entries_table.c.watch_id == str(watch_id))
            .order_by(alert_dedupe_entries_table.c.sent_at)
        )
        sent_dedupe_keys: set[str] = set()
        last_sent_at_by_bucket: dict[str, datetime] = {}
        for row in result.fetchall():
            mapping = row._mapping
            sent_dedupe_keys.add(mapping["dedupe_key"])
            bucket = _alert_bucket(
                watch_id=mapping["watch_id"],
                itinerary_fingerprint=mapping["itinerary_fingerprint"],
                reason=mapping["reason"],
            )
            sent_at = _aware_datetime(mapping["sent_at"])
            previous = last_sent_at_by_bucket.get(bucket)
            if previous is None or sent_at > previous:
                last_sent_at_by_bucket[bucket] = sent_at

        return AlertEvaluationState(
            sent_dedupe_keys=frozenset(sent_dedupe_keys),
            last_sent_at_by_bucket=last_sent_at_by_bucket,
        )

    async def record_alert(self, household_id: UUID, alert: PriceAlert) -> bool:
        existing = await self._session.execute(
            select(alert_dedupe_entries_table.c.dedupe_key)
            .where(alert_dedupe_entries_table.c.dedupe_key == alert.dedupe_key)
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False

        await self._session.execute(
            insert(alert_dedupe_entries_table).values(
                dedupe_key=alert.dedupe_key,
                household_id=str(household_id),
                watch_id=alert.watch_id,
                itinerary_fingerprint=alert.itinerary_fingerprint,
                reason=alert.reason.value,
                sent_at=alert.observed_at,
            )
        )
        return True


class TelegramUpdateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_update(self, *, update_id: int, received_at: datetime) -> bool:
        require_aware_datetime(received_at, "received_at")
        existing = await self._session.execute(
            select(telegram_update_dedupe_table.c.update_id)
            .where(telegram_update_dedupe_table.c.update_id == update_id)
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False

        await self._session.execute(
            insert(telegram_update_dedupe_table).values(
                update_id=update_id,
                received_at=received_at,
            )
        )
        return True


class TelegramLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_code(self, code: NewTelegramLinkCode) -> None:
        require_aware_datetime(code.created_at, "created_at")
        require_aware_datetime(code.expires_at, "expires_at")
        await self._session.execute(
            insert(telegram_link_codes_table).values(
                code=code.code,
                household_id=str(code.household_id),
                user_id=str(code.user_id),
                created_at=code.created_at,
                expires_at=code.expires_at,
                consumed_at=None,
            )
        )

    async def consume_code(
        self,
        *,
        code: str,
        telegram_user_id: int,
        chat_id: int,
        now: datetime,
    ) -> TelegramAccountRecord | None:
        require_aware_datetime(now, "now")
        result = await self._session.execute(
            select(telegram_link_codes_table)
            .where(telegram_link_codes_table.c.code == code)
            .where(telegram_link_codes_table.c.consumed_at.is_(None))
            .where(telegram_link_codes_table.c.expires_at > now)
            .limit(1)
        )
        row = result.fetchone()
        if row is None:
            return None
        link_code = _telegram_link_code_record(row._mapping)
        await self._session.execute(
            update(telegram_link_codes_table)
            .where(telegram_link_codes_table.c.code == code)
            .values(consumed_at=now)
        )
        existing = await self.get_account_for_user(link_code.user_id)
        if existing is None:
            await self._session.execute(
                insert(telegram_accounts_table).values(
                    user_id=str(link_code.user_id),
                    household_id=str(link_code.household_id),
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    linked_at=now,
                    revoked_at=None,
                )
            )
        else:
            await self._session.execute(
                update(telegram_accounts_table)
                .where(telegram_accounts_table.c.user_id == str(link_code.user_id))
                .values(
                    household_id=str(link_code.household_id),
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    linked_at=now,
                    revoked_at=None,
                )
            )
        account = await self.get_account_for_user(link_code.user_id)
        if account is None:
            raise RuntimeError("telegram account was not persisted")
        return account

    async def get_account_for_user(self, user_id: UUID) -> TelegramAccountRecord | None:
        result = await self._session.execute(
            select(telegram_accounts_table)
            .where(telegram_accounts_table.c.user_id == str(user_id))
            .where(telegram_accounts_table.c.revoked_at.is_(None))
            .limit(1)
        )
        row = result.fetchone()
        return _telegram_account_record(row._mapping) if row is not None else None

    async def get_account_for_telegram_user(
        self,
        telegram_user_id: int,
    ) -> TelegramAccountRecord | None:
        result = await self._session.execute(
            select(telegram_accounts_table)
            .where(telegram_accounts_table.c.telegram_user_id == telegram_user_id)
            .where(telegram_accounts_table.c.revoked_at.is_(None))
            .limit(1)
        )
        row = result.fetchone()
        return _telegram_account_record(row._mapping) if row is not None else None

    async def revoke_account_for_user(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        revoked_at: datetime,
    ) -> bool:
        require_aware_datetime(revoked_at, "revoked_at")
        result = await self._session.execute(
            update(telegram_accounts_table)
            .where(telegram_accounts_table.c.household_id == str(household_id))
            .where(telegram_accounts_table.c.user_id == str(user_id))
            .where(telegram_accounts_table.c.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        return cast(CursorResult[Any], result).rowcount == 1


class TelegramNotificationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, notification: NewTelegramNotification) -> bool:
        existing = await self._session.execute(
            select(telegram_notification_outbox_table.c.id)
            .where(telegram_notification_outbox_table.c.dedupe_key == notification.dedupe_key)
            .limit(1)
        )
        if existing.fetchone() is not None:
            return False
        await self._session.execute(
            insert(telegram_notification_outbox_table).values(
                id=str(notification.id),
                household_id=str(notification.household_id),
                user_id=str(notification.user_id),
                chat_id=notification.chat_id,
                kind=notification.kind,
                dedupe_key=notification.dedupe_key,
                payload_json=notification.payload_json,
                status=notification.status,
                attempts=notification.attempts,
                next_retry_at=notification.next_retry_at,
                locked_at=notification.locked_at,
                locked_by=notification.locked_by,
                created_at=notification.created_at,
                sent_at=notification.sent_at,
                error_code=notification.error_code,
                error_message=notification.error_message,
            )
        )
        return True

    async def has_dedupe_key(self, dedupe_key: str) -> bool:
        result = await self._session.execute(
            select(telegram_notification_outbox_table.c.id)
            .where(telegram_notification_outbox_table.c.dedupe_key == dedupe_key)
            .limit(1)
        )
        return result.fetchone() is not None

    async def list_due(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[TelegramNotificationRecord, ...]:
        result = await self._session.execute(
            select(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.status.in_(("queued", "retry_scheduled")))
            .where(
                or_(
                    telegram_notification_outbox_table.c.next_retry_at.is_(None),
                    telegram_notification_outbox_table.c.next_retry_at <= now,
                )
            )
            .order_by(
                telegram_notification_outbox_table.c.created_at,
                telegram_notification_outbox_table.c.id,
            )
            .limit(limit)
        )
        return tuple(_telegram_notification_record(row._mapping) for row in result.fetchall())

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        worker_id: str,
    ) -> tuple[TelegramNotificationRecord, ...]:
        require_aware_datetime(now, "now")
        claimed: list[TelegramNotificationRecord] = []
        candidates = await self.list_due(now=now, limit=limit)
        for candidate in candidates:
            result = await self._session.execute(
                update(telegram_notification_outbox_table)
                .where(telegram_notification_outbox_table.c.id == str(candidate.id))
                .where(
                    telegram_notification_outbox_table.c.status.in_(("queued", "retry_scheduled"))
                )
                .where(
                    or_(
                        telegram_notification_outbox_table.c.next_retry_at.is_(None),
                        telegram_notification_outbox_table.c.next_retry_at <= now,
                    )
                )
                .values(
                    status="sending",
                    locked_at=now,
                    locked_by=worker_id,
                    error_code=None,
                    error_message=None,
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                continue
            record = await self.get_notification(candidate.id)
            if record is not None:
                claimed.append(record)
        return tuple(claimed)

    async def recover_stale_sending(
        self,
        *,
        now: datetime,
        stale_before: datetime,
        limit: int,
    ) -> int:
        require_aware_datetime(now, "now")
        require_aware_datetime(stale_before, "stale_before")
        stale_ids = await self._telegram_stale_sending_ids(stale_before=stale_before, limit=limit)
        recovered = 0
        for notification_id in stale_ids:
            result = await self._session.execute(
                update(telegram_notification_outbox_table)
                .where(telegram_notification_outbox_table.c.id == str(notification_id))
                .where(telegram_notification_outbox_table.c.status == "sending")
                .where(telegram_notification_outbox_table.c.locked_at <= stale_before)
                .values(
                    status="retry_scheduled",
                    next_retry_at=now,
                    locked_at=None,
                    locked_by=None,
                    error_code="worker_lease_expired",
                    error_message="worker lease expired; notification requeued",
                )
            )
            if cast(CursorResult[Any], result).rowcount == 1:
                recovered += 1
        return recovered

    async def _telegram_stale_sending_ids(
        self,
        *,
        stale_before: datetime,
        limit: int,
    ) -> tuple[UUID, ...]:
        result = await self._session.execute(
            select(telegram_notification_outbox_table.c.id)
            .where(telegram_notification_outbox_table.c.status == "sending")
            .where(telegram_notification_outbox_table.c.locked_at.is_not(None))
            .where(telegram_notification_outbox_table.c.locked_at <= stale_before)
            .order_by(
                telegram_notification_outbox_table.c.locked_at,
                telegram_notification_outbox_table.c.id,
            )
            .limit(limit)
        )
        return tuple(UUID(row._mapping["id"]) for row in result.fetchall())

    async def get_notification(
        self,
        notification_id: UUID,
    ) -> TelegramNotificationRecord | None:
        result = await self._session.execute(
            select(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.id == str(notification_id))
            .limit(1)
        )
        row = result.fetchone()
        return _telegram_notification_record(row._mapping) if row is not None else None

    async def mark_sent(self, *, notification_id: UUID, sent_at: datetime) -> None:
        await self._session.execute(
            update(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.id == str(notification_id))
            .values(
                status="sent",
                sent_at=sent_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                error_code=None,
                error_message=None,
            )
        )

    async def mark_retry_scheduled(
        self,
        *,
        notification_id: UUID,
        attempts: int,
        next_retry_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.id == str(notification_id))
            .values(
                status="retry_scheduled",
                attempts=attempts,
                next_retry_at=next_retry_at,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def mark_failed(
        self,
        *,
        notification_id: UUID,
        attempts: int,
        failed_at: datetime,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._session.execute(
            update(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.id == str(notification_id))
            .values(
                status="failed",
                attempts=attempts,
                sent_at=failed_at,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                error_code=error_code,
                error_message=error_message,
            )
        )

    async def list_by_user(self, user_id: UUID) -> tuple[TelegramNotificationRecord, ...]:
        result = await self._session.execute(
            select(telegram_notification_outbox_table)
            .where(telegram_notification_outbox_table.c.user_id == str(user_id))
            .order_by(telegram_notification_outbox_table.c.created_at)
        )
        return tuple(_telegram_notification_record(row._mapping) for row in result.fetchall())


class LiveObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_grant(self, grant: UserActionGrant) -> None:
        await self._session.execute(
            insert(user_action_grants_table).values(
                id=str(grant.id),
                user_id=str(grant.user_id),
                provider_id=grant.provider_id,
                action_type=grant.action_type,
                request_fingerprint=grant.request_fingerprint,
                issued_at=grant.issued_at,
                expires_at=grant.expires_at,
                source=grant.source,
                consumed_at=grant.consumed_at,
            )
        )

    async def get_grant(self, user_id: UUID, grant_id: UUID) -> UserActionGrant | None:
        result = await self._session.execute(
            select(user_action_grants_table)
            .where(user_action_grants_table.c.user_id == str(user_id))
            .where(user_action_grants_table.c.id == str(grant_id))
            .limit(1)
        )
        row = result.fetchone()
        return _user_action_grant(row._mapping) if row is not None else None

    async def consume_grant(self, grant_id: UUID, *, consumed_at: datetime) -> bool:
        existing = await self._session.execute(
            select(user_action_grants_table.c.consumed_at)
            .where(user_action_grants_table.c.id == str(grant_id))
            .limit(1)
        )
        row = existing.fetchone()
        if row is None or row._mapping["consumed_at"] is not None:
            return False

        await self._session.execute(
            update(user_action_grants_table)
            .where(user_action_grants_table.c.id == str(grant_id))
            .values(consumed_at=consumed_at)
        )
        return True

    async def add_observation(self, observation: LiveObservation) -> None:
        await self._session.execute(
            insert(live_observations_table).values(
                id=str(observation.observation_id),
                grant_id=str(observation.grant_id),
                user_id=str(observation.user_id),
                source_id=observation.source_id,
                search_intent_hash=observation.search_intent_hash,
                status=observation.status.value,
                created_at=observation.created_at,
                started_at=observation.started_at,
                completed_at=observation.completed_at,
                expires_at=observation.expires_at,
                error_code=(
                    observation.error_code.value if observation.error_code is not None else None
                ),
                error_message=observation.error_message,
            )
        )
        for offer in observation.offers:
            await self._session.execute(
                insert(live_observation_offers_table).values(
                    id=str(uuid4()),
                    observation_id=str(observation.observation_id),
                    provider_id=offer.provider_id,
                    provider_offer_id=offer.provider_offer_id,
                    origin=offer.origin,
                    destination=offer.destination,
                    departure_date=offer.departure_date,
                    return_date=offer.return_date,
                    amount_minor=offer.total_price.minor_units,
                    currency=offer.total_price.currency,
                    passengers=offer.passengers,
                    observed_at=offer.observed_at,
                    freshness=offer.freshness.value,
                    requires_live_confirmation=offer.requires_live_confirmation,
                    baggage_summary=offer.baggage_summary,
                )
            )

    async def get_observation(
        self,
        user_id: UUID,
        observation_id: UUID,
    ) -> LiveObservation | None:
        observation_result = await self._session.execute(
            select(live_observations_table)
            .where(live_observations_table.c.user_id == str(user_id))
            .where(live_observations_table.c.id == str(observation_id))
            .limit(1)
        )
        observation_row = observation_result.fetchone()
        if observation_row is None:
            return None

        offers_result = await self._session.execute(
            select(live_observation_offers_table)
            .where(live_observation_offers_table.c.observation_id == str(observation_id))
            .order_by(live_observation_offers_table.c.id)
        )
        offers = tuple(_live_offer(row._mapping) for row in offers_result.fetchall())
        return _live_observation(observation_row._mapping, offers=offers)

    async def get_idempotent_observation_id(
        self,
        user_id: UUID,
        idempotency_key: str,
    ) -> UUID | None:
        result = await self._session.execute(
            select(live_observation_idempotency_table.c.observation_id)
            .where(live_observation_idempotency_table.c.user_id == str(user_id))
            .where(live_observation_idempotency_table.c.idempotency_key == idempotency_key)
            .limit(1)
        )
        row = result.fetchone()
        return UUID(row._mapping["observation_id"]) if row is not None else None

    async def record_idempotency(
        self,
        *,
        user_id: UUID,
        idempotency_key: str,
        observation_id: UUID,
        created_at: datetime,
    ) -> None:
        await self._session.execute(
            insert(live_observation_idempotency_table).values(
                dedupe_key=_live_observation_dedupe_key(user_id, idempotency_key),
                user_id=str(user_id),
                idempotency_key=idempotency_key,
                observation_id=str(observation_id),
                created_at=created_at,
            )
        )

    async def last_completed_observation_at(
        self,
        *,
        user_id: UUID,
        source_id: str,
        search_intent_hash: str,
    ) -> datetime | None:
        result = await self._session.execute(
            select(live_observations_table.c.completed_at)
            .where(live_observations_table.c.user_id == str(user_id))
            .where(live_observations_table.c.source_id == source_id)
            .where(live_observations_table.c.search_intent_hash == search_intent_hash)
            .where(live_observations_table.c.completed_at.is_not(None))
            .order_by(live_observations_table.c.completed_at.desc())
            .limit(1)
        )
        row = result.fetchone()
        if row is None or row._mapping["completed_at"] is None:
            return None
        return _aware_datetime(row._mapping["completed_at"])

    async def cleanup_expired_live_observation_state(
        self,
        *,
        now: datetime,
    ) -> LiveObservationCleanupResult:
        require_aware_datetime(now, "now")
        expired_observation_ids = await self._expired_observation_ids(now=now)
        offers_deleted = 0
        idempotency_deleted = 0

        if expired_observation_ids:
            offer_ids = await self._offer_ids_for_observations(expired_observation_ids)
            idempotency_keys = await self._idempotency_keys_for_observations(
                expired_observation_ids
            )
            offers_deleted = len(offer_ids)
            idempotency_deleted = len(idempotency_keys)
            if offer_ids:
                await self._session.execute(
                    delete(live_observation_offers_table).where(
                        live_observation_offers_table.c.id.in_(offer_ids)
                    )
                )
            if idempotency_keys:
                await self._session.execute(
                    delete(live_observation_idempotency_table).where(
                        live_observation_idempotency_table.c.dedupe_key.in_(idempotency_keys)
                    )
                )
            await self._session.execute(
                delete(live_observations_table).where(
                    live_observations_table.c.id.in_(expired_observation_ids)
                )
            )

        expired_grant_ids = await self._expired_grant_ids(now=now)
        if expired_grant_ids:
            await self._session.execute(
                delete(user_action_grants_table).where(
                    user_action_grants_table.c.id.in_(expired_grant_ids)
                )
            )

        return LiveObservationCleanupResult(
            grants_deleted=len(expired_grant_ids),
            observations_deleted=len(expired_observation_ids),
            offers_deleted=offers_deleted,
            idempotency_deleted=idempotency_deleted,
        )

    async def _expired_observation_ids(self, *, now: datetime) -> tuple[str, ...]:
        result = await self._session.execute(
            select(live_observations_table.c.id).where(live_observations_table.c.expires_at <= now)
        )
        return tuple(row._mapping["id"] for row in result.fetchall())

    async def _offer_ids_for_observations(
        self,
        observation_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        result = await self._session.execute(
            select(live_observation_offers_table.c.id).where(
                live_observation_offers_table.c.observation_id.in_(observation_ids)
            )
        )
        return tuple(row._mapping["id"] for row in result.fetchall())

    async def _idempotency_keys_for_observations(
        self,
        observation_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        result = await self._session.execute(
            select(live_observation_idempotency_table.c.dedupe_key).where(
                live_observation_idempotency_table.c.observation_id.in_(observation_ids)
            )
        )
        return tuple(row._mapping["dedupe_key"] for row in result.fetchall())

    async def _expired_grant_ids(self, *, now: datetime) -> tuple[str, ...]:
        result = await self._session.execute(
            select(user_action_grants_table.c.id).where(
                user_action_grants_table.c.expires_at <= now
            )
        )
        return tuple(row._mapping["id"] for row in result.fetchall())


def _watch_record(row: RowMapping) -> WatchRecord:
    return WatchRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        owner_user_id=UUID(row["owner_user_id"]),
        origin=row["origin"],
        destination=row["destination"],
        departure_date=row["departure_date"],
        return_date=row["return_date"],
        passengers=row["passengers"],
        currency=row["currency"],
        enabled=row["enabled"],
        paused_until=_aware_datetime(row["paused_until"])
        if row["paused_until"] is not None
        else None,
        next_eligible_at=(
            _aware_datetime(row["next_eligible_at"])
            if row["next_eligible_at"] is not None
            else _aware_datetime(row["created_at"])
        ),
        scan_interval_seconds=row["scan_interval_seconds"],
        allowed_provider_ids=_split_csv(row["allowed_provider_ids"]),
        last_scanned_at=(
            _aware_datetime(row["last_scanned_at"]) if row["last_scanned_at"] is not None else None
        ),
        last_scan_status=row["last_scan_status"],
        last_scan_error_code=row["last_scan_error_code"],
        created_at=_aware_datetime(row["created_at"]),
        updated_at=_aware_datetime(row["updated_at"]),
        version=row["version"],
        archived_at=(
            _aware_datetime(row["archived_at"]) if row["archived_at"] is not None else None
        ),
        archived_by_user_id=(
            UUID(row["archived_by_user_id"]) if row["archived_by_user_id"] is not None else None
        ),
        deleted_at=_aware_datetime(row["deleted_at"]) if row["deleted_at"] is not None else None,
        deleted_by_user_id=(
            UUID(row["deleted_by_user_id"]) if row["deleted_by_user_id"] is not None else None
        ),
        origin_kind=PlaceKind(row["origin_kind"]),
        destination_kind=PlaceKind(row["destination_kind"]),
        origin_airport_codes=_loads_airport_codes(row["origin_airport_codes_json"]),
        destination_airport_codes=_loads_airport_codes(row["destination_airport_codes_json"]),
        directory_version=row["directory_version"],
        origin_membership_version=row["origin_membership_version"],
        destination_membership_version=row["destination_membership_version"],
    )


def _auth_invitation_record(row: RowMapping) -> AuthInvitationRecord:
    return AuthInvitationRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        invited_by_user_id=(
            UUID(row["invited_by_user_id"]) if row["invited_by_user_id"] is not None else None
        ),
        role=HouseholdRole(row["role"]),
        code_hash=row["code_hash"],
        recipient_label=row["recipient_label"],
        created_at=_aware_datetime(row["created_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
        accepted_at=(
            _aware_datetime(row["accepted_at"]) if row["accepted_at"] is not None else None
        ),
        accepted_by_user_id=(
            UUID(row["accepted_by_user_id"]) if row["accepted_by_user_id"] is not None else None
        ),
        revoked_at=_aware_datetime(row["revoked_at"]) if row["revoked_at"] is not None else None,
    )


def _auth_session(row: RowMapping) -> AuthSession:
    return AuthSession(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        role=HouseholdRole(row["membership_role"]),
        created_at=_aware_datetime(row["created_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
    )


def _airport_search_match(row: RowMapping) -> AirportSearchMatch:
    airport = _airport_from_row(row)
    return AirportSearchMatch(
        airport=airport,
        label=f"{airport.iata_code} - {airport.name}, {airport.municipality}",
    )


def _airport_from_row(row: RowMapping) -> Airport:
    return Airport(
        iata_code=row["iata_code"],
        name=row["name"],
        municipality=row["municipality"],
        country_code=row["country_code"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        airport_type=AirportType(row["airport_type"]),
        active=row["active"],
        keywords=_split_keywords(row["keywords"]),
        scheduled_service=row["scheduled_service"],
        commercial_provenance=row["commercial_provenance"],
    )


def _split_keywords(value: str) -> tuple[str, ...]:
    return tuple(keyword.strip() for keyword in value.split(",") if keyword.strip())


def _normalize_airport_query(query: str) -> str:
    normalized = query.strip().lower()
    for prefix, replacement in _CITY_ALIASES.items():
        if normalized.startswith(prefix):
            return replacement
    return normalized


def _airport_search_sort_key(airport: Airport, normalized_query: str) -> tuple[int, int, str]:
    if airport.iata_code.lower().startswith(normalized_query):
        priority = 0
    elif airport.municipality.lower().startswith(normalized_query):
        priority = 1
    elif airport.name.lower().startswith(normalized_query):
        priority = 2
    else:
        priority = 3
    type_priority = 0 if airport.airport_type == AirportType.LARGE_AIRPORT else 1
    return (priority, type_priority, airport.iata_code)


def _agent_audit_record(row: RowMapping) -> AgentAuditRecord:
    return AgentAuditRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]) if row["household_id"] is not None else None,
        user_id=UUID(row["user_id"]) if row["user_id"] is not None else None,
        event_type=row["event_type"],
        tool_name=row["tool_name"],
        summary=row["summary"],
        policy_decision=row["policy_decision"],
        related_id=row["related_id"],
        created_at=_aware_datetime(row["created_at"]),
    )


def _audit_event_record(row: RowMapping) -> AuditEventRecord:
    return AuditEventRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        actor_user_id=UUID(row["actor_user_id"]) if row["actor_user_id"] is not None else None,
        action=row["action"],
        entity_type=row["entity_type"],
        entity_id=UUID(row["entity_id"]),
        summary=row["summary"],
        created_at=_aware_datetime(row["created_at"]),
    )


def _source_health_event_record(row: RowMapping) -> SourceHealthEventRecord:
    return SourceHealthEventRecord(
        id=UUID(row["id"]),
        source_id=row["source_id"],
        event_type=row["event_type"],
        status=row["status"],
        message=row["message"],
        observed_at=_aware_datetime(row["observed_at"]),
        cooldown_until=(
            _aware_datetime(row["cooldown_until"]) if row["cooldown_until"] is not None else None
        ),
    )


def _worker_heartbeat_record(row: RowMapping) -> WorkerHeartbeatRecord:
    return WorkerHeartbeatRecord(
        worker_id=row["worker_id"],
        role=row["role"],
        status=row["status"],
        current_phase=row["current_phase"],
        current_job_kind=row["current_job_kind"],
        current_job_id=row["current_job_id"],
        started_at=_aware_datetime(row["started_at"]),
        last_seen_at=_aware_datetime(row["last_seen_at"]),
        stopping_at=(
            _aware_datetime(row["stopping_at"]) if row["stopping_at"] is not None else None
        ),
        stopped_at=_aware_datetime(row["stopped_at"]) if row["stopped_at"] is not None else None,
        last_summary_json=row["last_summary_json"],
    )


def _worker_control_record(row: RowMapping) -> WorkerControlRecord:
    return WorkerControlRecord(
        drain_requested=bool(row["drain_requested"]),
        reason=row["reason"],
        requested_by_household_id=(
            UUID(row["requested_by_household_id"])
            if row["requested_by_household_id"] is not None
            else None
        ),
        requested_by_user_id=(
            UUID(row["requested_by_user_id"]) if row["requested_by_user_id"] is not None else None
        ),
        requested_at=(
            _aware_datetime(row["requested_at"]) if row["requested_at"] is not None else None
        ),
        cleared_at=_aware_datetime(row["cleared_at"]) if row["cleared_at"] is not None else None,
        updated_at=_aware_datetime(row["updated_at"]) if row["updated_at"] is not None else None,
    )


def _price_snapshot_record(row: RowMapping) -> PriceSnapshotRecord:
    return PriceSnapshotRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        watch_id=UUID(row["watch_id"]),
        provider_id=row["provider_id"],
        itinerary_fingerprint=row["itinerary_fingerprint"],
        observed_at=_aware_datetime(row["observed_at"]),
        price=Money(row["amount_minor"], row["currency"]),
        freshness=Freshness(row["freshness"]),
        requires_live_confirmation=row["requires_live_confirmation"],
    )


def _watch_scan_job_record(row: RowMapping) -> WatchScanJobRecord:
    return WatchScanJobRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        watch_id=UUID(row["watch_id"]),
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        next_retry_at=(
            _aware_datetime(row["next_retry_at"]) if row["next_retry_at"] is not None else None
        ),
        locked_at=_aware_datetime(row["locked_at"]) if row["locked_at"] is not None else None,
        locked_by=row["locked_by"],
        deadline_at=_aware_datetime(row["deadline_at"]),
        created_at=_aware_datetime(row["created_at"]),
        started_at=(_aware_datetime(row["started_at"]) if row["started_at"] is not None else None),
        completed_at=(
            _aware_datetime(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        provider_ids=_split_csv(row["provider_ids"]),
        provider_denials=_loads_string_dict(row["provider_denials"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _telegram_link_code_record(row: RowMapping) -> TelegramLinkCodeRecord:
    return TelegramLinkCodeRecord(
        code=row["code"],
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        created_at=_aware_datetime(row["created_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
        consumed_at=(
            _aware_datetime(row["consumed_at"]) if row["consumed_at"] is not None else None
        ),
    )


def _telegram_account_record(row: RowMapping) -> TelegramAccountRecord:
    return TelegramAccountRecord(
        user_id=UUID(row["user_id"]),
        household_id=UUID(row["household_id"]),
        telegram_user_id=row["telegram_user_id"],
        chat_id=row["chat_id"],
        linked_at=_aware_datetime(row["linked_at"]),
        revoked_at=_aware_datetime(row["revoked_at"]) if row["revoked_at"] is not None else None,
    )


def _telegram_notification_record(row: RowMapping) -> TelegramNotificationRecord:
    return TelegramNotificationRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        chat_id=row["chat_id"],
        kind=row["kind"],
        dedupe_key=row["dedupe_key"],
        payload_json=row["payload_json"],
        status=row["status"],
        attempts=row["attempts"],
        next_retry_at=(
            _aware_datetime(row["next_retry_at"]) if row["next_retry_at"] is not None else None
        ),
        locked_at=_aware_datetime(row["locked_at"]) if row["locked_at"] is not None else None,
        locked_by=row["locked_by"],
        created_at=_aware_datetime(row["created_at"]),
        sent_at=_aware_datetime(row["sent_at"]) if row["sent_at"] is not None else None,
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _user_action_grant(row: RowMapping) -> UserActionGrant:
    return UserActionGrant(
        id=UUID(row["id"]),
        user_id=UUID(row["user_id"]),
        provider_id=row["provider_id"],
        action_type=row["action_type"],
        request_fingerprint=row["request_fingerprint"],
        issued_at=_aware_datetime(row["issued_at"]),
        expires_at=_aware_datetime(row["expires_at"]),
        source=row["source"],
        consumed_at=(
            _aware_datetime(row["consumed_at"]) if row["consumed_at"] is not None else None
        ),
    )


def _live_observation(
    row: RowMapping,
    *,
    offers: tuple[FlightOffer, ...],
) -> LiveObservation:
    return LiveObservation(
        observation_id=UUID(row["id"]),
        grant_id=UUID(row["grant_id"]),
        user_id=UUID(row["user_id"]),
        source_id=row["source_id"],
        search_intent_hash=row["search_intent_hash"],
        status=ObservationStatus(row["status"]),
        created_at=_aware_datetime(row["created_at"]),
        started_at=_aware_datetime(row["started_at"]) if row["started_at"] is not None else None,
        completed_at=(
            _aware_datetime(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        expires_at=_aware_datetime(row["expires_at"]),
        offers=offers,
        error_code=ObservationErrorCode(row["error_code"])
        if row["error_code"] is not None
        else None,
        error_message=row["error_message"],
    )


def _live_offer(row: RowMapping) -> FlightOffer:
    return FlightOffer(
        provider_id=row["provider_id"],
        provider_offer_id=row["provider_offer_id"],
        origin=row["origin"],
        destination=row["destination"],
        departure_date=row["departure_date"],
        return_date=row["return_date"],
        total_price=Money(row["amount_minor"], row["currency"]),
        passengers=row["passengers"],
        observed_at=_aware_datetime(row["observed_at"]),
        freshness=Freshness(row["freshness"]),
        requires_live_confirmation=row["requires_live_confirmation"],
        baggage_summary=row["baggage_summary"],
    )


def _browser_observation_job(row: RowMapping) -> BrowserObservationJobRecord:
    return BrowserObservationJobRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        source_id=row["source_id"],
        search_id=row["search_id"],
        search_intent_hash=row["search_intent_hash"],
        idempotency_key=row["idempotency_key"],
        grant_id=UUID(row["grant_id"]),
        origin=row["origin"],
        destination=row["destination"],
        departure_date=row["departure_date"],
        return_date=row["return_date"],
        passengers=row["passengers"],
        adults=row["adults"],
        children=row["children"],
        infants=row["infants"],
        trip_type=row["trip_type"],
        currency=row["currency"],
        status=ObservationStatus(row["status"]),
        attempts=row["attempts"],
        last_attempted_at=(
            _aware_datetime(row["last_attempted_at"])
            if row["last_attempted_at"] is not None
            else None
        ),
        next_retry_at=(
            _aware_datetime(row["next_retry_at"]) if row["next_retry_at"] is not None else None
        ),
        locked_at=_aware_datetime(row["locked_at"]) if row["locked_at"] is not None else None,
        locked_by=row["locked_by"],
        created_at=_aware_datetime(row["created_at"]),
        started_at=(_aware_datetime(row["started_at"]) if row["started_at"] is not None else None),
        waiting_since=(
            _aware_datetime(row["waiting_since"]) if row["waiting_since"] is not None else None
        ),
        operator_resume_requested_at=(
            _aware_datetime(row["operator_resume_requested_at"])
            if row["operator_resume_requested_at"] is not None
            else None
        ),
        operator_abort_requested_at=(
            _aware_datetime(row["operator_abort_requested_at"])
            if row["operator_abort_requested_at"] is not None
            else None
        ),
        completed_at=(
            _aware_datetime(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        expires_at=_aware_datetime(row["expires_at"]),
        error_code=(
            ObservationErrorCode(row["error_code"]) if row["error_code"] is not None else None
        ),
        error_message=row["error_message"],
    )


def _browser_observed_offer(row: RowMapping) -> BrowserObservedOffer:
    amount_minor = row["amount_minor"]
    currency = row["currency"]
    price = (
        Money(amount_minor, currency) if amount_minor is not None and currency is not None else None
    )
    return BrowserObservedOffer(
        observation_id=UUID(row["id"]),
        source_id=row["source_id"],
        source_name=row["source_name"],
        provider_offer_id=row["provider_offer_id"],
        origin=row["origin"],
        destination=row["destination"],
        departure_date=row["departure_date"],
        return_date=row["return_date"],
        total_price=price,
        passengers=row["passengers"],
        observed_at=_aware_datetime(row["observed_at"]),
        final_url=row["final_url"],
        display_url=row["display_url"],
        freshness=Freshness(row["freshness"]),
        confidence=Confidence(row["confidence"]),
        parser_version=row["parser_version"],
        parser_warnings=tuple(json.loads(row["parser_warnings_json"])),
        airline_name=row["airline_name"],
        airline_iata=row["airline_iata"],
        flight_number=row["flight_number"],
        departure_time_local=row["departure_time_local"],
        arrival_time_local=row["arrival_time_local"],
        duration_minutes=row["duration_minutes"],
        stops=row["stops"],
        baggage_summary=row["baggage_summary"],
        seller_name=row["seller_name"],
        requires_external_confirmation=row["requires_external_confirmation"],
    )


def _deal_candidate(row: RowMapping) -> DealCandidate:
    amount_minor = row["extracted_price_minor_units"]
    currency = row["currency"]
    price = (
        Money(amount_minor, currency) if amount_minor is not None and currency is not None else None
    )
    return DealCandidate(
        source_id=row["source_id"],
        url=row["discovered_url"],
        title=row["title"],
        summary_ru=row["summary"],
        extracted_price=price,
        extracted_origin=row["extracted_origin"],
        extracted_destination=row["extracted_destination"],
        extracted_date_window=row["extracted_departure_window"],
        confidence=Confidence(row["confidence"]),
        discovered_at=_aware_datetime(row["discovered_at"]),
        requires_manual_verification=row["requires_manual_verification"],
        expires_at=_aware_datetime(row["expires_at"]),
    )


def _deal_discovery_job_record(row: RowMapping) -> DealDiscoveryJobRecord:
    return DealDiscoveryJobRecord(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        search_id=row["search_id"],
        idempotency_key=row["idempotency_key"],
        status=row["status"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        next_retry_at=(
            _aware_datetime(row["next_retry_at"]) if row["next_retry_at"] is not None else None
        ),
        locked_at=_aware_datetime(row["locked_at"]) if row["locked_at"] is not None else None,
        locked_by=row["locked_by"],
        deadline_at=_aware_datetime(row["deadline_at"]),
        created_at=_aware_datetime(row["created_at"]),
        started_at=(_aware_datetime(row["started_at"]) if row["started_at"] is not None else None),
        completed_at=(
            _aware_datetime(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        search_intent_json=row["search_intent_json"],
        limit=row["limit"],
        result_count=row["result_count"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


def _manual_price_confirmation(row: RowMapping) -> ManualPriceConfirmation:
    amount_minor = row["amount_minor"]
    currency = row["currency"]
    price = (
        Money(amount_minor, currency) if amount_minor is not None and currency is not None else None
    )
    return ManualPriceConfirmation(
        id=UUID(row["id"]),
        household_id=UUID(row["household_id"]),
        user_id=UUID(row["user_id"]),
        target_kind=row["target_kind"],
        target_id=row["target_id"],
        source_id=row["source_id"],
        status=row["status"],
        confirmed_price=price,
        note=row["note"],
        confirmed_at=_aware_datetime(row["confirmed_at"]),
    )


def _alert_bucket(*, watch_id: str, itinerary_fingerprint: str, reason: str) -> str:
    return f"{watch_id}:{itinerary_fingerprint}:{reason}"


def _live_observation_dedupe_key(user_id: UUID, idempotency_key: str) -> str:
    return f"{user_id}:{idempotency_key}"


def _join_csv(values: tuple[str, ...]) -> str:
    return ",".join(value.strip() for value in values if value.strip())


def _split_csv(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _dump_airport_codes(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def _loads_airport_codes(value: str) -> tuple[str, ...]:
    payload = json.loads(value)
    if not isinstance(payload, list) or any(not isinstance(item, str) for item in payload):
        raise ValueError("watch airport-code snapshot must be a JSON string array")
    return tuple(payload)


def _loads_string_dict(value: str | None) -> dict[str, str]:
    if value is None or not value.strip():
        return {}
    payload = json.loads(value)
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(item) for key, item in payload.items()}


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


_CITY_ALIASES: dict[str, str] = {
    "варшав": "warsaw",
    "warszaw": "warsaw",
    "барсел": "barcelona",
    "краков": "krakow",
    "kraków": "krakow",
    "лодз": "lodz",
    "łodz": "lodz",
    "łódź": "lodz",
}
