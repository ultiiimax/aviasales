from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.domain.observation import ObservationStatus
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    BrowserObservationJobRepository,
    HouseholdWatchRepository,
    LiveObservationRepository,
    NewWatch,
    TelegramLinkRepository,
    TelegramNotificationOutboxRepository,
)

HOUSEHOLD_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_A = "aaaaaaaa-0000-0000-0000-000000000001"
WATCH_A = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def test_telegram_webhook_is_disabled_by_default() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/telegram/webhook",
        json={"update_id": 1001, "message": {"text": "/start"}},
    )

    assert response.status_code == 503
    assert response.json() == {"code": "telegram_disabled", "status": "rejected"}


def test_telegram_webhook_requires_secret_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    client = TestClient(create_app(watch_session_factory=asyncio.run(_session_factory())))

    response = client.post(
        "/api/v1/telegram/webhook",
        json={"update_id": 1001, "message": {"text": "/start"}},
    )

    assert response.status_code == 403
    assert response.json() == {"code": "secret_mismatch", "status": "rejected"}


def test_telegram_webhook_accepts_and_deduplicates_update(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    client = TestClient(create_app(watch_session_factory=asyncio.run(_session_factory())))
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    payload = {"update_id": 1001, "message": {"text": "/start"}}

    first = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    second = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)

    assert first.status_code == 202
    assert first.json() == {"code": "accepted", "status": "accepted"}
    assert second.status_code == 200
    assert second.json() == {"code": "duplicate", "status": "ignored"}


def test_telegram_webhook_deduplicates_update_across_app_instances(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    session_factory = asyncio.run(_session_factory())
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    payload = {"update_id": 2002, "message": {"text": "/start"}}

    first_client = TestClient(create_app(watch_session_factory=session_factory))
    first = first_client.post("/api/v1/telegram/webhook", json=payload, headers=headers)

    second_client = TestClient(create_app(watch_session_factory=session_factory))
    second = second_client.post("/api/v1/telegram/webhook", json=payload, headers=headers)

    assert first.status_code == 202
    assert first.json() == {"code": "accepted", "status": "accepted"}
    assert second.status_code == 200
    assert second.json() == {"code": "duplicate", "status": "ignored"}


def test_telegram_link_code_is_consumed_from_webhook(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))

    created = client.post(
        "/api/v1/telegram/link-code",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )
    code = created.json()["code"]
    payload = {
        "update_id": 3003,
        "message": {
            "text": f"/link {code}",
            "from": {"id": 12345},
            "chat": {"id": 98765},
        },
    }
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}

    linked = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    replay = client.post("/api/v1/telegram/webhook", json=payload, headers=headers)
    account = asyncio.run(_telegram_account(session_factory, UUID(USER_A)))

    assert created.status_code == 200
    assert linked.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == {"code": "duplicate", "status": "ignored"}
    assert account is not None
    assert account.telegram_user_id == 12345
    assert account.chat_id == 98765


def test_telegram_watches_command_enqueues_linked_household_reply(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}

    created = client.post(
        "/api/v1/telegram/link-code",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )
    link_payload = {
        "update_id": 4004,
        "message": {
            "text": f"/link {created.json()['code']}",
            "from": {"id": 12345},
            "chat": {"id": 98765},
        },
    }
    linked = client.post("/api/v1/telegram/webhook", json=link_payload, headers=headers)
    asyncio.run(_add_watch(session_factory))

    command_payload = {
        "update_id": 4005,
        "message": {
            "text": "/watches",
            "from": {"id": 12345},
            "chat": {"id": 98765},
        },
    }
    accepted = client.post("/api/v1/telegram/webhook", json=command_payload, headers=headers)
    replay = client.post("/api/v1/telegram/webhook", json=command_payload, headers=headers)
    rows = asyncio.run(_telegram_outbox(session_factory, UUID(USER_A)))

    assert linked.status_code == 202
    assert accepted.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == {"code": "duplicate", "status": "ignored"}
    assert len(rows) == 1
    assert rows[0].kind == "command_reply"
    assert "WAW -> BCN" in rows[0].payload_json


