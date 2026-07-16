from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flight_hunter.application.worker_health import (
    AgentOperationalHealthItem,
    WorkerControlState,
    WorkerHealthAlert,
    WorkerHealthItem,
    WorkerHealthSnapshot,
    WorkerQueueHealthItem,
    render_worker_health_prometheus,
)

NOW = datetime(2026, 6, 29, 18, 0, tzinfo=UTC)


def test_worker_health_prometheus_omits_job_ids_and_summaries() -> None:
    snapshot = WorkerHealthSnapshot(
        checked_at=NOW,
        control=WorkerControlState(
            drain_requested=True,
            reason="deploy",
            requested_at=NOW - timedelta(minutes=5),
            cleared_at=None,
            updated_at=NOW - timedelta(minutes=5),
        ),
        workers=(
            WorkerHealthItem(
                worker_id='worker-"a"\n',
                role="flight_hunter_worker",
                status="running",
                effective_status="stale",
                current_phase="sending",
                current_job_kind="telegram",
                current_job_id="job-secret-123",
                started_at=NOW - timedelta(hours=1),
                last_seen_at=NOW - timedelta(seconds=42),
                stopping_at=None,
                stopped_at=None,
                last_summary={"telegram_token": "secret-value"},
            ),
        ),
        queues=(
            WorkerQueueHealthItem(
                lane="telegram",
                status_counts={"queued": 2, "sending": 1},
                due_count=2,
                delayed_count=3,
                stale_count=1,
                expired_count=0,
                oldest_queued_age_seconds=900,
                oldest_locked_age_seconds=720,
                warning_level="stale",
            ),
        ),
        alerts=(
            WorkerHealthAlert(
                severity="critical",
                code="queue_stale_lock",
                subject_kind="queue",
                subject_id="telegram",
                message="telegram queue has stale locked work",
            ),
        ),
        agent=AgentOperationalHealthItem(
            operation_status_counts={"pending": 2, "leased": 1},
            run_status_counts={"running": 1, "partial": 2},
            due_operation_count=2,
            oldest_due_operation_age_seconds=180,
            circuit_state_counts={"closed": 1, "open": 1},
            estimated_logical_operations=12,
            actual_logical_operations=9,
            estimated_http_attempts=24,
            actual_http_attempts=15,
            confirmed_candidates=4,
            provider_denials=2,
            terminal_run_count=2,
            terminal_run_duration_seconds=17.5,
            recovered_operations=3,
        ),
    )

    metrics = render_worker_health_prometheus(snapshot)

    assert 'worker_id="worker-\\"a\\"\\n"' in metrics
    assert "flight_hunter_worker_drain_requested 1" in metrics
    assert (
        'flight_hunter_worker_last_seen_age_seconds{worker_id="worker-\\"a\\"\\n",'
        'role="flight_hunter_worker"} 42'
    ) in metrics
    assert 'flight_hunter_worker_queue_items{lane="telegram",state="status:queued"} 2' in metrics
    assert 'flight_hunter_worker_queue_items{lane="telegram",state="stale"} 1' in metrics
    assert 'flight_hunter_worker_queue_age_seconds{lane="telegram",age="locked"} 720' in metrics
    assert (
        'flight_hunter_worker_alert_active{severity="critical",code="queue_stale_lock",'
        'subject_kind="queue",subject_id="telegram"} 1'
    ) in metrics
    assert 'flight_hunter_agent_operation_items{state="pending"} 2' in metrics
    assert 'flight_hunter_agent_run_items{status="partial"} 2' in metrics
    assert "flight_hunter_agent_oldest_due_operation_age_seconds 180" in metrics
    assert 'flight_hunter_agent_circuit_items{state="open"} 1' in metrics
    assert 'flight_hunter_agent_logical_operations{kind="estimated"} 12' in metrics
    assert 'flight_hunter_agent_logical_operations{kind="actual"} 9' in metrics
    assert 'flight_hunter_agent_http_attempts{kind="estimated"} 24' in metrics
    assert 'flight_hunter_agent_http_attempts{kind="actual"} 15' in metrics
    assert "flight_hunter_agent_confirmed_candidates 4" in metrics
    assert "flight_hunter_agent_provider_denials 2" in metrics
    assert "flight_hunter_agent_recovered_operations 3" in metrics
    assert "flight_hunter_agent_terminal_run_duration_seconds_count 2" in metrics
    assert "flight_hunter_agent_terminal_run_duration_seconds_sum 17.5" in metrics
    assert "job-secret-123" not in metrics
    assert "secret-value" not in metrics
