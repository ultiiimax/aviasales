# ADR 0094: Worker queue health dashboard

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter now has durable browser observation jobs, watch scan jobs, deal discovery jobs and
Telegram notification delivery. The worker can claim and recover these queues, and operator drain
control can pause new claims. Before this slice, admin health showed worker heartbeats but not the
actual queue backlog, retry delay, stale locks or expired/deadline-exceeded rows.

## Decision

Add a read-only worker queue health aggregate to `GET /api/v1/admin/workers/health`. The response
now includes one queue item per lane:

- `browser`;
- `watch`;
- `deal`;
- `telegram`.

Each item reports status counts, due count, delayed count, stale active count, expired/deadline count,
oldest queued age, oldest locked age and a warning level. Warning priority is:

1. `stale`;
2. `deadline_risk`;
3. `drained`;
4. `backlog`;
5. `ok`.

The web Health panel renders these aggregates in a separate “Worker queues” section. This is
strictly read-only and does not alter claim, retry, recovery or provider-call semantics.

## Consequences

- Operators can see queue pressure and stale/deadline risks without shelling into the database.
- Admin health still performs no provider calls and exposes no secrets.
- This does not add external process supervision, alerting or Prometheus metrics; those remain
  follow-up operations work.

## Verification

- Persistence tests cover queue aggregation across browser/watch/deal/Telegram lanes.
- API tests cover the new `queues` response and no-secret invariant.
- Web UI tests cover the queue dashboard labels.
