from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import (
    NewSourceHealthEvent,
    SourceHealthEventRepository,
)

NOW = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_source_health_event_repository_records_append_only_events() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = SourceHealthEventRepository(session)
        await repository.add_event(
            NewSourceHealthEvent(
                id=UUID(int=1),
                source_id="tutu",
                event_type="browser_observation",
                status="retry_scheduled",
                message="browser observation retry scheduled; code=runner_failed",
                observed_at=NOW,
                cooldown_until=NOW + timedelta(minutes=1),
            )
        )
        await repository.add_event(
            NewSourceHealthEvent(
                id=UUID(int=2),
                source_id="aviasales_search",
                event_type="provider_contract",
                status="ok",
                message="contract fixture passed",
                observed_at=NOW + timedelta(seconds=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        repository = SourceHealthEventRepository(session)
        all_events = await repository.list_recent()
        tutu_events = await repository.list_recent(source_id="tutu")

    assert [event.source_id for event in all_events] == ["aviasales_search", "tutu"]
    assert len(tutu_events) == 1
    assert tutu_events[0].status == "retry_scheduled"
    assert tutu_events[0].cooldown_until == NOW + timedelta(minutes=1)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
