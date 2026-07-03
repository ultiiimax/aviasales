from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.api.app import create_app
from flight_hunter.persistence.models import (
    browser_observation_jobs_table,
    deal_discovery_jobs_table,
    mapper_registry,
    telegram_notification_outbox_table,
)
from flight_hunter.persistence.repositories import (
    NewWorkerHeartbeat,
    WorkerControlRepository,
    WorkerHeartbeatRepository,
)

OLD = datetime(2020, 1, 1, 12, 0, tzinfo=UTC)
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_admin_worker_health_returns_durable_heartbeats_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "secret-value")
    session_factory = asyncio.run(_session_factory_with_heartbeats())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.get("/api/v1/admin/workers/health")

    assert response.status_code == 200
    body = response.json()
    assert body["control"]["drain_requested"] is True
    assert body["control"]["reason"] == "deploy window"
    workers = {worker["worker_id"]: worker for worker in body["workers"]}
    assert workers["worker-a"]["status"] == "running"
    assert workers["worker-a"]["effective_status"] == "stale"
    assert workers["worker-a"]["current_job_kind"] == "browser_observation"
    assert workers["worker-a"]["current_job_id"] == "job-123"
    assert workers["worker-a"]["last_summary"]["browser_jobs_seen"] == 1
    assert workers["worker-b"]["effective_status"] == "stopped"
    queues = {queue["lane"]: queue for queue in body["queues"]}
    assert queues["browser"]["due_count"] == 1
    assert queues["browser"]["warning_level"] == "drained"
    assert queues["telegram"]["stale_count"] == 1
    assert queues["telegram"]["warning_level"] == "stale"
    alerts = {(alert["code"], alert["subject_id"]): alert for alert in body["alerts"]}
    assert alerts[("worker_stale", "worker-a")]["severity"] == "critical"
    assert alerts[("queue_stale_lock", "telegram")]["severity"] == "critical"
    assert ("queue_backlog", "browser") not in alerts
    assert "secret-value" not in str(body)


