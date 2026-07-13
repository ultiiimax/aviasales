from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    NewSourceHealthEvent,
    SourceHealthEventRepository,
)

NOW = datetime(2026, 6, 29, 22, 30, tzinfo=UTC)


def test_admin_source_health_reads_config_and_recent_events_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AVIASALES_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AVIASALES_SEARCH_SIGNATURE", "secret-signature")
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "secret-marker")
    session_factory = asyncio.run(_session_factory_with_events())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.get("/api/v1/admin/sources/health")
    paged_response = client.get(
        "/api/v1/admin/sources/health?sources_limit=1&sources_offset=1&event_limit=7"
    )

    assert response.status_code == 200
    assert paged_response.status_code == 200
    body = response.json()
    paged_body = paged_response.json()
    assert body["checked_at"]
    assert body["sources_limit"] == 100
    assert body["sources_offset"] == 0
    assert body["event_limit"] == 100
    assert paged_body["sources_limit"] == 1
    assert paged_body["sources_offset"] == 1
    assert paged_body["event_limit"] == 7
    assert len(paged_body["sources"]) == 1
    sources = {source["source_id"]: source for source in body["sources"]}
    assert sources["aviasales_search"]["contract_known"] is True
    assert sources["aviasales_search"]["stage"] == "implemented"
    assert sources["searxng"]["contract_known"] is True
    assert sources["searxng"]["current_status"] == "blocked"
    assert sources["searxng"]["blocked_reasons"] == ["searxng_disabled"]
    assert sources["crawl4ai"]["contract_known"] is True
    assert sources["crawl4ai"]["blocked_reasons"] == ["crawl4ai_disabled"]
    assert sources["deal_discovery"]["contract_known"] is True
    assert sources["deal_discovery"]["merge_scope"] == "candidate_only"
    assert sources["deal_discovery"]["background_requests_allowed"] is False
    assert sources["deal_discovery"]["user_action_required"] is True
    assert sources["deal_discovery"]["blocked_reasons"] == [
        "searxng_disabled",
        "crawl4ai_disabled",
    ]
    assert sources["tutu"]["contract_known"] is False
    assert sources["tutu"]["current_status"] == "retry_scheduled"
    assert sources["tutu"]["latest_event"]["event_type"] == "browser_observation"
    assert sources["tutu"]["latest_event"]["cooldown_until"] is not None
    assert "secret-signature" not in str(body)
    assert "secret-marker" not in str(body)


async def _session_factory_with_events():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await SourceHealthEventRepository(session).add_event(
            NewSourceHealthEvent(
                id=UUID("99999999-9999-9999-9999-999999999999"),
                source_id="tutu",
                event_type="browser_observation",
                status="retry_scheduled",
                message="browser observation retry scheduled; code=runner_failed",
                observed_at=NOW,
                cooldown_until=NOW + timedelta(minutes=1),
            )
        )
        await session.commit()
    return session_factory
