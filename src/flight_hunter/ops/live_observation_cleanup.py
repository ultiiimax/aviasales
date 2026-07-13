from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.application.live_observation_cleanup import LiveObservationCleanupService
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.persistence.database import create_database_engine


@dataclass(frozen=True, slots=True)
class CleanupCommandResult:
    ok: bool
    code: str
    dry_run: bool
    grants_deleted: int
    observations_deleted: int
    offers_deleted: int
    idempotency_deleted: int


async def cleanup_live_observation_state(
    *,
    database_url: str,
    dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> CleanupCommandResult:
    database_path = _sqlite_database_path(database_url)
    if database_path is not None and not database_path.exists():
        return _empty_result(code="database_missing", dry_run=dry_run)

    now = clock or (lambda: datetime.now(UTC))
    engine = create_database_engine(database_url)
    try:
        session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        service = LiveObservationCleanupService(
            session_factory=session_factory,
            clock=now,
        )
        result = await service.run_once(dry_run=dry_run)
    except SQLAlchemyError:
        return _empty_result(code="cleanup_failed", dry_run=dry_run)
    finally:
        await engine.dispose()

    return CleanupCommandResult(
        ok=True,
        code="ok",
        dry_run=dry_run,
        grants_deleted=result.grants_deleted,
        observations_deleted=result.observations_deleted,
        offers_deleted=result.offers_deleted,
        idempotency_deleted=result.idempotency_deleted,
    )


def render_cleanup_result(result: CleanupCommandResult) -> str:
    return json.dumps(
        {
            "ok": result.ok,
            "code": result.code,
            "dry_run": result.dry_run,
            "grants_deleted": result.grants_deleted,
            "observations_deleted": result.observations_deleted,
            "offers_deleted": result.offers_deleted,
            "idempotency_deleted": result.idempotency_deleted,
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean expired Flight Hunter live-observation state."
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
    database_url = args.database_url or settings.database_url
    result = asyncio.run(
        cleanup_live_observation_state(
            database_url=database_url,
            dry_run=args.dry_run,
        )
    )
    print(render_cleanup_result(result))
    return 0 if result.ok else 1


def _empty_result(*, code: str, dry_run: bool) -> CleanupCommandResult:
    return CleanupCommandResult(
        ok=False,
        code=code,
        dry_run=dry_run,
        grants_deleted=0,
        observations_deleted=0,
        offers_deleted=0,
        idempotency_deleted=0,
    )


def _sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return None
    database = url.database
    if database is None or database == "" or database == ":memory:":
        return None
    return Path(database)
