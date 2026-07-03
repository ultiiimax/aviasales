# ADR 0106: Worker health alert snapshot

Date: 2026-06-29

## Status

Accepted.

## Context

The admin worker health endpoint already exposed heartbeats and queue aggregates, but external
supervisors still had to infer alert conditions from several fields. That made stale workers,
stale queue locks and deadline-risk queues easier to miss.

## Decision

Add deterministic `alerts` to `WorkerHealthSnapshot` and
`GET /api/v1/admin/workers/health`. Alerts are derived from existing heartbeat and queue state:

- `worker_stale` and `worker_failed` are critical worker alerts;
- `queue_stale_lock` is a critical queue alert;
- `queue_deadline_risk` and `queue_backlog` are warning queue alerts.

The web Health panel renders these alerts as a read-only section.

## Consequences

- External supervisors can poll one stable API field instead of reimplementing warning rules.
- Alerts are side-effect free; Telegram or email delivery can be layered on later.
- Secrets and raw worker payloads are not included.

## Verification

- API tests cover stale worker, stale queue, backlog and deadline-risk alerts.
- Web UI smoke tests assert the alert panel is present.
