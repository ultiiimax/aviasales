from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.ops.worker_healthcheck import run_healthcheck
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import NewWorkerHeartbeat, WorkerHeartbeatRepository

NOW = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)


def test_worker_healthcheck_accepts_fresh_role_lane(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    asyncio.run(
        _store_heartbeat(
            database_url,
            worker_id="flight-hunter-watch-worker",
            role="watch",
            status="running",
            last_seen_at=NOW,
        )
    )

    result = asyncio.run(
        run_healthcheck(
            database_url=database_url,
            role="watch",
            max_age_seconds=300,
            clock=lambda: NOW,
        )
    )

    assert result.ok is True
    assert result.code == "ok"
    assert result.matched_workers == ("flight-hunter-watch-worker",)
    assert result.alerts == ()


def test_worker_healthcheck_fails_stale_role_lane(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    asyncio.run(
        _store_heartbeat(
            database_url,
            worker_id="flight-hunter-watch-worker",
            role="watch",
            status="running",
            last_seen_at=NOW - timedelta(minutes=10),
        )
    )

    result = asyncio.run(
        run_healthcheck(
            database_url=database_url,
            role="watch",
            max_age_seconds=300,
            clock=lambda: NOW,
        )
    )

    assert result.ok is False
    assert result.code == "worker_unhealthy"
    assert result.matched_workers == ("flight-hunter-watch-worker",)
    assert result.alerts[0].code == "worker_stale"


def test_worker_healthcheck_fails_missing_role_lane(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    asyncio.run(_create_schema(database_url))

    result = asyncio.run(
        run_healthcheck(
            database_url=database_url,
            role="telegram",
            max_age_seconds=300,
            clock=lambda: NOW,
        )
    )

    assert result.ok is False
    assert result.code == "worker_heartbeat_missing"
    assert result.matched_workers == ()


async def _store_heartbeat(
    database_url: str,
    *,
    worker_id: str,
    role: str,
    status: str,
    last_seen_at: datetime,
) -> None:
    session_factory = await _create_schema(database_url)
    async with session_factory() as session:
        await WorkerHeartbeatRepository(session).upsert(
            NewWorkerHeartbeat(
                worker_id=worker_id,
                role=role,
                status=status,
                current_phase="idle",
                started_at=NOW - timedelta(minutes=30),
                last_seen_at=last_seen_at,
            )
        )
        await session.commit()


async def _create_schema(database_url: str) -> async_sessionmaker:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    await engine.dispose()
    return async_sessionmaker(create_async_engine(database_url), expire_on_commit=False)


def _database_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'worker-healthcheck.db').as_posix()}"
