from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

import httpx2

from flight_hunter.application.live_observations import GrantSource
from flight_hunter.application.personal_observations import (
    PersonalObservationService,
)
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.notifications.alerts import PriceAlert
from flight_hunter.ops.structured_logging import log_event
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    HouseholdWatchRepository,
    NewAuditEvent,
    NewTelegramLinkCode,
    NewTelegramNotification,
    TelegramAccountRecord,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
    TelegramNotificationRecord,
    WatchRecord,
)


class TelegramTransport(Protocol):
    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None: ...

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None: ...


class TelegramBotApiTransport:
    def __init__(self, *, token: str, http_client: httpx2.Client | None = None) -> None:
        if not token:
            raise ValueError("token is required")
        self._client = http_client or httpx2.Client(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=10.0,
        )

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        def send() -> None:
            payload: dict[str, object] = {"chat_id": chat_id, "text": text}
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup
            response = self._client.post(
                "/sendMessage",
                json=payload,
            )
            if response.status_code >= 400:
                raise RuntimeError("telegram_http_error")
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError("telegram_unsuccessful_response")

        await asyncio.to_thread(send)

    async def answer_callback_query(
        self,
        *,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        if not callback_query_id:
            raise ValueError("callback_query_id is required")

        def answer() -> None:
            payload: dict[str, object] = {
                "callback_query_id": callback_query_id,
                "show_alert": show_alert,
            }
            if text is not None:
                payload["text"] = text[:200]
            response = self._client.post(
                "/answerCallbackQuery",
                json=payload,
            )
            if response.status_code >= 400:
                raise RuntimeError("telegram_http_error")
            response_payload = response.json()
            if not isinstance(response_payload, dict) or response_payload.get("ok") is not True:
                raise RuntimeError("telegram_unsuccessful_response")

        await asyncio.to_thread(answer)


@dataclass(frozen=True, slots=True)
class TelegramLinkCodeResult:
    code: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TelegramConsumeLinkResult:
    accepted: bool
    code: str
    account: TelegramAccountRecord | None


@dataclass(frozen=True, slots=True)
class TelegramQuietHours:
    start: time
    end: time

    def contains(self, value: datetime) -> bool:
        current = value.timetz().replace(tzinfo=None)
        if self.start <= self.end:
            return self.start <= current < self.end
        return current >= self.start or current < self.end

    def next_allowed_at(self, value: datetime) -> datetime:
        if not self.contains(value):
            return value
        end_at = value.replace(
            hour=self.end.hour,
            minute=self.end.minute,
            second=0,
            microsecond=0,
        )
        if end_at <= value:
            end_at += timedelta(days=1)
        return end_at


@dataclass(frozen=True, slots=True)
class TelegramDeliverySummary:
    notifications_seen: int = 0
    sent: int = 0
    retry_scheduled: int = 0
    failed: int = 0
    deferred_quiet_hours: int = 0


TelegramWatchCommandResult = Literal["queued", "duplicate", "unlinked"]
TelegramWatchCallbackAction = Literal["pause", "resume", "check"]
TelegramWatchCallbackResult = Literal[
    "queued",
    "duplicate",
    "unlinked",
    "invalid_callback",
    "not_found",
    "version_conflict",
    "observation_unavailable",
]


class TelegramLinkService:
    def __init__(
        self,
        *,
        repository: TelegramLinkRepository,
        clock: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._code_factory = code_factory or _default_code

    async def create_link_code(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        ttl: timedelta,
    ) -> TelegramLinkCodeResult:
        now = self._clock()
        code = self._code_factory()
        expires_at = now + ttl
        await self._repository.add_code(
            NewTelegramLinkCode(
                code=code,
                household_id=household_id,
                user_id=user_id,
                created_at=now,
                expires_at=expires_at,
            )
        )
        return TelegramLinkCodeResult(code=code, expires_at=expires_at)

    async def consume_link_code(
        self,
        *,
        code: str,
        telegram_user_id: int,
        chat_id: int,
    ) -> TelegramConsumeLinkResult:
        account = await self._repository.consume_code(
            code=code,
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
            now=self._clock(),
        )
        if account is None:
            return TelegramConsumeLinkResult(
                accepted=False,
                code="link_code_invalid_or_expired",
                account=None,
            )
        return TelegramConsumeLinkResult(accepted=True, code="linked", account=account)


class TelegramWatchCommandService:
    def __init__(
        self,
        *,
        links: TelegramLinkRepository,
        watches: HouseholdWatchRepository,
        outbox: TelegramNotificationOutboxRepository,
        audit_repository: AuditEventRepository | None = None,
        personal_observation_service: PersonalObservationService | None = None,
        observation_source_id: str = "tutu",
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._links = links
        self._watches = watches
        self._outbox = outbox
        self._audit_repository = audit_repository
        self._personal_observation_service = personal_observation_service
        self._observation_source_id = observation_source_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    async def handle_watches_command(
        self,
        *,
        telegram_user_id: int,
        update_id: int,
    ) -> TelegramWatchCommandResult:
        account = await self._links.get_account_for_telegram_user(telegram_user_id)
        if account is None:
            return "unlinked"
        watches = await self._watches.list_watches(account.household_id)
        payload = {
            "kind": "command_reply",
            "command": "watches",
            "text": _watches_command_text(watches),
            "reply_markup": _watches_reply_markup(
                watches,
                observation_source_id=self._observation_source_id,
            ),
        }
        queued = await self._outbox.enqueue(
            NewTelegramNotification(
                id=self._id_factory(),
                household_id=account.household_id,
                user_id=account.user_id,
                chat_id=account.chat_id,
                kind="command_reply",
                dedupe_key=f"telegram:command:watches:{update_id}",
                payload_json=json.dumps(payload, sort_keys=True),
                status="queued",
                attempts=0,
                created_at=self._clock(),
            )
        )
        return "queued" if queued else "duplicate"

    async def handle_watch_callback(
        self,
        *,
        telegram_user_id: int,
        callback_query_id: str,
        callback_data: str,
        update_id: int,
    ) -> TelegramWatchCallbackResult:
        parsed = _parse_watch_callback_data(callback_data)
        if parsed is None:
            return "invalid_callback"
        action, watch_id, expected_version, source_id = parsed
        dedupe_key = f"telegram:callback:{update_id}"
        if await self._outbox.has_dedupe_key(dedupe_key):
            return "duplicate"

        account = await self._links.get_account_for_telegram_user(telegram_user_id)
        if account is None:
            return "unlinked"

        now = self._clock()
        if action == "check":
            return await self._handle_watch_check_callback(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                watch_id=watch_id,
                expected_version=expected_version,
                source_id=source_id,
                update_id=update_id,
                created_at=now,
            )

        if action == "pause":
            paused_until = now + timedelta(hours=24)
            result = await self._watches.update_watch(
                household_id=account.household_id,
                watch_id=watch_id,
                expected_version=expected_version,
                updated_at=now,
                updates={
                    "enabled": True,
                    "paused_until": paused_until,
                    "next_eligible_at": paused_until,
                },
            )
        else:
            result = await self._watches.update_watch(
                household_id=account.household_id,
                watch_id=watch_id,
                expected_version=expected_version,
                updated_at=now,
                updates={
                    "enabled": True,
                    "paused_until": None,
                    "next_eligible_at": now,
                },
            )

        if result.status == "not_found":
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Watch not found or access denied.",
                created_at=now,
            )
            return "not_found"
        if result.status == "version_conflict":
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Watch changed in another place. Open /watches and try again.",
                created_at=now,
            )
            return "version_conflict"
        if result.watch is None:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Watch not found or access denied.",
                created_at=now,
            )
            return "not_found"

        await self._record_watch_audit(
            account=account,
            watch_id=watch_id,
            action=f"watch.{action}d" if action == "pause" else "watch.resumed",
            created_at=now,
        )
        text = _watch_callback_success_text(result.watch, action=action)
        queued = await self._enqueue_callback_ack(
            account=account,
            dedupe_key=dedupe_key,
            callback_query_id=callback_query_id,
            text=text,
            created_at=now,
        )
        return "queued" if queued else "duplicate"

    async def _handle_watch_check_callback(
        self,
        *,
        account: TelegramAccountRecord,
        dedupe_key: str,
        callback_query_id: str,
        watch_id: UUID,
        expected_version: int,
        source_id: str,
        update_id: int,
        created_at: datetime,
    ) -> TelegramWatchCallbackResult:
        watch = await self._watches.get_watch(account.household_id, watch_id)
        if watch is None:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Watch not found or access denied.",
                created_at=created_at,
            )
            return "not_found"
        if watch.version != expected_version:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Watch changed in another place. Open /watches and try again.",
                created_at=created_at,
            )
            return "version_conflict"
        if self._personal_observation_service is None:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text="Manual browser check is unavailable right now.",
                created_at=created_at,
            )
            return "observation_unavailable"

        search_intent = _search_intent_from_watch(watch)
        grant = await self._personal_observation_service.issue_grant(
            user_id=account.user_id,
            source_id=source_id,
            search_intent=search_intent,
            source=GrantSource.TELEGRAM_CALLBACK,
        )
        if not grant.allowed or grant.grant_token is None:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text=f"Manual browser check is unavailable: {grant.code.value}.",
                created_at=created_at,
            )
            return "observation_unavailable"

        created = await self._personal_observation_service.create_job(
            household_id=account.household_id,
            user_id=account.user_id,
            source_id=source_id,
            search_id=_watch_observation_search_id(watch),
            search_intent=search_intent,
            grant_token=grant.grant_token,
            idempotency_key=_watch_observation_idempotency_key(
                update_id=update_id,
                watch_id=watch.id,
                watch_version=watch.version,
                source_id=source_id,
            ),
        )
        if not created.accepted or created.job_id is None:
            await self._enqueue_callback_ack(
                account=account,
                dedupe_key=dedupe_key,
                callback_query_id=callback_query_id,
                text=f"Manual browser check was not queued: {created.code.value}.",
                created_at=created_at,
            )
            return "observation_unavailable"

        await self._record_watch_audit(
            account=account,
            watch_id=watch_id,
            action="watch.browser_observation_queued",
            created_at=created_at,
        )
        text = _watch_check_success_text(
            watch,
            source_id=source_id,
            job_id=created.job_id,
            idempotent_replay=created.idempotent_replay,
        )
        queued = await self._enqueue_callback_ack(
            account=account,
            dedupe_key=dedupe_key,
            callback_query_id=callback_query_id,
            text=text,
            created_at=created_at,
        )
        return "queued" if queued else "duplicate"

    async def _enqueue_callback_ack(
        self,
        *,
        account: TelegramAccountRecord,
        dedupe_key: str,
        callback_query_id: str,
        text: str,
        created_at: datetime,
    ) -> bool:
        payload = {
            "kind": "callback_ack",
            "command": "watch_callback",
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": False,
        }
        return await self._outbox.enqueue(
            NewTelegramNotification(
                id=self._id_factory(),
                household_id=account.household_id,
                user_id=account.user_id,
                chat_id=account.chat_id,
                kind="callback_ack",
                dedupe_key=dedupe_key,
                payload_json=json.dumps(payload, sort_keys=True),
                status="queued",
                attempts=0,
                created_at=created_at,
            )
        )

    async def _record_watch_audit(
        self,
        *,
        account: TelegramAccountRecord,
        watch_id: UUID,
        action: str,
        created_at: datetime,
    ) -> None:
        if self._audit_repository is None:
            return
        await self._audit_repository.add_event(
            NewAuditEvent(
                id=self._id_factory(),
                household_id=account.household_id,
                actor_user_id=account.user_id,
                action=action,
                entity_type="watch",
                entity_id=watch_id,
                summary=f"telegram {action}",
                created_at=created_at,
            )
        )


