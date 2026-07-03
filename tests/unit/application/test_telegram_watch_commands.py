from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.personal_observations import PersonalObservationService
from flight_hunter.application.telegram_notifications import (
    TelegramLinkService,
    TelegramWatchCommandService,
)
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    BrowserObservedOfferRepository,
    HouseholdWatchRepository,
    LiveObservationRepository,
    NewWatch,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
)

HOUSEHOLD_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_B = UUID("bbbbbbbb-0000-0000-0000-000000000001")
WATCH_A = UUID("11111111-1111-1111-1111-111111111111")
WATCH_B = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_watches_command_enqueues_scoped_watch_list_for_linked_user() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await _link_user(session, household_id=HOUSEHOLD_A, user_id=USER_A)
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date="2026-10-19",
                created_at=NOW,
            )
        )
        await watches.add_watch(
            NewWatch(
                id=WATCH_B,
                household_id=HOUSEHOLD_B,
                owner_user_id=USER_B,
                origin="WAW",
                destination="NRT",
                departure_date="2026-11-02",
                return_date=None,
                created_at=NOW,
            )
        )
        service = _command_service(session)

        result = await service.handle_watches_command(telegram_user_id=12345, update_id=3003)
        duplicate = await service.handle_watches_command(telegram_user_id=12345, update_id=3003)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_A)

    assert result == "queued"
    assert duplicate == "duplicate"
    assert len(rows) == 1
    assert rows[0].kind == "command_reply"
    assert rows[0].dedupe_key == "telegram:command:watches:3003"
    payload = json.loads(rows[0].payload_json)
    assert payload["command"] == "watches"
    assert "WAW -> BCN" in payload["text"]
    assert "NRT" not in payload["text"]
    assert payload["reply_markup"] == {
        "inline_keyboard": [
            [
                {"text": "Pause #1", "callback_data": f"fh:w:p:{WATCH_A}:1"},
                {"text": "Resume #1", "callback_data": f"fh:w:r:{WATCH_A}:1"},
                {"text": "Check #1", "callback_data": f"fh:w:c:{WATCH_A}:1:tutu"},
            ]
        ]
    }


@pytest.mark.anyio
async def test_watches_command_for_unlinked_user_does_not_enqueue_reply() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        result = await _command_service(session).handle_watches_command(
            telegram_user_id=99999,
            update_id=4004,
        )
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_A)

    assert result == "unlinked"
    assert rows == ()


@pytest.mark.anyio
async def test_pause_callback_checks_owner_and_expected_version() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await _link_user(session, household_id=HOUSEHOLD_A, user_id=USER_A)
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        service = _command_service(session)

        result = await service.handle_watch_callback(
            telegram_user_id=12345,
            callback_query_id="callback-5005",
            callback_data=f"fh:w:p:{WATCH_A}:1",
            update_id=5005,
        )
        duplicate = await service.handle_watch_callback(
            telegram_user_id=12345,
            callback_query_id="callback-5005",
            callback_data=f"fh:w:p:{WATCH_A}:1",
            update_id=5005,
        )
        watch = await watches.get_watch(HOUSEHOLD_A, WATCH_A)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_A)

    assert result == "queued"
    assert duplicate == "duplicate"
    assert watch is not None
    assert watch.paused_until == NOW + timedelta(hours=24)
    assert watch.next_eligible_at == NOW + timedelta(hours=24)
    assert watch.version == 2
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-5005"
    assert "callback_data" not in payload
    assert payload["text"] == "Watch WAW -> BCN paused for 24 hours. Version: 2."


@pytest.mark.anyio
async def test_check_callback_queues_personal_observation_from_real_callback() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await _link_user(session, household_id=HOUSEHOLD_A, user_id=USER_A)
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        service = _command_service(session, personal_observer_enabled=True)

        result = await service.handle_watch_callback(
            telegram_user_id=12345,
            callback_query_id="callback-8008",
            callback_data=f"fh:w:c:{WATCH_A}:1:tutu",
            update_id=8008,
        )
        duplicate = await service.handle_watch_callback(
            telegram_user_id=12345,
            callback_query_id="callback-8008",
            callback_data=f"fh:w:c:{WATCH_A}:1:tutu",
            update_id=8008,
        )
        watch = await watches.get_watch(HOUSEHOLD_A, WATCH_A)
        jobs = await BrowserObservationJobRepository(session).list_queued(now=NOW)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_A)
        grant = await LiveObservationRepository(session).get_grant(USER_A, jobs[0].grant_id)

    assert result == "queued"
    assert duplicate == "duplicate"
    assert watch is not None
    assert watch.version == 1
    assert len(jobs) == 1
    assert jobs[0].status == ObservationStatus.QUEUED
    assert jobs[0].source_id == "tutu"
    assert jobs[0].search_id == f"telegram-watch:{WATCH_A}:v1"
    assert jobs[0].origin == "WAW"
    assert jobs[0].destination == "BCN"
    assert jobs[0].passengers == 1
    assert grant is not None
    assert grant.source == "telegram_callback"
    assert grant.consumed_at == NOW
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-8008"
    assert "callback_data" not in payload
    assert payload["text"].startswith("Manual browser check queued for WAW -> BCN on tutu.")
    assert str(grant.id) not in payload["text"]


@pytest.mark.anyio
async def test_resume_callback_rejects_stale_version_without_mutating_watch() -> None:
    session_factory = await _session_factory()
    paused_until = NOW + timedelta(hours=24)
    async with session_factory() as session:
        await _link_user(session, household_id=HOUSEHOLD_A, user_id=USER_A)
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
                paused_until=paused_until,
                next_eligible_at=paused_until,
            )
        )
        await watches.update_watch(
            household_id=HOUSEHOLD_A,
            watch_id=WATCH_A,
            expected_version=1,
            updated_at=NOW,
            updates={"enabled": True},
        )
        service = _command_service(session)

        result = await service.handle_watch_callback(
            telegram_user_id=12345,
            callback_query_id="callback-6006",
            callback_data=f"fh:w:r:{WATCH_A}:1",
            update_id=6006,
        )
        watch = await watches.get_watch(HOUSEHOLD_A, WATCH_A)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_A)

    assert result == "version_conflict"
    assert watch is not None
    assert watch.paused_until == paused_until
    assert watch.version == 2
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-6006"
    assert payload["text"] == "Watch changed in another place. Open /watches and try again."


@pytest.mark.anyio
async def test_callback_from_other_household_cannot_control_watch() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await _link_user(
            session,
            household_id=HOUSEHOLD_B,
            user_id=USER_B,
            telegram_user_id=22222,
            chat_id=222220,
        )
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        service = _command_service(session)

        result = await service.handle_watch_callback(
            telegram_user_id=22222,
            callback_query_id="callback-7007",
            callback_data=f"fh:w:p:{WATCH_A}:1",
            update_id=7007,
        )
        watch = await watches.get_watch(HOUSEHOLD_A, WATCH_A)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_B)

    assert result == "not_found"
    assert watch is not None
    assert watch.paused_until is None
    assert watch.version == 1
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-7007"
    assert payload["text"] == "Watch not found or access denied."


@pytest.mark.anyio
async def test_check_callback_from_other_household_cannot_queue_observation() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        await _link_user(
            session,
            household_id=HOUSEHOLD_B,
            user_id=USER_B,
            telegram_user_id=22222,
            chat_id=222220,
        )
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=HOUSEHOLD_A,
                owner_user_id=USER_A,
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        service = _command_service(session, personal_observer_enabled=True)

        result = await service.handle_watch_callback(
            telegram_user_id=22222,
            callback_query_id="callback-9009",
            callback_data=f"fh:w:c:{WATCH_A}:1:tutu",
            update_id=9009,
        )
        jobs = await BrowserObservationJobRepository(session).list_queued(now=NOW)
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_B)

    assert result == "not_found"
    assert jobs == ()
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-9009"
    assert payload["text"] == "Watch not found or access denied."


async def _link_user(
    session,
    *,
    household_id: UUID,
    user_id: UUID,
    telegram_user_id: int = 12345,
    chat_id: int = 98765,
) -> None:
    service = TelegramLinkService(
        repository=TelegramLinkRepository(session),
        clock=lambda: NOW,
        code_factory=lambda: "LINKME",
    )
    created = await service.create_link_code(
        household_id=household_id,
        user_id=user_id,
        ttl=timedelta(minutes=5),
    )
    await service.consume_link_code(
        code=created.code,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
    )


def _command_service(
    session,
    *,
    personal_observer_enabled: bool = False,
) -> TelegramWatchCommandService:
    personal_observation_service = None
    if personal_observer_enabled:
        personal_observation_service = PersonalObservationService(
            jobs=BrowserObservationJobRepository(session),
            grants=LiveObservationRepository(session),
            observed_offers=BrowserObservedOfferRepository(session),
            observer_enabled=True,
            clock=lambda: NOW,
        )
    return TelegramWatchCommandService(
        links=TelegramLinkRepository(session),
        watches=HouseholdWatchRepository(session),
        outbox=TelegramNotificationOutboxRepository(session),
        personal_observation_service=personal_observation_service,
        clock=lambda: NOW,
        id_factory=lambda: UUID("33333333-3333-3333-3333-333333333333"),
    )


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
