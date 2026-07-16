from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from flight_hunter.persistence.agent_repositories import (
    AgentOperationalHealthRecord,
    AgentOperationalHealthRepository,
)
from flight_hunter.persistence.repositories import (
    AuditEventRepository,
    NewAuditEvent,
    WorkerControlRecord,
    WorkerControlRepository,
    WorkerHeartbeatRecord,
    WorkerHeartbeatRepository,
    WorkerQueueHealthRecord,
    WorkerQueueHealthRepository,
)

WORKER_CONTROL_AUDIT_ENTITY_ID = UUID("00000000-0000-0000-0000-000000000090")


@dataclass(frozen=True, slots=True)
class WorkerControlState:
    drain_requested: bool
    reason: str | None
    requested_at: datetime | None
    cleared_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkerHealthItem:
    worker_id: str
    role: str
    status: str
    effective_status: str
    current_phase: str
    current_job_kind: str | None
    current_job_id: str | None
    started_at: datetime
    last_seen_at: datetime
    stopping_at: datetime | None
    stopped_at: datetime | None
    last_summary: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class WorkerQueueHealthItem:
    lane: str
    status_counts: Mapping[str, int]
    due_count: int
    delayed_count: int
    stale_count: int
    expired_count: int
    oldest_queued_age_seconds: int | None
    oldest_locked_age_seconds: int | None
    warning_level: str


@dataclass(frozen=True, slots=True)
class WorkerHealthAlert:
    severity: str
    code: str
    subject_kind: str
    subject_id: str
    message: str


@dataclass(frozen=True, slots=True)
class AgentOperationalHealthItem:
    operation_status_counts: Mapping[str, int]
    run_status_counts: Mapping[str, int]
    due_operation_count: int
    oldest_due_operation_age_seconds: int | None
    circuit_state_counts: Mapping[str, int]
    estimated_logical_operations: int
    actual_logical_operations: int
    estimated_http_attempts: int
    actual_http_attempts: int
    confirmed_candidates: int
    provider_denials: int
    terminal_run_count: int
    terminal_run_duration_seconds: float
    recovered_operations: int = 0


@dataclass(frozen=True, slots=True)
class WorkerHealthSnapshot:
    checked_at: datetime
    control: WorkerControlState
    workers: tuple[WorkerHealthItem, ...]
    queues: tuple[WorkerQueueHealthItem, ...]
    alerts: tuple[WorkerHealthAlert, ...]
    agent: AgentOperationalHealthItem | None = None


class WorkerHealthService:
    def __init__(
        self,
        *,
        heartbeats: WorkerHeartbeatRepository,
        queues: WorkerQueueHealthRepository | None = None,
        control: WorkerControlRepository | None = None,
        agent_health: AgentOperationalHealthRepository | None = None,
        clock: Callable[[], datetime] | None = None,
        stale_after: timedelta = timedelta(minutes=5),
    ) -> None:
        self._heartbeats = heartbeats
        self._queues = queues
        self._control = control
        self._agent_health = agent_health
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stale_after = stale_after

    async def snapshot(self, *, limit: int = 20, offset: int = 0) -> WorkerHealthSnapshot:
        now = self._clock()
        heartbeats = await self._heartbeats.list_recent(limit=limit, offset=offset)
        control = await self._control.get_state() if self._control is not None else None
        queue_records = (
            await self._queues.queue_health(now=now, stale_after=self._stale_after)
            if self._queues is not None
            else ()
        )
        agent_record = (
            await self._agent_health.snapshot(now=now) if self._agent_health is not None else None
        )
        control_state = _worker_control_state(control)
        workers = tuple(
            _worker_item(record, now=now, stale_after=self._stale_after) for record in heartbeats
        )
        queues = tuple(
            _queue_item(
                record,
                now=now,
                drain_requested=control_state.drain_requested,
            )
            for record in queue_records
        )
        return WorkerHealthSnapshot(
            checked_at=now,
            control=control_state,
            workers=workers,
            queues=queues,
            alerts=_worker_health_alerts(workers=workers, queues=queues),
            agent=_agent_health_item(agent_record, now=now),
        )


