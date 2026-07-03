# ADR 0080: Worker Heartbeats

Date: 2026-06-29

## Status

Accepted.

## Context

The durable worker can process browser observation jobs, watch scans and Telegram outbox rows, but
operators previously had to infer whether the worker was alive from logs or stale leases. The
monster plan calls for production-grade worker visibility and operational health without issuing
provider calls from admin screens.

## Decision

- Add `worker_heartbeats`, keyed by `worker_id`, as a durable read model for worker liveness.
- Record role, status, phase, start/last-seen/stopped timestamps and the last pass summary JSON.
- Let `flight-hunter-worker` update its heartbeat before and after each pass. One-shot runs end as
  `stopped`; loop passes report `idle`, and CLI loop shutdown records `stopped`.
- Expose `GET /api/v1/admin/workers/health` and render workers in the existing web Health panel.
- Compute `effective_status=stale` at read time when a non-stopped worker has not reported within
  the configured stale window.

## Consequences

- Admin health reads durable DB state and does not perform live checks or provider calls.
- Heartbeats are upserted per worker, so a long-running deployment does not create unbounded
  heartbeat rows.
- This complements, but does not replace, job leases and stale recovery.
