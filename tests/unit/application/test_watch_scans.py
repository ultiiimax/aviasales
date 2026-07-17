from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.watch_scans import (
    WatchScanService,
    _intent_from_watch,
    _scan_idempotency_key,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.places import PlaceKind
from flight_hunter.domain.policy import DataKind, ExecutionContext, ProviderPolicy
from flight_hunter.notifications.alerts import AlertEvaluator
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AlertDedupeRepository,
    HouseholdWatchRepository,
    NewPriceSnapshot,
    NewWatch,
    PriceSnapshotRepository,
    SourceHealthEventRepository,
    WatchRecord,
    WatchScanJobRepository,
)
from flight_hunter.providers.fake import FakeFlightProvider

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
WATCH_ID = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def test_watch_record_carries_frozen_route_snapshot_fields() -> None:
    field_names = {field.name for field in fields(WatchRecord)}

    assert {
        "origin_kind",
        "destination_kind",
        "origin_airport_codes",
        "destination_airport_codes",
        "directory_version",
        "origin_membership_version",
        "destination_membership_version",
    } <= field_names


def test_watch_scan_intent_restores_airport_kind_and_frozen_snapshot() -> None:
    watch = cast(
        WatchRecord,
        SimpleNamespace(
            origin="DME",
            destination="PAR",
            departure_date="2026-10-12",
            return_date=None,
            passengers=1,
            currency="RUB",
            origin_kind=PlaceKind.AIRPORT,
            destination_kind=PlaceKind.CITY,
            origin_airport_codes=("DME",),
            destination_airport_codes=("BVA", "CDG", "ORY"),
            directory_version="directory-v1",
            origin_membership_version="airport-dme-v1",
            destination_membership_version="par-2026-07-17",
        ),
    )

    intent = _intent_from_watch(watch)

    assert intent.origin_kind is PlaceKind.AIRPORT
    assert intent.destination_kind is PlaceKind.CITY
    assert intent.origin_airport_codes == ("DME",)
    assert intent.destination_airport_codes == ("BVA", "CDG", "ORY")
    assert intent.directory_version == "directory-v1"
    assert intent.origin_membership_version == "airport-dme-v1"
    assert intent.destination_membership_version == "par-2026-07-17"


def test_watch_scan_idempotency_key_includes_frozen_route_snapshot() -> None:
    baseline = cast(
        WatchRecord,
        SimpleNamespace(
            id=WATCH_ID,
            next_eligible_at=NOW,
            origin="MOW",
            destination="PAR",
            origin_kind=PlaceKind.CITY,
            destination_kind=PlaceKind.CITY,
            origin_airport_codes=("DME", "SVO", "VKO", "ZIA"),
            destination_airport_codes=("BVA", "CDG", "ORY"),
            directory_version="directory-v1",
            origin_membership_version="mow-v1",
            destination_membership_version="par-v1",
        ),
    )
    changed_membership = cast(
        WatchRecord,
        SimpleNamespace(
            **{
                **vars(baseline),
                "origin_airport_codes": ("DME", "SVO", "VKO"),
                "origin_membership_version": "mow-v2",
            }
        ),
    )

    assert _scan_idempotency_key(baseline) != _scan_idempotency_key(changed_membership)


@pytest.mark.anyio
async def test_watch_scan_persists_snapshot_and_advances_schedule() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await HouseholdWatchRepository(session).add_watch(_watch())
        service = _service(
            session,
            providers={"fake": FakeFlightProvider(clock=lambda: NOW)},
        )

        summary = await service.run_once(
            due_limit=5,
            job_limit=5,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            job_deadline=timedelta(minutes=5),
            worker_id="test-worker",
        )

        history = await PriceSnapshotRepository(session).list_history(HOUSEHOLD_ID, WATCH_ID)
        watch = await HouseholdWatchRepository(session).get_watch(HOUSEHOLD_ID, WATCH_ID)

    assert summary.due_watches_seen == 1
    assert summary.jobs_enqueued == 1
    assert summary.jobs_processed == 1
    assert summary.jobs_succeeded == 1
    assert summary.snapshots_saved == 1
    assert history[0].provider_id == "fake"
    assert history[0].freshness == Freshness.CACHED
    assert watch is not None
    assert watch.last_scan_status == "succeeded"
    assert watch.next_eligible_at == NOW + timedelta(hours=1)


