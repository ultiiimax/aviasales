import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import NewWatchScanJob, WatchScanJobRepository

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
WATCH_ID = UUID("77777777-7777-7777-7777-777777777777")
JOB_ID = UUID("88888888-8888-8888-8888-888888888888")


@pytest.mark.anyio
async def test_two_workers_claim_one_sqlite_job_once(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'claims.sqlite').as_posix()}"
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(UTC)
    async with session_factory() as session:
        await WatchScanJobRepository(session).enqueue_job(
            NewWatchScanJob(
                id=JOB_ID,
                household_id=HOUSEHOLD_ID,
                watch_id=WATCH_ID,
                idempotency_key="watch-scan:concurrency",
                status="queued",
                attempts=0,
                max_attempts=3,
                deadline_at=now + timedelta(minutes=5),
                created_at=now,
                provider_ids=("fake",),
                provider_denials={},
            )
        )
        await session.commit()

    async def claim(worker_id: str) -> tuple[UUID, ...]:
        async with session_factory() as session:
            jobs = await WatchScanJobRepository(session).claim_queued(
                now=now,
                limit=1,
                worker_id=worker_id,
            )
            await session.commit()
            return tuple(job.id for job in jobs)

    first, second = await asyncio.gather(claim("worker-a"), claim("worker-b"))
    await engine.dispose()

    assert sorted((*first, *second)) == [JOB_ID]


@pytest.mark.anyio
async def test_sqlite_writer_waits_for_short_contention(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'contention.sqlite').as_posix()}"
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(
            text("CREATE TABLE contention (id INTEGER PRIMARY KEY, value TEXT)")
        )

    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def first_writer() -> None:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("INSERT INTO contention (id, value) VALUES (1, 'first')"))
            first_started.set()
            await release_first.wait()
            await transaction.commit()

    async def second_writer() -> None:
        await first_started.wait()
        async with engine.begin() as connection:
            await connection.execute(
                text("INSERT INTO contention (id, value) VALUES (2, 'second')")
            )

    first_task = asyncio.create_task(first_writer())
    second_task = asyncio.create_task(second_writer())
    await first_started.wait()
    await asyncio.sleep(0.05)
    release_first.set()
    await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)

    async with engine.connect() as connection:
        count = (await connection.execute(text("SELECT COUNT(*) FROM contention"))).scalar_one()
    await engine.dispose()

    assert count == 2