def test_telegram_watch_pause_callback_mutates_owned_watch(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}

    created = client.post(
        "/api/v1/telegram/link-code",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )
    link_payload = {
        "update_id": 5005,
        "message": {
            "text": f"/link {created.json()['code']}",
            "from": {"id": 12345},
            "chat": {"id": 98765},
        },
    }
    linked = client.post("/api/v1/telegram/webhook", json=link_payload, headers=headers)
    asyncio.run(_add_watch(session_factory))

    callback_payload = {
        "update_id": 5006,
        "callback_query": {
            "id": "callback-1",
            "from": {"id": 12345},
            "message": {"chat": {"id": 98765}},
            "data": f"fh:w:p:{WATCH_A}:1",
        },
    }
    accepted = client.post("/api/v1/telegram/webhook", json=callback_payload, headers=headers)
    replay = client.post("/api/v1/telegram/webhook", json=callback_payload, headers=headers)
    rows = asyncio.run(_telegram_outbox(session_factory, UUID(USER_A)))
    watch = asyncio.run(_watch(session_factory, UUID(HOUSEHOLD_A), WATCH_A))

    assert linked.status_code == 202
    assert accepted.status_code == 202
    assert replay.status_code == 200
    assert watch is not None
    assert watch.paused_until is not None
    assert watch.paused_until > NOW
    assert watch.version == 2
    assert len(rows) == 1
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-1"
    assert payload["text"] == "Watch WAW -> BCN paused for 24 hours. Version: 2."
    assert "callback_data" not in payload


def test_telegram_watch_check_callback_queues_browser_observation(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_WATCH_CHECK_SOURCE_ID", "tutu")
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))
    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}

    created = client.post(
        "/api/v1/telegram/link-code",
        headers=_headers(HOUSEHOLD_A, USER_A),
    )
    link_payload = {
        "update_id": 6006,
        "message": {
            "text": f"/link {created.json()['code']}",
            "from": {"id": 12345},
            "chat": {"id": 98765},
        },
    }
    linked = client.post("/api/v1/telegram/webhook", json=link_payload, headers=headers)
    asyncio.run(_add_watch(session_factory))

    callback_payload = {
        "update_id": 6007,
        "callback_query": {
            "id": "callback-2",
            "from": {"id": 12345},
            "message": {"chat": {"id": 98765}},
            "data": f"fh:w:c:{WATCH_A}:1:tutu",
        },
    }
    accepted = client.post("/api/v1/telegram/webhook", json=callback_payload, headers=headers)
    replay = client.post("/api/v1/telegram/webhook", json=callback_payload, headers=headers)
    rows = asyncio.run(_telegram_outbox(session_factory, UUID(USER_A)))
    jobs = asyncio.run(_browser_jobs(session_factory))
    grant = asyncio.run(_grant(session_factory, UUID(USER_A), jobs[0].grant_id))
    watch = asyncio.run(_watch(session_factory, UUID(HOUSEHOLD_A), WATCH_A))

    assert linked.status_code == 202
    assert accepted.status_code == 202
    assert replay.status_code == 200
    assert replay.json() == {"code": "duplicate", "status": "ignored"}
    assert watch is not None
    assert watch.version == 1
    assert len(jobs) == 1
    assert jobs[0].status == ObservationStatus.QUEUED
    assert jobs[0].source_id == "tutu"
    assert jobs[0].search_id == f"telegram-watch:{WATCH_A}:v1"
    assert grant is not None
    assert grant.source == "telegram_callback"
    assert grant.consumed_at is not None
    assert len(rows) == 1
    assert rows[0].kind == "callback_ack"
    payload = json.loads(rows[0].payload_json)
    assert payload["callback_query_id"] == "callback-2"
    assert "Manual browser check queued" in payload["text"]
    assert str(grant.id) not in payload["text"]
    assert "callback_data" not in payload


def _headers(household_id: str, user_id: str) -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": household_id,
        "X-Flight-Hunter-User-Id": user_id,
    }


async def _telegram_account(session_factory, user_id: UUID):
    async with session_factory() as session:
        return await TelegramLinkRepository(session).get_account_for_user(user_id)


async def _telegram_outbox(session_factory, user_id: UUID):
    async with session_factory() as session:
        return await TelegramNotificationOutboxRepository(session).list_by_user(user_id)


async def _add_watch(session_factory) -> None:
    async with session_factory() as session:
        await HouseholdWatchRepository(session).add_watch(
            NewWatch(
                id=WATCH_A,
                household_id=UUID(HOUSEHOLD_A),
                owner_user_id=UUID(USER_A),
                origin="WAW",
                destination="BCN",
                departure_date="2026-10-12",
                return_date=None,
                created_at=NOW,
            )
        )
        await session.commit()


async def _watch(session_factory, household_id: UUID, watch_id: UUID):
    async with session_factory() as session:
        return await HouseholdWatchRepository(session).get_watch(household_id, watch_id)


async def _browser_jobs(session_factory):
    async with session_factory() as session:
        return await BrowserObservationJobRepository(session).list_queued(now=datetime.now(UTC))


async def _grant(session_factory, user_id: UUID, grant_id: UUID):
    async with session_factory() as session:
        return await LiveObservationRepository(session).get_grant(user_id, grant_id)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
