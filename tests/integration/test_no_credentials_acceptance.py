from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness
from flight_hunter.ops.worker import run_once
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    NewPriceSnapshot,
    PriceSnapshotRepository,
    TelegramNotificationOutboxRepository,
)

BOOTSTRAP_TOKEN = "bootstrap-acceptance-token"
TELEGRAM_WEBHOOK_HEADER = {"X-Telegram-Bot-Api-Secret-Token": "telegram-acceptance"}
OLD_OBSERVED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_no_credentials_demo_acceptance_flow(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'acceptance.db').as_posix()}"
    session_factory = await _session_factory(database_url)
    settings = _settings(database_url)
    client = TestClient(create_app(watch_session_factory=session_factory, settings=settings))

    family = _accept_invitation(client, household_name="Acceptance family")
    other_family = _accept_invitation(client, household_name="Other family")
    headers = {"Authorization": f"Bearer {family['session_token']}"}
    other_headers = {"Authorization": f"Bearer {other_family['session_token']}"}

    search = client.post(
        "/api/v1/searches",
        headers=headers,
        json=_search_payload(),
    )
    assert search.status_code == 201
    search_body = search.json()
    assert search_body["priced_offers"][0]["provider_id"] == "fake"
    assert search_body["priced_offers"][0]["freshness"] == "cached"
    assert search_body["priced_offers"][0]["requires_live_confirmation"] is True

    watch = client.post(
        "/api/v1/watches",
        headers=headers,
        json=_watch_payload(),
    )
    assert watch.status_code == 201
    watch_id = UUID(watch.json()["id"])
    household_id = UUID(family["household_id"])
    user_id = UUID(family["user_id"])

    await _link_telegram(client, headers=headers)
    await _add_previous_snapshot(
        session_factory,
        household_id=household_id,
        watch_id=watch_id,
    )

    first_summary = await run_once(
        database_url=database_url,
        settings=settings,
        limit=10,
        process_watch_scans=True,
        cleanup_expired_live_observations=False,
    )
    second_summary = await run_once(
        database_url=database_url,
        settings=settings,
        limit=10,
        process_watch_scans=True,
        cleanup_expired_live_observations=False,
    )

    history = client.get(f"/api/v1/watches/{watch_id}/history", headers=headers)
    hidden_history = client.get(f"/api/v1/watches/{watch_id}/history", headers=other_headers)
    audit = client.get("/api/v1/admin/audit-events", headers=headers)
    outbox_rows = await _telegram_rows(session_factory, user_id)
    audit_rows = await _audit_rows(session_factory, household_id)

    assert first_summary.watch_due_seen == 1
    assert first_summary.watch_jobs_enqueued == 1
    assert first_summary.watch_jobs_succeeded == 1
    assert first_summary.watch_snapshots_saved == 1
    assert first_summary.watch_alerts_recorded == 1
    assert first_summary.watch_telegram_notifications_enqueued == 1
    assert second_summary.watch_telegram_notifications_enqueued == 0
    assert history.status_code == 200
    assert len(history.json()["snapshots"]) == 2
    assert hidden_history.status_code == 404
    assert audit.status_code == 200
    assert any(event["action"] == "watch.created" for event in audit.json()["audit_events"])
    assert [event.action for event in audit_rows] == ["watch.created"]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].kind == "price_drop"
    assert outbox_rows[0].chat_id == 98765
    assert outbox_rows[0].dedupe_key.startswith("telegram:")
    assert json.loads(outbox_rows[0].payload_json)["current_minor"] == 79_900


def _accept_invitation(client: TestClient, *, household_name: str) -> dict[str, str]:
    invitation = client.post(
        "/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": BOOTSTRAP_TOKEN},
        json={"household_name": household_name, "recipient_label": "owner"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "Acceptance owner",
        },
    )
    assert accepted.status_code == 201
    return accepted.json()


async def _link_telegram(client: TestClient, *, headers: dict[str, str]) -> None:
    code = client.post("/api/v1/telegram/link-code", headers=headers)
    assert code.status_code == 200
    linked = client.post(
        "/api/v1/telegram/webhook",
        headers=TELEGRAM_WEBHOOK_HEADER,
        json={
            "update_id": 42,
            "message": {
                "text": f"/link {code.json()['code']}",
                "from": {"id": 12345},
                "chat": {"id": 98765},
            },
        },
    )
    assert linked.status_code == 202


async def _add_previous_snapshot(
    session_factory: async_sessionmaker,
    *,
    household_id: UUID,
    watch_id: UUID,
) -> None:
    async with session_factory() as session:
        await PriceSnapshotRepository(session).add_snapshot(
            NewPriceSnapshot(
                id=UUID("44444444-4444-4444-4444-444444444444"),
                household_id=household_id,
                watch_id=watch_id,
                provider_id="fake",
                itinerary_fingerprint=_fake_itinerary_fingerprint(),
                observed_at=OLD_OBSERVED_AT,
                price=Money(100_000, "RUB"),
                freshness=Freshness.CACHED,
                requires_live_confirmation=True,
            )
        )
        await session.commit()


async def _telegram_rows(session_factory: async_sessionmaker, user_id: UUID):
    async with session_factory() as session:
        return await TelegramNotificationOutboxRepository(session).list_by_user(user_id)


async def _audit_rows(session_factory: async_sessionmaker, household_id: UUID):
    async with session_factory() as session:
        return await AuditEventRepository(session).list_events(household_id)


async def _session_factory(database_url: str) -> async_sessionmaker:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    await engine.dispose()
    return async_sessionmaker(create_async_engine(database_url), expire_on_commit=False)


def _settings(database_url: str) -> AppSettings:
    return replace(
        AppSettings.from_env(),
        database_url=database_url,
        auth_bootstrap_token=BOOTSTRAP_TOKEN,
        telegram_enabled=True,
        telegram_webhook_secret="telegram-acceptance",
        telegram_bot_token=None,
        aviasales_search_enabled=False,
        aviasales_search_signature=None,
        aviasales_search_marker=None,
        watch_scan_enabled=True,
        watch_alert_drop_threshold_percent=10,
        watch_alert_cooldown_seconds=3600,
    )


def _search_payload() -> dict[str, object]:
    return {
        "origin": "WAW",
        "destination": "BCN",
        "departure_date": "2026-10-12",
        "return_date": "2026-10-19",
        "passengers": 1,
        "currency": "RUB",
    }


def _watch_payload() -> dict[str, object]:
    return {
        "origin": "WAW",
        "destination": "BCN",
        "departure_date": "2026-10-12",
        "return_date": "2026-10-19",
        "passengers": 1,
        "currency": "RUB",
    }


def _fake_itinerary_fingerprint() -> str:
    return "|".join(
        (
            "fake",
            "fake:WAW:BCN:2026-10-12:2026-10-19:1",
            "WAW",
            "BCN",
            "2026-10-12",
            "2026-10-19",
            "1",
            "RUB",
        )
    )
