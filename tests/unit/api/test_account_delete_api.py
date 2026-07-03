from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.domain.auth import HouseholdRole
from flight_hunter.domain.auth import token_hash as hash_token
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    HouseholdWatchRepository,
    IdentityRepository,
    NewTelegramLinkCode,
    NewWatch,
    TelegramLinkRepository,
)

BOOTSTRAP_TOKEN = "bootstrap-secret"
OTHER_USER_ID = UUID("bbbbbbbb-0000-0000-0000-000000000002")
OWNED_WATCH_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_WATCH_ID = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 29, 16, 30, tzinfo=UTC)


@pytest.mark.anyio
async def test_delete_account_requires_bearer_session_not_legacy_headers() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_allow_legacy_headers=True),
        )
    )

    response = client.delete(
        "/api/v1/account",
        headers={
            "X-Flight-Hunter-Household-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "X-Flight-Hunter-User-Id": "aaaaaaaa-0000-0000-0000-000000000001",
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


@pytest.mark.anyio
async def test_delete_account_deactivates_current_user_and_retains_history() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            watch_session_factory=session_factory,
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )
    session_body = _accept_bootstrap_invitation(client)
    household_id = UUID(session_body["household_id"])
    user_id = UUID(session_body["user_id"])
    auth_headers = {"Authorization": f"Bearer {session_body['session_token']}"}
    await _seed_account_delete_data(session_factory, household_id, user_id)

    response = client.delete("/api/v1/account", headers=auth_headers)
    me_after = client.get("/api/v1/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "deactivated",
        "household_id": str(household_id),
        "user_id": str(user_id),
        "sessions_revoked": 1,
        "membership_disabled": True,
        "telegram_account_revoked": True,
        "owned_watches_deleted": 1,
        "retained_records": [
            "audit_events",
            "price_history",
            "manual_confirmations",
            "browser_observations",
            "deal_candidates",
        ],
    }
    assert me_after.status_code == 401

    async with session_factory() as session:
        identity = IdentityRepository(session)
        auth_session = await identity.session_by_token_hash(
            token_hash=hash_token(session_body["session_token"]),
            now=NOW + timedelta(minutes=10),
        )
        watches = await HouseholdWatchRepository(session).list_watches_for_export(
            household_id,
            limit=10,
        )
        telegram_account = await TelegramLinkRepository(session).get_account_for_user(user_id)
        audit_events = await AuditEventRepository(session).list_recent(household_id, limit=10)

    assert auth_session is None
    watch_by_id = {watch.id: watch for watch in watches}
    assert watch_by_id[OWNED_WATCH_ID].deleted_by_user_id == user_id
    assert watch_by_id[OTHER_WATCH_ID].deleted_at is None
    assert telegram_account is None
    assert {"account.deactivated", "watch.deleted"}.issubset(
        {event.action for event in audit_events}
    )


async def _seed_account_delete_data(
    session_factory: async_sessionmaker,
    household_id: UUID,
    user_id: UUID,
) -> None:
    async with session_factory() as session:
        identity = IdentityRepository(session)
        await identity.add_user(
            user_id=OTHER_USER_ID,
            display_name="Other",
            created_at=NOW,
        )
        await identity.add_membership(
            household_id=household_id,
            user_id=OTHER_USER_ID,
            role=HouseholdRole.MEMBER,
            created_at=NOW,
        )
        watches = HouseholdWatchRepository(session)
        await watches.add_watch(
            NewWatch(
                id=OWNED_WATCH_ID,
                household_id=household_id,
                owner_user_id=user_id,
                origin="MOW",
                destination="AYT",
                departure_date="2026-09-10",
                return_date=None,
                created_at=NOW,
            )
        )
        await watches.add_watch(
            NewWatch(
                id=OTHER_WATCH_ID,
                household_id=household_id,
                owner_user_id=OTHER_USER_ID,
                origin="LED",
                destination="IST",
                departure_date="2026-09-11",
                return_date=None,
                created_at=NOW,
            )
        )
        telegram = TelegramLinkRepository(session)
        await telegram.add_code(
            NewTelegramLinkCode(
                code="ABC123",
                household_id=household_id,
                user_id=user_id,
                created_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        await telegram.consume_code(
            code="ABC123",
            telegram_user_id=12345,
            chat_id=98765,
            now=NOW + timedelta(minutes=1),
        )
        await session.commit()


def _accept_bootstrap_invitation(client: TestClient) -> dict[str, str]:
    invitation = client.post(
        "/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": BOOTSTRAP_TOKEN},
        json={"household_name": "Family", "recipient_label": "owner"},
    )
    assert invitation.status_code == 201
    response = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "Kiwun",
        },
    )
    assert response.status_code == 201
    return response.json()


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings.from_env(), **overrides)


async def _session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