def render_worker_health_prometheus(snapshot: WorkerHealthSnapshot) -> str:
    lines = [
        "# HELP flight_hunter_worker_health_checked_at_seconds Snapshot Unix timestamp.",
        "# TYPE flight_hunter_worker_health_checked_at_seconds gauge",
        "flight_hunter_worker_health_checked_at_seconds "
        f"{_metric_number(snapshot.checked_at.timestamp())}",
        "# HELP flight_hunter_worker_drain_requested Whether worker drain mode is active.",
        "# TYPE flight_hunter_worker_drain_requested gauge",
        f"flight_hunter_worker_drain_requested {_metric_number(snapshot.control.drain_requested)}",
        "# HELP flight_hunter_worker_info Worker heartbeat state without job ids or summaries.",
        "# TYPE flight_hunter_worker_info gauge",
    ]
    for worker in snapshot.workers:
        lines.append(
            "flight_hunter_worker_info"
            + _metric_labels(
                worker_id=worker.worker_id,
                role=worker.role,
                status=worker.status,
                effective_status=worker.effective_status,
                phase=worker.current_phase,
            )
            + " 1"
        )
    lines.extend(
        [
            "# HELP flight_hunter_worker_last_seen_age_seconds Age of the last worker heartbeat.",
            "# TYPE flight_hunter_worker_last_seen_age_seconds gauge",
        ]
    )
    for worker in snapshot.workers:
        lines.append(
            "flight_hunter_worker_last_seen_age_seconds"
            + _metric_labels(worker_id=worker.worker_id, role=worker.role)
            + f" {_metric_number(_age_seconds(worker.last_seen_at, now=snapshot.checked_at) or 0)}"
        )
    lines.extend(
        [
            "# HELP flight_hunter_worker_queue_items Queue item counts by lane and status class.",
            "# TYPE flight_hunter_worker_queue_items gauge",
        ]
    )
    for queue in snapshot.queues:
        for status, count in sorted(queue.status_counts.items()):
            lines.append(
                "flight_hunter_worker_queue_items"
                + _metric_labels(lane=queue.lane, state=f"status:{status}")
                + f" {_metric_number(count)}"
            )
        for state, count in (
            ("due", queue.due_count),
            ("delayed", queue.delayed_count),
            ("stale", queue.stale_count),
            ("expired", queue.expired_count),
        ):
            lines.append(
                "flight_hunter_worker_queue_items"
                + _metric_labels(lane=queue.lane, state=state)
                + f" {_metric_number(count)}"
            )
    lines.extend(
        [
            "# HELP flight_hunter_worker_queue_age_seconds Oldest queue item age by lane.",
            "# TYPE flight_hunter_worker_queue_age_seconds gauge",
        ]
    )
    for queue in snapshot.queues:
        if queue.oldest_queued_age_seconds is not None:
            lines.append(
                "flight_hunter_worker_queue_age_seconds"
                + _metric_labels(lane=queue.lane, age="queued")
                + f" {_metric_number(queue.oldest_queued_age_seconds)}"
            )
        if queue.oldest_locked_age_seconds is not None:
            lines.append(
                "flight_hunter_worker_queue_age_seconds"
                + _metric_labels(lane=queue.lane, age="locked")
                + f" {_metric_number(queue.oldest_locked_age_seconds)}"
            )
    lines.extend(
        [
            "# HELP flight_hunter_worker_alert_active Active worker or queue alert.",
            "# TYPE flight_hunter_worker_alert_active gauge",
        ]
    )
    for alert in snapshot.alerts:
        lines.append(
            "flight_hunter_worker_alert_active"
            + _metric_labels(
                severity=alert.severity,
                code=alert.code,
                subject_kind=alert.subject_kind,
                subject_id=alert.subject_id,
            )
            + " 1"
        )
    if snapshot.agent is not None:
        agent = snapshot.agent
        lines.extend(
            [
                "# HELP flight_hunter_agent_operation_items Durable agent operations by state.",
                "# TYPE flight_hunter_agent_operation_items gauge",
            ]
        )
        for state, count in sorted(agent.operation_status_counts.items()):
            lines.append(
                "flight_hunter_agent_operation_items"
                + _metric_labels(state=state)
                + f" {_metric_number(count)}"
            )
        lines.extend(
            [
                "# HELP flight_hunter_agent_run_items Durable agent runs by status.",
                "# TYPE flight_hunter_agent_run_items gauge",
            ]
        )
        for status, count in sorted(agent.run_status_counts.items()):
            lines.append(
                "flight_hunter_agent_run_items"
                + _metric_labels(status=status)
                + f" {_metric_number(count)}"
            )
        if agent.oldest_due_operation_age_seconds is not None:
            lines.extend(
                [
                    "# HELP flight_hunter_agent_oldest_due_operation_age_seconds "
                    "Age of the oldest due agent operation.",
                    "# TYPE flight_hunter_agent_oldest_due_operation_age_seconds gauge",
                    "flight_hunter_agent_oldest_due_operation_age_seconds "
                    f"{_metric_number(agent.oldest_due_operation_age_seconds)}",
                ]
            )
        lines.extend(
            [
                "# HELP flight_hunter_agent_circuit_items Agent provider circuits by state.",
                "# TYPE flight_hunter_agent_circuit_items gauge",
            ]
        )
        for state, count in sorted(agent.circuit_state_counts.items()):
            lines.append(
                "flight_hunter_agent_circuit_items"
                + _metric_labels(state=state)
                + f" {_metric_number(count)}"
            )
        lines.extend(
            [
                "# HELP flight_hunter_agent_logical_operations "
                "Approved and consumed logical operations.",
                "# TYPE flight_hunter_agent_logical_operations gauge",
                "flight_hunter_agent_logical_operations"
                + _metric_labels(kind="estimated")
                + f" {_metric_number(agent.estimated_logical_operations)}",
                "flight_hunter_agent_logical_operations"
                + _metric_labels(kind="actual")
                + f" {_metric_number(agent.actual_logical_operations)}",
                "# HELP flight_hunter_agent_http_attempts Approved and consumed HTTP attempts.",
                "# TYPE flight_hunter_agent_http_attempts gauge",
                "flight_hunter_agent_http_attempts"
                + _metric_labels(kind="estimated")
                + f" {_metric_number(agent.estimated_http_attempts)}",
                "flight_hunter_agent_http_attempts"
                + _metric_labels(kind="actual")
                + f" {_metric_number(agent.actual_http_attempts)}",
                "# HELP flight_hunter_agent_confirmed_candidates "
                "Confirmed candidate evidence count.",
                "# TYPE flight_hunter_agent_confirmed_candidates gauge",
                f"flight_hunter_agent_confirmed_candidates {agent.confirmed_candidates}",
                "# HELP flight_hunter_agent_provider_denials Durable provider denial count.",
                "# TYPE flight_hunter_agent_provider_denials gauge",
                f"flight_hunter_agent_provider_denials {agent.provider_denials}",
                "# HELP flight_hunter_agent_recovered_operations "
                "Durable expired operation lease recovery count.",
                "# TYPE flight_hunter_agent_recovered_operations gauge",
                f"flight_hunter_agent_recovered_operations {agent.recovered_operations}",
                "# HELP flight_hunter_agent_terminal_run_duration_seconds "
                "Durable terminal agent run duration summary.",
                "# TYPE flight_hunter_agent_terminal_run_duration_seconds summary",
                "flight_hunter_agent_terminal_run_duration_seconds_count "
                f"{agent.terminal_run_count}",
                "flight_hunter_agent_terminal_run_duration_seconds_sum "
                f"{_metric_number(agent.terminal_run_duration_seconds)}",
            ]
        )
    return "\n".join(lines) + "\n"