class TelegramNotificationService:
    def __init__(
        self,
        *,
        links: TelegramLinkRepository,
        outbox: TelegramNotificationOutboxRepository,
        transport: TelegramTransport | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._links = links
        self._outbox = outbox
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory

    async def enqueue_price_alert(
        self,
        *,
        household_id: UUID,
        user_id: UUID,
        alert: PriceAlert,
    ) -> bool:
        account = await self._links.get_account_for_user(user_id)
        status = "queued" if account is not None else "blocked"
        payload = {
            "kind": "price_drop",
            "watch_id": alert.watch_id,
            "itinerary_fingerprint": alert.itinerary_fingerprint,
            "drop_percent": alert.drop_percent,
            "previous_minor": alert.previous_price.minor_units,
            "current_minor": alert.current_price.minor_units,
            "currency": alert.current_price.currency,
            "observed_at": alert.observed_at.isoformat(),
        }
        return await self._outbox.enqueue(
            NewTelegramNotification(
                id=self._id_factory(),
                household_id=household_id,
                user_id=user_id,
                chat_id=account.chat_id if account is not None else None,
                kind="price_drop",
                dedupe_key=f"telegram:{alert.dedupe_key}",
                payload_json=json.dumps(payload, sort_keys=True),
                status=status,
                attempts=0,
                created_at=self._clock(),
                error_code=None if account is not None else "telegram_link_missing",
                error_message=None if account is not None else "user has not linked Telegram",
            )
        )

    async def deliver_due(
        self,
        *,
        limit: int,
        max_attempts: int,
        retry_delay: timedelta,
        worker_id: str = "telegram-delivery",
        quiet_hours: TelegramQuietHours | None = None,
    ) -> TelegramDeliverySummary:
        now = self._clock()
        due = await self._outbox.claim_due(now=now, limit=limit, worker_id=worker_id)
        summary = TelegramDeliverySummary(notifications_seen=len(due))
        for notification in due:
            result = await self._deliver_one(
                notification,
                now=now,
                max_attempts=max_attempts,
                retry_delay=retry_delay,
                quiet_hours=quiet_hours,
            )
            summary = TelegramDeliverySummary(
                notifications_seen=summary.notifications_seen,
                sent=summary.sent + result.sent,
                retry_scheduled=summary.retry_scheduled + result.retry_scheduled,
                failed=summary.failed + result.failed,
                deferred_quiet_hours=(summary.deferred_quiet_hours + result.deferred_quiet_hours),
            )
        return summary

    async def deliver_claimed(
        self,
        notification: TelegramNotificationRecord,
        *,
        max_attempts: int,
        retry_delay: timedelta,
        quiet_hours: TelegramQuietHours | None = None,
        now: datetime | None = None,
    ) -> TelegramDeliverySummary:
        return await self._deliver_one(
            notification,
            now=now or self._clock(),
            max_attempts=max_attempts,
            retry_delay=retry_delay,
            quiet_hours=quiet_hours,
        )

    async def _deliver_one(
        self,
        notification: TelegramNotificationRecord,
        *,
        now: datetime,
        max_attempts: int,
        retry_delay: timedelta,
        quiet_hours: TelegramQuietHours | None,
    ) -> TelegramDeliverySummary:
        if (
            quiet_hours is not None
            and notification.kind != "callback_ack"
            and quiet_hours.contains(now)
        ):
            await self._outbox.mark_retry_scheduled(
                notification_id=notification.id,
                attempts=notification.attempts,
                next_retry_at=quiet_hours.next_allowed_at(now),
                error_code="quiet_hours",
                error_message="delivery deferred by quiet hours",
            )
            return TelegramDeliverySummary(deferred_quiet_hours=1)

        if self._transport is None:
            await self._outbox.mark_failed(
                notification_id=notification.id,
                attempts=notification.attempts + 1,
                failed_at=now,
                error_code="telegram_transport_unavailable",
                error_message="telegram transport is unavailable",
            )
            return TelegramDeliverySummary(failed=1)

        if notification.kind == "callback_ack":
            callback_payload = _callback_ack_payload(notification)
            if callback_payload is None:
                await self._outbox.mark_failed(
                    notification_id=notification.id,
                    attempts=notification.attempts + 1,
                    failed_at=now,
                    error_code="telegram_payload_invalid",
                    error_message="callback_ack payload is invalid",
                )
                return TelegramDeliverySummary(failed=1)
            callback_query_id, text, show_alert = callback_payload
            chat_id = None
        elif notification.chat_id is None:
            await self._outbox.mark_failed(
                notification_id=notification.id,
                attempts=notification.attempts + 1,
                failed_at=now,
                error_code="telegram_transport_unavailable",
                error_message="telegram chat id is unavailable",
            )
            return TelegramDeliverySummary(failed=1)
        else:
            callback_query_id = None
            text = None
            show_alert = False
            chat_id = notification.chat_id

        try:
            if callback_query_id is not None:
                await self._transport.answer_callback_query(
                    callback_query_id=callback_query_id,
                    text=text,
                    show_alert=show_alert,
                )
            else:
                assert chat_id is not None
                await self._transport.send_message(
                    chat_id=chat_id,
                    text=_notification_text(notification),
                    reply_markup=_notification_reply_markup(notification),
                )
        except Exception as exc:
            attempts = notification.attempts + 1
            error_code = _notification_failure_code(notification)
            if attempts < max_attempts:
                await self._outbox.mark_retry_scheduled(
                    notification_id=notification.id,
                    attempts=attempts,
                    next_retry_at=now + retry_delay,
                    error_code=error_code,
                    error_message=exc.__class__.__name__,
                )
                return TelegramDeliverySummary(retry_scheduled=1)
            await self._outbox.mark_failed(
                notification_id=notification.id,
                attempts=attempts,
                failed_at=now,
                error_code=error_code,
                error_message=exc.__class__.__name__,
            )
            return TelegramDeliverySummary(failed=1)

        await self._outbox.mark_sent(notification_id=notification.id, sent_at=now)
        if notification.kind == "price_drop":
            price_payload = _price_drop_payload(notification)
            log_event(
                "alert_sent",
                watch_id=price_payload.get("watch_id"),
                reason="price_drop",
                notification_id=notification.id,
                household_id=notification.household_id,
                attempt=notification.attempts + 1,
            )
        return TelegramDeliverySummary(sent=1)


def _notification_text(notification: TelegramNotificationRecord) -> str:
    payload = json.loads(notification.payload_json)
    if not isinstance(payload, dict):
        return "Flight Hunter alert"
    if notification.kind == "command_reply":
        text = payload.get("text")
        return text if isinstance(text, str) and text.strip() else "Flight Hunter"
    currency = str(payload.get("currency", ""))
    current_minor = payload.get("current_minor")
    previous_minor = payload.get("previous_minor")
    drop_percent = payload.get("drop_percent")
    return (
        "Flight Hunter price drop alert\n"
        f"Drop: {drop_percent}%\n"
        f"Previous: {previous_minor} minor units {currency}\n"
        f"Current: {current_minor} minor units {currency}\n"
        "Open the web UI to verify cached price freshness before booking."
    )


def _notification_reply_markup(
    notification: TelegramNotificationRecord,
) -> dict[str, object] | None:
    if notification.kind != "command_reply":
        return None
    payload = json.loads(notification.payload_json)
    if not isinstance(payload, dict):
        return None
    reply_markup = payload.get("reply_markup")
    return reply_markup if isinstance(reply_markup, dict) else None


def _callback_ack_payload(
    notification: TelegramNotificationRecord,
) -> tuple[str, str | None, bool] | None:
    payload = json.loads(notification.payload_json)
    if not isinstance(payload, dict):
        return None
    callback_query_id = payload.get("callback_query_id")
    if not isinstance(callback_query_id, str) or not callback_query_id.strip():
        return None
    text_value = payload.get("text")
    text = text_value.strip()[:200] if isinstance(text_value, str) and text_value.strip() else None
    return callback_query_id, text, payload.get("show_alert") is True


def _price_drop_payload(notification: TelegramNotificationRecord) -> dict[str, object]:
    try:
        payload = json.loads(notification.payload_json)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _notification_failure_code(notification: TelegramNotificationRecord) -> str:
    if notification.kind == "callback_ack":
        return "telegram_callback_ack_failed"
    return "telegram_send_failed"


def _watches_command_text(watches: tuple[WatchRecord, ...]) -> str:
    if not watches:
        return "Flight Hunter watches\nNo active watches yet."
    lines = ["Flight Hunter watches"]
    for index, watch in enumerate(watches[:10], start=1):
        route = f"{watch.origin} -> {watch.destination}"
        dates = watch.departure_date
        if watch.return_date is not None:
            dates = f"{dates}..{watch.return_date}"
        status = _watch_status(watch)
        lines.append(
            f"{index}. {route} {dates}, {watch.passengers} pax, {status}, v{watch.version}"
        )
    if len(watches) > 10:
        lines.append(f"And {len(watches) - 10} more in the web UI.")
    return "\n".join(lines)


def _watches_reply_markup(
    watches: tuple[WatchRecord, ...],
    *,
    observation_source_id: str,
) -> dict[str, object] | None:
    rows: list[list[dict[str, str]]] = []
    for index, watch in enumerate(watches[:10], start=1):
        rows.append(
            [
                {
                    "text": f"Pause #{index}",
                    "callback_data": f"fh:w:p:{watch.id}:{watch.version}",
                },
                {
                    "text": f"Resume #{index}",
                    "callback_data": f"fh:w:r:{watch.id}:{watch.version}",
                },
                {
                    "text": f"Check #{index}",
                    "callback_data": (f"fh:w:c:{watch.id}:{watch.version}:{observation_source_id}"),
                },
            ]
        )
    return {"inline_keyboard": rows} if rows else None


def _watch_status(watch: WatchRecord) -> str:
    if not watch.enabled:
        return "disabled"
    if watch.paused_until is not None:
        return f"paused until {watch.paused_until.isoformat()}"
    return "enabled"


def _parse_watch_callback_data(
    data: str,
) -> tuple[TelegramWatchCallbackAction, UUID, int, str] | None:
    parts = data.split(":")
    if len(parts) not in {5, 6} or parts[0] != "fh" or parts[1] != "w":
        return None
    if parts[2] == "p":
        action: TelegramWatchCallbackAction = "pause"
    elif parts[2] == "r":
        action = "resume"
    elif parts[2] == "c":
        action = "check"
    else:
        return None
    if action == "check" and len(parts) != 6:
        return None
    if action != "check" and len(parts) != 5:
        return None
    source_id = parts[5] if action == "check" else "tutu"
    if not _safe_source_id(source_id):
        return None
    try:
        watch_id = UUID(parts[3])
        version = int(parts[4])
    except ValueError:
        return None
    if version < 1:
        return None
    return action, watch_id, version, source_id


def _watch_callback_success_text(
    watch: WatchRecord,
    *,
    action: Literal["pause", "resume"],
) -> str:
    route = f"{watch.origin} -> {watch.destination}"
    if action == "pause":
        return f"Watch {route} paused for 24 hours. Version: {watch.version}."
    return f"Watch {route} resumed. Version: {watch.version}."


def _watch_check_success_text(
    watch: WatchRecord,
    *,
    source_id: str,
    job_id: UUID,
    idempotent_replay: bool,
) -> str:
    route = f"{watch.origin} -> {watch.destination}"
    prefix = (
        "Manual browser check already queued"
        if idempotent_replay
        else "Manual browser check queued"
    )
    return f"{prefix} for {route} on {source_id}. Job: {job_id}."


def _search_intent_from_watch(watch: WatchRecord) -> SearchIntent:
    return SearchIntent(
        origin=watch.origin,
        destination=watch.destination,
        departure_date=watch.departure_date,
        return_date=watch.return_date,
        passengers=watch.passengers,
        currency=watch.currency,
    )


def _watch_observation_search_id(watch: WatchRecord) -> str:
    return f"telegram-watch:{watch.id}:v{watch.version}"


def _watch_observation_idempotency_key(
    *,
    update_id: int,
    watch_id: UUID,
    watch_version: int,
    source_id: str,
) -> str:
    return f"telegram:watch-check:{update_id}:{watch_id}:v{watch_version}:{source_id}"


def _safe_source_id(value: str) -> bool:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    return 0 < len(value) <= 32 and all(character in allowed for character in value)


def _default_code() -> str:
    return uuid4().hex[:10].upper()
