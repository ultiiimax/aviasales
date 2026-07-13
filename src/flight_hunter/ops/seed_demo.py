from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from flight_hunter.application.watch_service import CreateWatchCommand, WatchService
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.repositories import HouseholdWatchRepository

DEMO_HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DEMO_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
DEMO_WATCH_ID = UUID("77777777-7777-7777-7777-777777777777")


@dataclass(frozen=True, slots=True)
class SeedDemoResult:
    ok: bool
    code: str
    household_id: UUID
    user_id: UUID
    watch_id: UUID
    created: bool


def main() -> None:
    parser = argparse.ArgumentParser(prog="flight-hunter-seed-demo")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
    result = asyncio.run(seed_demo(database_url=args.database_url or settings.database_url))
    print(
        json.dumps(
            {
                "ok": result.ok,
                "code": result.code,
                "household_id": str(result.household_id),
                "user_id": str(result.user_id),
                "watch_id": str(result.watch_id),
                "created": result.created,
            },
            ensure_ascii=False,
        )
    )


async def seed_demo(*, database_url: str) -> SeedDemoResult:
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        repository = HouseholdWatchRepository(session)
        existing = await repository.get_watch(DEMO_HOUSEHOLD_ID, DEMO_WATCH_ID)
        if existing is None:
            service = WatchService(
                repository,
                clock=lambda: datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
                id_factory=lambda: DEMO_WATCH_ID,
            )
            await service.create_watch(
                CreateWatchCommand(
                    household_id=DEMO_HOUSEHOLD_ID,
                    owner_user_id=DEMO_USER_ID,
                    origin="MOW",
                    destination="IST",
                    departure_date="2026-09-10",
                    return_date="2026-09-20",
                )
            )
            await session.commit()
            created = True
        else:
            created = False
    await engine.dispose()
    return SeedDemoResult(
        ok=True,
        code="seeded",
        household_id=DEMO_HOUSEHOLD_ID,
        user_id=DEMO_USER_ID,
        watch_id=DEMO_WATCH_ID,
        created=created,
    )
