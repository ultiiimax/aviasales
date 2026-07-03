# ADR 0109: Worker Health Paging

Date: 2026-06-29

## Status

Accepted.

## Context

`GET /api/v1/admin/workers/health` and `/metrics` used a fixed latest-20 worker heartbeat window.
That is fine for a small local install, but production supervision can have multiple role-specific
workers and historical stopped/failed records. Operators need bounded paging controls without
expanding queue aggregate work or leaking job details.

## Decision

- Add `workers_limit` and `workers_offset` query parameters to worker health JSON and metrics
  endpoints.
- Add repository offset support to `WorkerHeartbeatRepository.list_recent(...)`.
- Keep queue aggregates unpaged because they are lane-level totals, not per-worker rows.
- Return `workers_limit` and `workers_offset` in the JSON health response.
- Apply the same bounds to metrics so scrape targets can choose a deterministic worker window.

## Consequences

- Worker heartbeat lists are bounded and operator-controllable.
- Metrics remain compact and continue to omit `current_job_id` and `last_summary`.
- Broader pagination for other admin resources remains a separate product concern.
