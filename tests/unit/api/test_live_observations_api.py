from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.persistence.models import mapper_registry

USER_ID = UUID("11111111-1111-1111-1111-111111111111")
INTENT = {
    "origin": "WAW",
    "destination": "BCN",
    "departure_date": "2026-10-12",
    "return_date": "2026-10-19",
    "passengers": 2,
    "currency": "RUB",
}


def test_browser_sources_endpoint_exposes_policy_without_legal_text_or_background(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCRAPING_OBSERVER_ENABLED", "false")
    client = TestClient(create_app())

    response = client.get("/api/v1/browser-sources")

    assert response.status_code == 200
    sources = {source["source_id"]: source for source in response.json()["sources"]}
    source = sources["demo_browser"]
    assert source["source_id"] == "demo_browser"
    assert source["enabled"] is False
    assert source["user_action_required"] is True
    assert source["background_allowed"] is False
    assert sources["tutu"]["enabled"] is False
    assert sources["tutu"]["permission_status"] == "active"
    assert sources["tutu"]["background_allowed"] is False
    assert "document_ref" not in source
    assert "secret" not in str(response.json()).lower()


def test_browser_sources_endpoint_enables_personal_observer_sources_from_env(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "true")
    monkeypatch.setenv("RU_AGGREGATORS_ENABLED", "tutu")
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    client = TestClient(create_app())

    response = client.get("/api/v1/browser-sources")

    sources = {source["source_id"]: source for source in response.json()["sources"]}
    assert response.status_code == 200
    assert sources["tutu"]["enabled"] is True
    assert sources["tutu"]["current_health"] == "healthy"
    assert sources["tutu"]["permission_status"] == "active"
    assert sources["tutu"]["user_action_required"] is True
    assert sources["tutu"]["background_allowed"] is False
    assert sources["yandex_travel"]["enabled"] is False


@pytest.mark.anyio
async def test_live_observation_api_uses_one_time_grant_and_idempotency(monkeypatch) -> None:
    monkeypatch.setenv("SCRAPING_OBSERVER_ENABLED", "true")
    client = TestClient(create_app(watch_session_factory=await _session_factory()))
    headers = {"X-Flight-Hunter-User-Id": str(USER_ID)}

    grant_response = client.post(
        "/api/v1/live-observation-grants",
        headers=headers,
        json={"source_id": "demo_browser", "search_intent": INTENT},
    )
    assert grant_response.status_code == 201
    grant_token = grant_response.json()["grant_token"]

    create_response = client.post(
        "/api/v1/live-observations",
        headers={**headers, "Idempotency-Key": "idem-1"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": grant_token,
        },
    )
    assert create_response.status_code == 202
    observation_id = create_response.json()["observation_id"]
    assert create_response.json()["status"] == "queued"

    duplicate_response = client.post(
        "/api/v1/live-observations",
        headers={**headers, "Idempotency-Key": "idem-1"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": grant_token,
        },
    )
    assert duplicate_response.status_code == 202
    assert duplicate_response.json()["observation_id"] == observation_id

    observation_response = client.get(
        f"/api/v1/live-observations/{observation_id}",
        headers=headers,
    )
    assert observation_response.status_code == 200
    observation = observation_response.json()
    assert observation["status"] == "succeeded"
    assert observation["result_scope"] == "live_observed"
    assert observation["offers"][0]["freshness"] == "live_observed"
    assert observation["offers"][0]["requires_live_confirmation"] is True

    replay_response = client.post(
        "/api/v1/live-observations",
        headers={**headers, "Idempotency-Key": "idem-2"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": grant_token,
        },
    )
    assert replay_response.status_code == 403
    assert replay_response.json()["code"] == "user_action_grant_consumed"


@pytest.mark.anyio
async def test_live_observation_api_requires_user_context_and_grant(monkeypatch) -> None:
    monkeypatch.setenv("SCRAPING_OBSERVER_ENABLED", "true")
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    missing_auth = client.post(
        "/api/v1/live-observations",
        headers={"Idempotency-Key": "idem-1"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": "22222222-2222-2222-2222-222222222222",
        },
    )
    assert missing_auth.status_code == 401
    assert missing_auth.json()["code"] == "auth_context_missing"

    missing_grant = client.post(
        "/api/v1/live-observations",
        headers={
            "X-Flight-Hunter-User-Id": str(USER_ID),
            "Idempotency-Key": "idem-1",
        },
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": "22222222-2222-2222-2222-222222222222",
        },
    )
    assert missing_grant.status_code == 403
    assert missing_grant.json()["code"] == "user_action_grant_required"


@pytest.mark.anyio
async def test_live_observation_api_persists_result_and_idempotency_across_app_instances(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SCRAPING_OBSERVER_ENABLED", "true")
    session_factory = await _session_factory()
    headers = {"X-Flight-Hunter-User-Id": str(USER_ID)}

    first_client = TestClient(create_app(watch_session_factory=session_factory))
    grant_response = first_client.post(
        "/api/v1/live-observation-grants",
        headers=headers,
        json={"source_id": "demo_browser", "search_intent": INTENT},
    )
    observation_response = first_client.post(
        "/api/v1/live-observations",
        headers={**headers, "Idempotency-Key": "idem-durable"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": grant_response.json()["grant_token"],
        },
    )
    observation_id = observation_response.json()["observation_id"]

    second_client = TestClient(create_app(watch_session_factory=session_factory))
    persisted = second_client.get(
        f"/api/v1/live-observations/{observation_id}",
        headers=headers,
    )
    replay = second_client.post(
        "/api/v1/live-observations",
        headers={**headers, "Idempotency-Key": "idem-durable"},
        json={
            "source_id": "demo_browser",
            "search_intent": INTENT,
            "grant_token": grant_response.json()["grant_token"],
        },
    )

    assert persisted.status_code == 200
    assert persisted.json()["status"] == "succeeded"
    assert persisted.json()["offers"][0]["freshness"] == "live_observed"
    assert replay.status_code == 202
    assert replay.json()["observation_id"] == observation_id


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
