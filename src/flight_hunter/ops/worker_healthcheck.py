from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker

from flight_hunter.application.worker_health import WorkerHealthAlert, WorkerHealthService
from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.repositories import (
    WorkerControlRepository,
    WorkerHeartbeatRepository,
    WorkerQueueHealthRepository,
)


@dataclass(frozen=True, slots=True)
class WorkerHealthcheckResult:
    ok: bool
    code: str
    checked_at: datetime
    matched_workers: tuple[str, ...]
    alerts: tuple[WorkerHealthAlert, ...]

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "code": self.code,
                "checked_at": self.checked_at.isoformat(),
                "matched_workers": list(self.matched_workers),
                "alerts": [
                    {
                        "severity": alert.severity,
                        "code": alert.code,
                        "subject_kind": alert.subject_kind,
                        "subject_id": alert.subject_id,
                        "message": alert.message,
                    }
                    for alert in self.alerts
                ],
            },
            indent=2,
        )


async def run_healthcheck(
    *,
    database_url: str,
    role: str | None = None,
    worker_id: str | None = None,
    max_age_seconds: int = 300,
    clock: Callable[[], datetime] | None = None,
) -> WorkerHealthcheckResult:
    now = clock() if clock is not None else datetime.now(UTC)
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            snapshot = await WorkerHealthService(
                heartbeats=WorkerHeartbeatRepository(session),
                queues=WorkerQueueHealthRepository(session),
                control=WorkerControlRepository(session),
                clock=lambda: now,
                stale_after=timedelta(seconds=max_age_seconds),
            ).snapshot(limit=200)
    finally:
        await engine.dispose()

    workers = snapshot.workers
    if worker_id is not None:
        workers = tuple(worker for worker in workers if worker.worker_id == worker_id)
    if role is not None:
        workers = tuple(worker for worker in workers if worker.role == role)

    relevant_alerts = tuple(
        alert
        for alert in snapshot.alerts
        if _alert_matches(
            alert, role=role, worker_ids=tuple(worker.worker_id for worker in workers)
        )
    )
    matched_worker_ids = tuple(worker.worker_id for worker in workers)
    if not workers:
        return WorkerHealthcheckResult(
            ok=False,
            code="worker_heartbeat_missing",
            checked_at=now,
            matched_workers=(),
            alerts=relevant_alerts,
        )
    if any(worker.effective_status in {"failed", "stale"} for worker in workers):
        return WorkerHealthcheckResult(
            ok=False,
            code="worker_unhealthy",
            checked_at=now,
            matched_workers=matched_worker_ids,
            alerts=relevant_alerts,
        )
    if any(alert.severity == "critical" for alert in relevant_alerts):
        return WorkerHealthcheckResult(
            ok=False,
            code="worker_critical_alert",
            checked_at=now,
            matched_workers=matched_worker_ids,
            alerts=relevant_alerts,
        )
    return WorkerHealthcheckResult(
        ok=True,
        code="ok",
        checked_at=now,
        matched_workers=matched_worker_ids,
        alerts=relevant_alerts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="flight-hunter-worker-healthcheck")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--role", default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--max-age-seconds", type=int, default=300)
    args = parser.parse_args()

    load_env_file()
    settings = AppSettings.from_env()
    result = asyncio.run(
        run_healthcheck(
            database_url=args.database_url or settings.database_url,
            role=args.role,
            worker_id=args.worker_id,
            max_age_seconds=max(1, args.max_age_seconds),
        )
    )
    print(result.to_json())
    if not result.ok:
        raise SystemExit(1)


def _alert_matches(
    alert: WorkerHealthAlert,
    *,
    role: str | None,
    worker_ids: tuple[str, ...],
) -> bool:
    if alert.subject_kind == "worker":
        return not worker_ids or alert.subject_id in worker_ids
    if alert.subject_kind == "queue":
        return role is None or alert.subject_id == role
    return role is None