@pytest.mark.anyio
async def test_watch_scan_never_calls_user_action_provider() -> None:
    session_factory = await _session_factory()
    unsafe_provider = RecordingProvider(
        policy=ProviderPolicy.aviasales_search(
            terms_verified_at=NOW,
            credentials_present=True,
            access_approved=True,
            enabled=True,
        ),
        offers=(),
    )
    async with session_factory() as session:
        await HouseholdWatchRepository(session).add_watch(
            _watch(allowed_provider_ids=("aviasales_search",))
        )
        service = _service(session, providers={"aviasales_search": unsafe_provider})

        summary = await service.run_once(
            due_limit=5,
            job_limit=5,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            job_deadline=timedelta(minutes=5),
            worker_id="test-worker",
        )
        watch = await HouseholdWatchRepository(session).get_watch(HOUSEHOLD_ID, WATCH_ID)
        health = await SourceHealthEventRepository(session).list_recent(
            source_id=f"watch:{WATCH_ID}"
        )

    assert unsafe_provider.calls == 0
    assert summary.jobs_enqueued == 0
    assert summary.watches_skipped == 1
    assert watch is not None
    assert watch.last_scan_status == "skipped"
    assert watch.last_scan_error_code == "user_action_required"
    assert health[0].status == "skipped"


@pytest.mark.anyio
async def test_watch_scan_retry_does_not_duplicate_snapshot_or_alert() -> None:
    session_factory = await _session_factory()
    drop_provider = RecordingProvider(
        policy=_provider_policy("drop"),
        offers=(
            _offer(
                provider_id="drop",
                provider_offer_id="route-1",
                amount_minor=88_000,
            ),
        ),
    )
    flaky_provider = FailingProvider(policy=_provider_policy("flaky"))
    outbox = RecordingOutbox()
    async with session_factory() as session:
        await HouseholdWatchRepository(session).add_watch(
            _watch(allowed_provider_ids=("drop", "flaky"))
        )
        await PriceSnapshotRepository(session).add_snapshot(
            NewPriceSnapshot(
                id=UUID("33333333-3333-3333-3333-333333333333"),
                household_id=HOUSEHOLD_ID,
                watch_id=WATCH_ID,
                provider_id="drop",
                itinerary_fingerprint=_fingerprint("drop", "route-1"),
                observed_at=NOW - timedelta(hours=1),
                price=Money(100_000, "RUB"),
                freshness=Freshness.CACHED,
                requires_live_confirmation=True,
            )
        )
        service = _service(
            session,
            providers={"drop": drop_provider, "flaky": flaky_provider},
            telegram_outbox=outbox,
        )

        first = await service.run_once(
            due_limit=5,
            job_limit=5,
            max_attempts=2,
            retry_delay=timedelta(0),
            job_deadline=timedelta(minutes=5),
            worker_id="test-worker",
        )
        second = await service.run_once(
            due_limit=5,
            job_limit=5,
            max_attempts=2,
            retry_delay=timedelta(0),
            job_deadline=timedelta(minutes=5),
            worker_id="test-worker",
        )
        history = await PriceSnapshotRepository(session).list_history(HOUSEHOLD_ID, WATCH_ID)
        alert_state = await AlertDedupeRepository(session).load_state(HOUSEHOLD_ID, WATCH_ID)

    assert first.snapshots_saved == 1
    assert first.alerts_recorded == 1
    assert first.jobs_retry_scheduled == 1
    assert second.jobs_already_queued == 1
    assert second.snapshots_saved == 0
    assert second.alerts_recorded == 0
    assert first.telegram_notifications_enqueued == 1
    assert second.telegram_notifications_enqueued == 0
    assert outbox.enqueued == [USER_ID]
    assert second.jobs_failed == 1
    assert len(history) == 2
    assert len(alert_state.sent_dedupe_keys) == 1


