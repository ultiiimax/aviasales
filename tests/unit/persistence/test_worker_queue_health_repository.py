from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import (
    browser_observation_jobs_table,
    deal_discovery_jobs_table,
    mapper_registry,
    telegram_notification_outbox_table,
    watch_scan_jobs_table,
)
from flight_hunter.persistence.repositories import WorkerQueueHealthRepository

NOW = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)


def test_worker_queue_health_repository_aggregates_all_worker_lanes() -> None:
    records = asyncio.run(_queue_records())

    by_lane = {record.lane: record for record in records}

    assert by_lane["browser"].status_counts == {"queued": 2, "running": 1}
    assert by_lane["browser"].due_count == 1
    assert by_lane["browser"].stale_count == 1
    assert by_lane["browser"].expired_count == 1
    assert by_lane["browser"].oldest_queued_at == NOW - timedelta(minutes=30)
    assert by_lane["browser"].oldest_locked_at == NOW - timedelta(minutes=15)

    assert by_lane["watch"].status_counts == {"queued": 1, "retry_scheduled": 1}
    assert by_lane["watch"].due_count == 0
    assert by_lane["watch"].delayed_count == 1
    assert by_lane["watch"].expired_count == 1

    assert by_lane["deal"].status_counts == {"running": 1}
    assert by_lane["deal"].due_count == 0
    assert by_lane["deal"].stale_count == 0
    assert by_lane["deal"].expired_count == 1

    assert by_lane["telegram"].status_counts == {"queued": 1, "sending": 1}
    assert by_lane["telegram"].due_count == 1
    assert by_lane["telegram"].stale_count == 1
    assert by_lane["telegram"].expired_count == 0


async def _queue_records():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        await session.execute(
            insert(browser_observation_jobs_table),
            [
                _browser_job(
                    "browser-due", status="queued", created_at=NOW - timedelta(minutes=10)
                ),
                _browser_job(
                    "browser-stale",
                    status="running",
                    created_at=NOW - timedelta(minutes=20),
                    locked_at=NOW - timedelta(minutes=15),
                ),
                _browser_job(
                    "browser-expired",
                    status="queued",
                    created_at=NOW - timedelta(minutes=30),
                    expires_at=NOW - timedelta(minutes=1),
                ),
            ],
        )
        await session.execute(
            insert(watch_scan_jobs_table),
            [
                _watch_job(
                    "watch-delayed",
                    status="retry_scheduled",
                    created_at=NOW - timedelta(minutes=7),
                    next_retry_at=NOW + timedelta(minutes=5),
                ),
                _watch_job(
                    "watch-expired",
                    status="queued",
                    created_at=NOW - timedelta(minutes=12),
                    deadline_at=NOW - timedelta(seconds=1),
                ),
            ],
        )
        await session.execute(
            insert(deal_discovery_jobs_table),
            [
                _deal_job(
                    "deal-expired-running",
                    status="running",
                    created_at=NOW - timedelta(minutes=18),
                    locked_at=NOW - timedelta(minutes=12),
                    deadline_at=NOW - timedelta(seconds=1),
                ),
            ],
        )
        await session.execute(
            insert(telegram_notification_outbox_table),
            [
                _telegram_notification(
                    "telegram-due",
                    status="queued",
                    created_at=NOW - timedelta(minutes=5),
                ),
                _telegram_notification(
                    "telegram-stale",
                    status="sending",
                    created_at=NOW - timedelta(minutes=8),
                    locked_at=NOW - timedelta(minutes=9),
                ),
            ],
        )
        records = await WorkerQueueHealthRepository(session).queue_health(
            now=NOW,
            stale_after=timedelta(minutes=5),
        )
    await engine.dispose()
    return records


def _browser_job(
    job_id: str,
    *,
    status: str,
    created_at: datetime,
    locked_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": job_id,
        "household_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "source_id": "tutu",
        "search_id": f"search-{job_id}",
        "search_intent_hash": f"hash-{job_id}",
        "idempotency_key": f"idem-{job_id}",
        "grant_id": "22222222-2222-2222-2222-222222222222",
        "origin": "MOW",
        "destination": "IST",
        "departure_date": "2026-09-10",
        "return_date": "2026-09-20",
        "passengers": 1,
        "adults": 1,
        "children": 0,
        "infants": 0,
        "trip_type": "round_trip",
        "currency": "RUB",
        "status": status,
        "attempts": 0,
        "last_attempted_at": None,
        "next_retry_at": None,
        "locked_at": locked_at,
        "locked_by": "worker-a" if locked_at is not None else None,
        "created_at": created_at,
        "started_at": locked_at,
        "waiting_since": None,
        "operator_resume_requested_at": None,
        "operator_abort_requested_at": None,
        "completed_at": None,
        "expires_at": expires_at or NOW + timedelta(hours=1),
        "error_code": None,
        "error_message": None,
    }


def _watch_job(
    job_id: str,
    *,
    status: str,
    created_at: datetime,
    next_retry_at: datetime | None = None,
    deadline_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": job_id,
        "household_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "watch_id": "33333333-3333-3333-3333-333333333333",
        "idempotency_key": f"idem-{job_id}",
        "status": status,
        "attempts": 0,
        "max_attempts": 3,
        "next_retry_at": next_retry_at,
        "locked_at": None,
        "locked_by": None,
        "deadline_at": deadline_at or NOW + timedelta(minutes=20),
        "created_at": created_at,
        "started_at": None,
        "completed_at": None,
        "provider_ids": "fake",
        "provider_denials": "{}",
        "error_code": None,
        "error_message": None,
    }


def _deal_job(
    job_id: str,
    *,
    status: str,
    created_at: datetime,
    locked_at: datetime | None = None,
    deadline_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": job_id,
        "household_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "search_id": f"search-{job_id}",
        "idempotency_key": f"idem-{job_id}",
        "status": status,
        "attempts": 1,
        "max_attempts": 3,
        "next_retry_at": None,
        "locked_at": locked_at,
        "locked_by": "worker-a" if locked_at is not None else None,
        "deadline_at": deadline_at or NOW + timedelta(minutes=20),
        "created_at": created_at,
        "started_at": locked_at,
        "completed_at": None,
        "search_intent_json": "{}",
        "limit": 5,
        "result_count": 0,
        "error_code": None,
        "error_message": None,
    }


def _telegram_notification(
    notification_id: str,
    *,
    status: str,
    created_at: datetime,
    locked_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "id": notification_id,
        "household_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "user_id": "11111111-1111-1111-1111-111111111111",
        "chat_id": 42,
        "kind": "watch_alert",
        "dedupe_key": f"dedupe-{notification_id}",
        "payload_json": "{}",
        "status": status,
        "attempts": 0,
        "next_retry_at": None,
        "locked_at": locked_at,
        "locked_by": "worker-a" if locked_at is not None else None,
        "created_at": created_at,
        "sent_at": None,
        "error_code": None,
        "error_message": None,
    }
