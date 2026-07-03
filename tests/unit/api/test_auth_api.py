from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.persistence.models import auth_sessions_table, mapper_registry

BOOTSTRAP_TOKEN = "bootstrap-secret"


@pytest.mark.anyio
async def test_bootstrap_invitation_requires_configured_token() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_bootstrap_token=None),
        )
    )

    response = client.post(
        "/api/v1/auth/bootstrap-invitation",
        json={"household_name": "Family"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "auth_bootstrap_disabled"


@pytest.mark.anyio
async def test_accept_invitation_returns_session_and_me() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )

    invitation = _bootstrap_invitation(client)
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation["invitation_code"],
            "display_name": "Kiwun",
        },
    )
    assert accepted.status_code == 201
    session_body = accepted.json()
    assert session_body["session_token"]
    assert session_body["household_id"] == invitation["household_id"]
    assert session_body["role"] == "owner"
    UUID(session_body["user_id"])

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {session_body['session_token']}"},
    )

    assert me.status_code == 200
    assert me.json() == {
        "household_id": session_body["household_id"],
        "user_id": session_body["user_id"],
        "role": "owner",
        "expires_at": session_body["expires_at"],
    }


@pytest.mark.anyio
async def test_watch_api_accepts_bearer_session_without_legacy_headers() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )
    session_body = _accept_bootstrap_invitation(client)
    auth_headers = {"Authorization": f"Bearer {session_body['session_token']}"}

    created = client.post(
        "/api/v1/watches",
        headers=auth_headers,
        json=_watch_payload(destination="BCN"),
    )
    listed = client.get("/api/v1/watches", headers=auth_headers)

    assert created.status_code == 201
    assert created.json()["household_id"] == session_body["household_id"]
    assert created.json()["owner_user_id"] == session_body["user_id"]
    assert listed.status_code == 200
    assert [watch["destination"] for watch in listed.json()["watches"]] == ["BCN"]


@pytest.mark.anyio
async def test_bearer_session_wins_over_conflicting_legacy_headers() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )
    session_body = _accept_bootstrap_invitation(client)

    created = client.post(
        "/api/v1/watches",
        headers={
            "Authorization": f"Bearer {session_body['session_token']}",
            "X-Flight-Hunter-Household-Id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "X-Flight-Hunter-User-Id": "bbbbbbbb-0000-0000-0000-000000000001",
        },
        json=_watch_payload(destination="NRT"),
    )

    assert created.status_code == 201
    assert created.json()["household_id"] == session_body["household_id"]
    assert created.json()["owner_user_id"] == session_body["user_id"]


@pytest.mark.anyio
async def test_bearer_session_authenticates_manual_confirmation_and_telegram_link() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )
    session_body = _accept_bootstrap_invitation(client)
    auth_headers = {"Authorization": f"Bearer {session_body['session_token']}"}

    confirmation = client.post(
        "/api/v1/manual-price-confirmations",
        headers=auth_headers,
        json={
            "target_kind": "deal_candidate",
            "target_id": "deal-1",
            "source_id": "deal_discovery",
            "status": "confirmed",
            "amount_minor": 123_456,
            "currency": "RUB",
        },
    )
    link_code = client.post("/api/v1/telegram/link-code", headers=auth_headers)

    assert confirmation.status_code == 201
    assert confirmation.json()["household_id"] == session_body["household_id"]
    assert confirmation.json()["user_id"] == session_body["user_id"]
    assert link_code.status_code == 200
    assert link_code.json()["code"]


@pytest.mark.anyio
async def test_session_token_is_not_stored_in_database() -> None:
    session_factory = await _session_factory()
    client = TestClient(
        create_app(
            watch_session_factory=session_factory,
            settings=_settings(auth_bootstrap_token=BOOTSTRAP_TOKEN),
        )
    )

    session_body = _accept_bootstrap_invitation(client)

    async with session_factory() as session:
        result = await session.execute(select(auth_sessions_table.c.token_hash))
        stored_hash = result.scalar_one()
    assert stored_hash != session_body["session_token"]
    assert len(stored_hash) == 64


@pytest.mark.anyio
async def test_legacy_headers_can_be_disabled() -> None:
    client = TestClient(
        create_app(
            watch_session_factory=await _session_factory(),
            settings=_settings(auth_allow_legacy_headers=False),
        )
    )

    response = client.post(
        "/api/v1/watches",
        headers={
            "X-Flight-Hunter-Household-Id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "X-Flight-Hunter-User-Id": "aaaaaaaa-0000-0000-0000-000000000001",
        },
        json=_watch_payload(),
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


def _bootstrap_invitation(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": BOOTSTRAP_TOKEN},
        json={"household_name": "Family", "recipient_label": "owner"},
    )
    assert response.status_code == 201
    return response.json()


def _accept_bootstrap_invitation(client: TestClient) -> dict[str, str]:
    invitation = _bootstrap_invitation(client)
    response = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation["invitation_code"],
            "display_name": "Kiwun",
        },
    )
    assert response.status_code == 201
    return response.json()


def _settings(**overrides: object) -> AppSettings:
    return replace(AppSettings.from_env(), **overrides)


def _watch_payload(*, destination: str = "BCN") -> dict[str, object]:
    return {
        "origin": "WAW",
        "destination": destination,
        "departure_date": "2026-10-12",
        "return_date": "2026-10-19",
    }


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