class WorkerControlService:
    def __init__(
        self,
        *,
        control: WorkerControlRepository,
        audit: AuditEventRepository,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._control = control
        self._audit = audit
        self._clock = clock or (lambda: datetime.now(UTC))

    async def set_drain(
        self,
        *,
        drain_requested: bool,
        reason: str | None,
        actor_household_id: UUID,
        actor_user_id: UUID,
    ) -> WorkerControlState:
        changed_at = self._clock()
        record = await self._control.set_drain(
            drain_requested=drain_requested,
            reason=reason,
            requested_by_household_id=actor_household_id,
            requested_by_user_id=actor_user_id,
            changed_at=changed_at,
        )
        await self._audit.add_event(
            NewAuditEvent(
                id=uuid4(),
                household_id=actor_household_id,
                actor_user_id=actor_user_id,
                action="worker.drain_enabled" if drain_requested else "worker.drain_cleared",
                entity_type="worker_control",
                entity_id=WORKER_CONTROL_AUDIT_ENTITY_ID,
                summary="worker drain enabled" if drain_requested else "worker drain cleared",
                created_at=changed_at,
            )
        )
        return _worker_control_state(record)


def _worker_item(
    record: WorkerHeartbeatRecord,
    *,
    now: datetime,
    stale_after: timedelta,
) -> WorkerHealthItem:
    return WorkerHealthItem(
        worker_id=record.worker_id,
        role=record.role,
        status=record.status,
        effective_status=_effective_status(record, now=now, stale_after=stale_after),
        current_phase=record.current_phase,
        current_job_kind=record.current_job_kind,
        current_job_id=record.current_job_id,
        started_at=record.started_at,
        last_seen_at=record.last_seen_at,
        stopping_at=record.stopping_at,
        stopped_at=record.stopped_at,
        last_summary=_loads_summary(record.last_summary_json),
    )


def _worker_control_state(record: WorkerControlRecord | None) -> WorkerControlState:
    if record is None:
        return WorkerControlState(
            drain_requested=False,
            reason=None,
            requested_at=None,
            cleared_at=None,
            updated_at=None,
        )
    return WorkerControlState(
        drain_requested=record.drain_requested,
        reason=record.reason,
        requested_at=record.requested_at,
        cleared_at=record.cleared_at,
        updated_at=record.updated_at,
    )


def _queue_item(
    record: WorkerQueueHealthRecord,
    *,
    now: datetime,
    drain_requested: bool,
) -> WorkerQueueHealthItem:
    return WorkerQueueHealthItem(
        lane=record.lane,
        status_counts=record.status_counts,
        due_count=record.due_count,
        delayed_count=record.delayed_count,
        stale_count=record.stale_count,
        expired_count=record.expired_count,
        oldest_queued_age_seconds=_age_seconds(record.oldest_queued_at, now=now),
        oldest_locked_age_seconds=_age_seconds(record.oldest_locked_at, now=now),
        warning_level=_queue_warning_level(record, drain_requested=drain_requested),
    )


def _agent_health_item(
    record: AgentOperationalHealthRecord | None,
    *,
    now: datetime,
) -> AgentOperationalHealthItem | None:
    if record is None:
        return None
    return AgentOperationalHealthItem(
        operation_status_counts=record.operation_status_counts,
        run_status_counts=record.run_status_counts,
        due_operation_count=record.due_operation_count,
        oldest_due_operation_age_seconds=_age_seconds(
            record.oldest_due_operation_at,
            now=now,
        ),
        circuit_state_counts=record.circuit_state_counts,
        estimated_logical_operations=record.estimated_logical_operations,
        actual_logical_operations=record.actual_logical_operations,
        estimated_http_attempts=record.estimated_http_attempts,
        actual_http_attempts=record.actual_http_attempts,
        confirmed_candidates=record.confirmed_candidates,
        provider_denials=record.provider_denials,
        terminal_run_count=record.terminal_run_count,
        terminal_run_duration_seconds=record.terminal_run_duration_seconds,
        recovered_operations=record.recovered_operations,
    )


def _queue_warning_level(
    record: WorkerQueueHealthRecord,
    *,
    drain_requested: bool,
) -> str:
    if record.stale_count > 0:
        return "stale"
    if record.expired_count > 0:
        return "deadline_risk"
    if drain_requested:
        return "drained"
    if record.due_count > 0:
        return "backlog"
    return "ok"


def _worker_health_alerts(
    *,
    workers: tuple[WorkerHealthItem, ...],
    queues: tuple[WorkerQueueHealthItem, ...],
) -> tuple[WorkerHealthAlert, ...]:
    alerts: list[WorkerHealthAlert] = []
    for worker in workers:
        if worker.effective_status == "stale":
            alerts.append(
                WorkerHealthAlert(
                    severity="critical",
                    code="worker_stale",
                    subject_kind="worker",
                    subject_id=worker.worker_id,
                    message=f"worker {worker.worker_id} has stale heartbeat",
                )
            )
        elif worker.effective_status == "failed":
            alerts.append(
                WorkerHealthAlert(
                    severity="critical",
                    code="worker_failed",
                    subject_kind="worker",
                    subject_id=worker.worker_id,
                    message=f"worker {worker.worker_id} reported failed status",
                )
            )
    for queue in queues:
        if queue.warning_level == "stale":
            alerts.append(
                WorkerHealthAlert(
                    severity="critical",
                    code="queue_stale_lock",
                    subject_kind="queue",
                    subject_id=queue.lane,
                    message=f"{queue.lane} queue has stale locked work",
                )
            )
        elif queue.warning_level == "deadline_risk":
            alerts.append(
                WorkerHealthAlert(
                    severity="warning",
                    code="queue_deadline_risk",
                    subject_kind="queue",
                    subject_id=queue.lane,
                    message=f"{queue.lane} queue has expired or deadline-risk work",
                )
            )
        elif queue.warning_level == "backlog":
            alerts.append(
                WorkerHealthAlert(
                    severity="warning",
                    code="queue_backlog",
                    subject_kind="queue",
                    subject_id=queue.lane,
                    message=f"{queue.lane} queue has due work waiting",
                )
            )
    return tuple(alerts)


def _age_seconds(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def _metric_labels(**labels: str) -> str:
    return (
        "{"
        + ",".join(f'{key}="{_escape_metric_label(value)}"' for key, value in labels.items())
        + "}"
    )


def _escape_metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _metric_number(value: float | int | bool) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _effective_status(
    record: WorkerHeartbeatRecord,
    *,
    now: datetime,
    stale_after: timedelta,
) -> str:
    if record.status in {"stopped", "failed"}:
        return record.status
    if record.last_seen_at < now - stale_after:
        return "stale"
    return record.status


def _loads_summary(value: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload
