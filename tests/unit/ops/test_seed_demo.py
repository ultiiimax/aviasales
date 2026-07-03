from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.ops.seed_demo import DEMO_HOUSEHOLD_ID, seed_demo
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import HouseholdWatchRepository


@pytest.mark.anyio
async def test_seed_demo_creates_deterministic_watch_once(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'seed.db').as_posix()}"
    await _create_schema(database_url)

    first = await seed_demo(database_url=database_url)
    second = await seed_demo(database_url=database_url)

    assert first.ok is True
    assert first.created is True
    assert second.ok is True
    assert second.created is False

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        watches = await HouseholdWatchRepository(session).list_watches(DEMO_HOUSEHOLD_ID)
    await engine.dispose()

    assert len(watches) == 1
    assert watches[0].origin == "MOW"
    assert watches[0].destination == "IST"


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    await engine.dispose()