class RecordingProvider:
    def __init__(self, *, policy: ProviderPolicy, offers: tuple[FlightOffer, ...]) -> None:
        self.policy = policy
        self.offers = offers
        self.calls = 0

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        self.calls += 1
        return self.offers


class FailingProvider:
    def __init__(self, *, policy: ProviderPolicy) -> None:
        self.policy = policy

    def search(
        self,
        intent: SearchIntent,
        *,
        request_fingerprint: str,
        context: ExecutionContext,
    ) -> tuple[FlightOffer, ...]:
        raise RuntimeError("sanitized provider failure")


class RecordingOutbox:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    async def enqueue_price_alert(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        alert,
    ) -> bool:
        self.enqueued.append(user_id)
        return True


def _service(
    session,
    *,
    providers,
    telegram_outbox=None,
) -> WatchScanService:
    return WatchScanService(
        watches=HouseholdWatchRepository(session),
        jobs=WatchScanJobRepository(session),
        snapshots=PriceSnapshotRepository(session),
        alert_dedupe=AlertDedupeRepository(session),
        source_health_events=SourceHealthEventRepository(session),
        providers=providers,
        alert_evaluator=AlertEvaluator(
            drop_threshold_percent=10,
            cooldown=timedelta(hours=6),
        ),
        telegram_outbox=telegram_outbox,
        clock=lambda: NOW,
    )


def _watch(*, allowed_provider_ids: tuple[str, ...] = ()) -> NewWatch:
    return NewWatch(
        id=WATCH_ID,
        household_id=HOUSEHOLD_ID,
        owner_user_id=USER_ID,
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date="2026-10-19",
        created_at=NOW - timedelta(hours=1),
        passengers=1,
        currency="RUB",
        next_eligible_at=NOW - timedelta(minutes=1),
        scan_interval_seconds=3600,
        allowed_provider_ids=allowed_provider_ids,
    )


def _offer(
    *,
    provider_id: str,
    provider_offer_id: str,
    amount_minor: int,
) -> FlightOffer:
    return FlightOffer(
        provider_id=provider_id,
        provider_offer_id=provider_offer_id,
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date="2026-10-19",
        total_price=Money(amount_minor, "RUB"),
        passengers=1,
        observed_at=NOW,
        freshness=Freshness.CACHED,
        requires_live_confirmation=True,
        baggage_summary=None,
    )


def _fingerprint(provider_id: str, provider_offer_id: str) -> str:
    return f"{provider_id}|{provider_offer_id}|WAW|BCN|2026-10-12|2026-10-19|1|RUB"


def _provider_policy(provider_id: str) -> ProviderPolicy:
    return ProviderPolicy(
        provider_id=provider_id,
        policy_version="2026-06-29",
        terms_url="https://example.test/provider",
        terms_verified_at=NOW,
        enabled=True,
        credentials_present=True,
        access_approved=True,
        data_kind=DataKind.CACHED,
        background_requests_allowed=True,
        user_action_required=False,
        merge_with_other_sources_allowed=True,
        persist_raw_results_allowed=False,
        persist_normalized_results_allowed=True,
        booking_link_requires_click=True,
        preload_booking_links_allowed=False,
        server_side_only=True,
        real_user_ip_required=False,
        max_requests_per_minute=10,
        max_requests_per_hour_per_user_ip=None,
        cache_ttl_seconds=3600,
        result_ttl_seconds=86_400,
        max_concurrent_requests=1,
        supports_flexible_dates=False,
        supports_nearby_airports=False,
        supports_multi_city=False,
        supports_one_way=True,
        supports_round_trip=True,
        supports_baggage=False,
        supports_fare_rules=False,
        notes="test provider",
    )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
