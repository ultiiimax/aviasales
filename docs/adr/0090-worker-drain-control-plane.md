# ADR 0090: Worker drain control plane

Date: 2026-06-29

## Status

Accepted.

## Context

`flight-hunter-worker` can process browser observations, watch scans, deal-discovery jobs,
Telegram delivery and maintenance cleanup through DB-backed leases. It also records durable
heartbeats for the admin health surface. Production deployments still need a safe way to pause new
claims before maintenance or upgrades without deleting queued work, inventing provider state, or
requiring log scraping.

External process supervision is intentionally out of scope for the FastAPI app, but the app can own
a durable operator intent that workers observe.

## Decision

Add a single-row `worker_control` table with a global `drain_requested` flag, optional reason and
timestamps. `GET /api/v1/admin/workers/health` includes this control state, and the web Health panel
shows whether new worker claims are enabled or paused.

`PATCH /api/v1/admin/workers/control` updates the drain flag through authenticated household/user
context and writes an audit event. The response does not expose requester ids.

When drain is requested, `flight-hunter-worker` skips new browser, watch, deal and Telegram
recovery/claim/delivery work. Maintenance cleanup remains allowed so expired short-lived state does
not accumulate. Already-running jobs keep their existing lifecycle; drain does not fail, delete or
requeue them.

## Consequences

- Operators can pause new claims before process restarts or deploys.
- Queued work remains durable and resumes when drain is cleared.
- Provider policy is unchanged: drain never creates provider/browser calls and does not grant live
  access.
- A separate supervisor is still required to start/stop processes and alert on stale workers.

## Verification

- Repository tests cover default, set and clear behavior.
- API tests cover health exposure, auth requirement and audit events.
- Worker tests cover skipped claims with maintenance cleanup still running.
