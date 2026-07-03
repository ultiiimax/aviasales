from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import anyio
import httpx2
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.telegram_notifications import (
    TelegramBotApiTransport,
    TelegramLinkService,
    TelegramNotificationService,
    TelegramQuietHours,
)
from flight_hunter.domain.money import Money
from flight_hunter.notifications.alerts import AlertReason, PriceAlert
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    NewTelegramNotification,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
WATCH_ID = "22222222-2222-2222-2222-222222222222"
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_telegram_link_code_is_one_time_and_not_username_based() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        links = TelegramLinkRepository(session)
        service = TelegramLinkService(
            repository=links,
            clock=lambda: NOW,
            code_factory=lambda: "ABC123",
        )
        created = await service.create_link_code(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            ttl=timedelta(minutes=5),
        )
        consumed = await service.consume_link_code(
            code=created.code,
            telegram_user_id=12345,
            chat_id=98765,
        )
        replay = await service.consume_link_code(
            code=created.code,
            telegram_user_id=12345,
            chat_id=98765,
        )

    assert created.expires_at == NOW + timedelta(minutes=5)
    assert consumed.accepted
    assert consumed.account is not None
    assert consumed.account.user_id == USER_ID
    assert consumed.account.telegram_user_id == 12345
    assert consumed.account.chat_id == 98765
    assert not replay.accepted
    assert replay.code == "link_code_invalid_or_expired"


@pytest.mark.anyio
async def test_price_alert_without_link_creates_blocked_outbox_row_once() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        service = _notification_service(session)

        first = await service.enqueue_price_alert(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            alert=_alert(),
        )
        second = await service.enqueue_price_alert(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            alert=_alert(),
        )
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_ID)

    assert first
    assert not second
    assert len(rows) == 1
    assert rows[0].status == "blocked"
    assert rows[0].chat_id is None
    assert rows[0].error_code == "telegram_link_missing"


@pytest.mark.anyio
async def test_linked_price_alert_is_delivered_once(caplog) -> None:
    caplog.set_level(logging.INFO, logger="flight_hunter.observability")
    session_factory = await _session_factory()
    transport = RecordingTransport()
    async with session_factory() as session:
        await _link_user(session)
        service = _notification_service(session, transport=transport)
        await service.enqueue_price_alert(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            alert=_alert(),
        )

        summary = await service.deliver_due(
            limit=10,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            worker_id="worker-a",
        )
        replay = await service.deliver_due(
            limit=10,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            worker_id="worker-b",
        )
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_ID)

    assert summary.notifications_seen == 1
    assert summary.sent == 1
    assert replay.notifications_seen == 0
    assert transport.messages == [(98765, "Flight Hunter price drop alert")]
    assert rows[0].status == "sent"
    assert rows[0].sent_at == NOW
    assert rows[0].locked_at is None
    assert rows[0].locked_by is None
    payload = _logged_event(caplog, "alert_sent")
    assert payload["watch_id"] == str(WATCH_ID)
    assert payload["reason"] == "price_drop"
    assert payload["notification_id"] == str(rows[0].id)
    assert payload["household_id"] == str(HOUSEHOLD_ID)
    assert payload["attempt"] == 1
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "98765" not in log_text
    assert "Flight Hunter price drop alert" not in log_text


@pytest.mark.anyio
async def test_quiet_hours_defer_delivery_without_transport_call(caplog) -> None:
    caplog.set_level(logging.INFO, logger="flight_hunter.observability")
    session_factory = await _session_factory()
    quiet_now = datetime(2026, 6, 29, 23, 30, tzinfo=UTC)
    transport = RecordingTransport()
    async with session_factory() as session:
        await _link_user(session, now=quiet_now)
        service = _notification_service(session, transport=transport, now=quiet_now)
        await service.enqueue_price_alert(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            alert=_alert(observed_at=quiet_now),
        )

        summary = await service.deliver_due(
            limit=10,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            quiet_hours=TelegramQuietHours(start=time(23, 0), end=time(8, 0)),
        )
        rows = await TelegramNotificationOutboxRepository(session).list_by_user(USER_ID)

    assert summary.deferred_quiet_hours == 1
    assert transport.messages == []
    assert _logged_events(caplog, "alert_sent") == []
    assert rows[0].status == "retry_scheduled"
    assert rows[0].attempts == 0
    assert rows[0].next_retry_at == datetime(2026, 6, 30, 8, 0, tzinfo=UTC)
    assert rows[0].locked_at is None
    assert rows[0].locked_by is None


@pytest.mark.anyio
async def test_command_reply_outbox_message_delivers_payload_text() -> None:
    session_factory = await _session_factory()
    transport = RecordingTransport()
    async with session_factory() as session:
        repository = TelegramNotificationOutboxRepository(session)
        await repository.enqueue(
            NewTelegramNotification(
                id=UUID("44444444-4444-4444-4444-444444444444"),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                chat_id=98765,
                kind="command_reply",
                dedupe_key="telegram:command:watches:1",
                payload_json='{"text": "Flight Hunter watches\\n1. WAW -> BCN"}',
                status="queued",
                attempts=0,
                created_at=NOW,
            )
        )
        service = _notification_service(session, transport=transport)

        summary = await service.deliver_due(
            limit=10,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
        )

    assert summary.sent == 1
    assert transport.messages == [(98765, "Flight Hunter watches")]


@pytest.mark.anyio
async def test_callback_ack_outbox_uses_answer_callback_query_without_chat_or_quiet_hours() -> None:
    session_factory = await _session_factory()
    transport = RecordingTransport()
    async with session_factory() as session:
        repository = TelegramNotificationOutboxRepository(session)
        await repository.enqueue(
            NewTelegramNotification(
                id=UUID("55555555-5555-5555-5555-555555555555"),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                chat_id=None,
                kind="callback_ack",
                dedupe_key="telegram:callback:9001",
                payload_json=(
                    '{"callback_query_id": "callback-9001", '
                    '"text": "Manual browser check queued.", '
                    '"show_alert": false}'
                ),
                status="queued",
                attempts=0,
                created_at=NOW,
            )
        )
        service = _notification_service(session, transport=transport)

        summary = await service.deliver_due(
            limit=10,
            max_attempts=3,
            retry_delay=timedelta(minutes=1),
            quiet_hours=TelegramQuietHours(start=time(0, 0), end=time(23, 59)),
        )
        rows = await repository.list_by_user(USER_ID)

    assert summary.sent == 1
    assert transport.messages == []
    assert transport.callback_answers == [("callback-9001", "Manual browser check queued.", False)]
    assert rows[0].status == "sent"
    assert rows[0].sent_at == NOW


def test_telegram_bot_api_transport_answers_callback_query_without_callback_data() -> None:
    captured_request: httpx2.Request | None = None

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal captured_request
        captured_request = request
        return httpx2.Response(200, json={"ok": True, "result": True})

    transport = TelegramBotApiTransport(
        token="telegram-token",
        http_client=httpx2.Client(
            transport=httpx2.MockTransport(handler),
            base_url="https://api.telegram.org/bottelegram-token",
        ),
    )

    async def answer() -> None:
        await transport.answer_callback_query(
            callback_query_id="callback-1",
            text="x" * 250,
            show_alert=True,
        )

    anyio.run(answer)

    assert captured_request is not None
    assert captured_request.url.path == "/bottelegram-token/answerCallbackQuery"
    payload = captured_request.read().decode()
    assert "callback-1" in payload
    assert "show_alert" in payload
    assert "callback_data" not in payload
    assert "x" * 201 not in payload


@pytest.mark.anyio
async def test_telegram_outbox_recovers_stale_sending_notification_without_attempt_increment() -> (
    None
):
    session_factory = await _session_factory()
    old_lock = NOW - timedelta(minutes=30)
    notification_id = UUID("33333333-3333-3333-3333-333333333333")
    async with session_factory() as session:
        repository = TelegramNotificationOutboxRepository(session)
        await repository.enqueue(
            NewTelegramNotification(
                id=notification_id,
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                chat_id=98765,
                kind="price_drop",
                dedupe_key="telegram:stale",
                payload_json="{}",
                status="queued",
                attempts=0,
                created_at=old_lock,
            )
        )
        await repository.claim_due(now=old_lock, limit=10, worker_id="worker-a")
        recovered = await repository.recover_stale_sending(
            now=NOW,
            stale_before=NOW - timedelta(minutes=15),
            limit=10,
        )
        rows = await repository.list_by_user(USER_ID)

    assert recovered == 1
    assert rows[0].status == "retry_scheduled"
    assert rows[0].attempts == 0
    assert rows[0].next_retry_at == NOW
    assert rows[0].locked_at is None
    assert rows[0].locked_by is None
    assert rows[0].error_code == "worker_lease_expired"


class RecordingTransport:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.reply_markups: list[dict[str, object] | None] = []
        self.callback_answers: list[tuple[str, str | None, bool]] = []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        first_line = text.splitlines()[0]
        self.messages.append((chat_id, first_line))
        self.reply_markups.append(reply_markup)

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        self.callback_answers.append((callback_query_id, text, show_alert))


def _notification_service(
    session,
    *,
    transport: RecordingTransport | None = None,
    now: datetime = NOW,
) -> TelegramNotificationService:
    return TelegramNotificationService(
        links=TelegramLinkRepository(session),
        outbox=TelegramNotificationOutboxRepository(session),
        transport=transport,
        clock=lambda: now,
    )


async def _link_user(session, *, now: datetime = NOW) -> None:
    service = TelegramLinkService(
        repository=TelegramLinkRepository(session),
        clock=lambda: now,
        code_factory=lambda: "LINKME",
    )
    created = await service.create_link_code(
        household_id=HOUSEHOLD_ID,
        user_id=USER_ID,
        ttl=timedelta(minutes=5),
    )
    await service.consume_link_code(
        code=created.code,
        telegram_user_id=12345,
        chat_id=98765,
    )


def _alert(*, observed_at: datetime = NOW) -> PriceAlert:
    return PriceAlert(
        watch_id=WATCH_ID,
        itinerary_fingerprint="route-1",
        reason=AlertReason.PRICE_DROP,
        observed_at=observed_at,
        previous_price=Money(100_000, "RUB"),
        current_price=Money(88_000, "RUB"),
        drop_percent=12,
        dedupe_key="watch:route-1:price_drop:88000",
    )


def _logged_event(caplog, event: str) -> dict[str, object]:
    events = _logged_events(caplog, event)
    if not events:
        raise AssertionError(f"missing structured log event {event}")
    return events[0]


def _logged_events(caplog, event: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for record in caplog.records:
        if record.name != "flight_hunter.observability":
            continue
        payload = json.loads(record.getMessage())
        if payload.get("event") == event:
            payloads.append(payload)
    return payloads


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