def test_admin_worker_metrics_returns_prometheus_text_without_job_ids_or_summaries(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TRAVELPAYOUTS_API_TOKEN", "secret-value")
    session_factory = asyncio.run(_session_factory_with_heartbeats())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.get("/api/v1/admin/workers/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "flight_hunter_worker_health_checked_at_seconds" in text
    assert 'flight_hunter_worker_info{worker_id="worker-a"' in text
    assert 'flight_hunter_worker_queue_items{lane="telegram",state="stale"} 1' in text
    assert (
        'flight_hunter_worker_alert_active{severity="critical",code="queue_stale_lock",'
        'subject_kind="queue",subject_id="telegram"} 1'
    ) in text
    assert "job-123" not in text
    assert "secret-value" not in text
    assert "last_summary" not in text


def test_admin_worker_control_update_requires_auth_context() -> None:
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.patch(
        "/api/v1/admin/workers/control",
        json={"drain_requested": True, "reason": "deploy window"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "auth_context_missing"


def test_admin_worker_health_alerts_on_backlog_and_deadline_risk() -> None:
    session_factory = asyncio.run(_session_factory_with_backlog_and_deadline_risk())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.get("/api/v1/admin/workers/health")

    assert response.status_code == 200
    body = response.json()
    queues = {queue["lane"]: queue for queue in body["queues"]}
    assert queues["browser"]["warning_level"] == "backlog"
    assert queues["deal"]["warning_level"] == "deadline_risk"
    alerts = {(alert["code"], alert["subject_id"]): alert for alert in body["alerts"]}
    assert alerts[("queue_backlog", "browser")]["severity"] == "warning"
    assert alerts[("queue_deadline_risk", "deal")]["severity"] == "warning"


def test_admin_worker_health_paginates_worker_heartbeats() -> None:
    session_factory = asyncio.run(_session_factory_with_heartbeats())
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.get("/api/v1/admin/workers/health?workers_limit=1&workers_offset=1")
    metrics_response = client.get("/api/v1/admin/workers/metrics?workers_limit=1&workers_offset=1")

    assert response.status_code == 200
    body = response.json()
    assert body["workers_limit"] == 1
    assert body["workers_offset"] == 1
    assert [worker["worker_id"] for worker in body["workers"]] == ["worker-a"]
    assert metrics_response.status_code == 200
    assert 'flight_hunter_worker_info{worker_id="worker-a"' in metrics_response.text
    assert 'flight_hunter_worker_info{worker_id="worker-b"' not in metrics_response.text


def test_admin_worker_control_update_sets_state_and_audit() -> None:
    session_factory = asyncio.run(_session_factory())
    client = TestClient(create_app(watch_session_factory=session_factory))
    headers = _headers()

    enable_response = client.patch(
        "/api/v1/admin/workers/control",
        json={"drain_requested": True, "reason": "deploy window"},
        headers=headers,
    )
    health_response = client.get("/api/v1/admin/workers/health")
    clear_response = client.patch(
        "/api/v1/admin/workers/control",
        json={"drain_requested": False},
        headers=headers,
    )
    audit_response = client.get("/api/v1/admin/audit-events", headers=headers)

    assert enable_response.status_code == 200
    assert enable_response.json()["drain_requested"] is True
    assert enable_response.json()["reason"] == "deploy window"
    assert health_response.json()["control"]["drain_requested"] is True
    assert clear_response.status_code == 200
    assert clear_response.json()["drain_requested"] is False
    assert clear_response.json()["reason"] is None
    actions = [event["action"] for event in audit_response.json()["audit_events"]]
    assert actions == ["worker.drain_cleared", "worker.drain_enabled"]


async def _session_factory_with_heartbeats():
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = WorkerHeartbeatRepository(session)
        await repository.upsert(
            NewWorkerHeartbeat(
                worker_id="worker-a",
                role="flight_hunter_worker",
                status="running",
                current_phase="claiming",
                current_job_kind="browser_observation",
                current_job_id="job-123",
                started_at=OLD - timedelta(minutes=20),
                last_seen_at=OLD - timedelta(minutes=10),
                last_summary_json='{"browser_jobs_seen": 1}',
            )
        )
        await repository.upsert(
            NewWorkerHeartbeat(
                worker_id="worker-b",
                role="flight_hunter_worker",
                status="stopped",
                current_phase="stopped",
                started_at=OLD - timedelta(minutes=3),
                last_seen_at=OLD - timedelta(minutes=1),
                stopped_at=OLD - timedelta(minutes=1),
                last_summary_json='{"browser_jobs_seen": 0}',
            )
        )
        await WorkerControlRepository(session).set_drain(
            drain_requested=True,
            reason="deploy window",
            requested_by_household_id=HOUSEHOLD_ID,
            requested_by_user_id=USER_ID,
            changed_at=OLD,
        )
        await session.execute(
            insert(browser_observation_jobs_table).values(
                id="browser-health",
                household_id=str(HOUSEHOLD_ID),
                user_id=str(USER_ID),
                source_id="tutu",
                search_id="search-worker-health",
                search_intent_hash="hash-worker-health",
                idempotency_key="idem-browser-health",
                grant_id="22222222-2222-2222-2222-222222222222",
                origin="MOW",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                passengers=1,
                adults=1,
                children=0,
                infants=0,
                trip_type="round_trip",
                currency="RUB",
                status="queued",
                attempts=0,
                last_attempted_at=None,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                created_at=OLD - timedelta(minutes=15),
                started_at=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                completed_at=None,
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
        )
        await session.execute(
            insert(telegram_notification_outbox_table).values(
                id="telegram-health",
                household_id=str(HOUSEHOLD_ID),
                user_id=str(USER_ID),
                chat_id=42,
                kind="watch_alert",
                dedupe_key="dedupe-telegram-health",
                payload_json="{}",
                status="sending",
                attempts=1,
                next_retry_at=None,
                locked_at=OLD - timedelta(minutes=12),
                locked_by="worker-a",
                created_at=OLD - timedelta(minutes=20),
                sent_at=None,
                error_code=None,
                error_message=None,
            )
        )
        await session.commit()
    return session_factory


async def _session_factory_with_backlog_and_deadline_risk():
    session_factory = await _session_factory()
    async with session_factory() as session:
        await session.execute(
            insert(browser_observation_jobs_table).values(
                id="browser-backlog",
                household_id=str(HOUSEHOLD_ID),
                user_id=str(USER_ID),
                source_id="tutu",
                search_id="search-browser-backlog",
                search_intent_hash="hash-browser-backlog",
                idempotency_key="idem-browser-backlog",
                grant_id="22222222-2222-2222-2222-222222222222",
                origin="MOW",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                passengers=1,
                adults=1,
                children=0,
                infants=0,
                trip_type="round_trip",
                currency="RUB",
                status="queued",
                attempts=0,
                last_attempted_at=None,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                created_at=OLD - timedelta(minutes=20),
                started_at=None,
                waiting_since=None,
                operator_resume_requested_at=None,
                operator_abort_requested_at=None,
                completed_at=None,
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
        )
        await session.execute(
            insert(deal_discovery_jobs_table).values(
                id="deal-deadline-risk",
                household_id=str(HOUSEHOLD_ID),
                user_id=str(USER_ID),
                search_id="search-deal-deadline-risk",
                idempotency_key="idem-deal-deadline-risk",
                status="queued",
                attempts=0,
                max_attempts=3,
                next_retry_at=None,
                locked_at=None,
                locked_by=None,
                deadline_at=OLD - timedelta(seconds=1),
                created_at=OLD - timedelta(minutes=30),
                started_at=None,
                completed_at=None,
                search_intent_json="{}",
                limit=5,
                result_count=0,
                error_code=None,
                error_message=None,
            )
        )
        await session.commit()
    return session_factory


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _headers() -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": str(HOUSEHOLD_ID),
        "X-Flight-Hunter-User-Id": str(USER_ID),
    }
