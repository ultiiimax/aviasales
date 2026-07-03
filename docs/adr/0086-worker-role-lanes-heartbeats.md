# ADR 0086: Worker role lanes and active job heartbeats

Date: 2026-06-29

## Status

Accepted.

## Context

`flight-hunter-worker` had grown from a personal browser observation command into a durable local
runtime for browser observation jobs, cached watch scans, Telegram outbox delivery, maintenance
cleanup and deal discovery jobs. Running every lane in one process is useful for local demo mode,
but production self-hosting needs clearer process boundaries and operator-visible active work.

The project still must not create hidden provider calls. Browser work remains user-action-only,
watch scans remain scheduler/policy approved, and deal discovery remains candidate-only after a
user enqueue action.

## Decision

Keep the existing all-in-one worker as the default, and add role-scoped lanes:

- `browser`: durable personal browser observation jobs.
- `watch`: due cached/background watch scan jobs.
- `deal`: durable deal discovery jobs.
- `telegram`: due Telegram notification outbox delivery.
- `maintenance`: short retention cleanup passes.

Operators can run one or more roles with repeatable `--role` or comma-separated `--roles`. Legacy
skip flags continue to work as aliases that remove their corresponding lanes. The default worker
ID remains `flight-hunter-worker` for the all-in-one process; single-role processes default to
`flight-hunter-{role}-worker`.

Worker heartbeat rows keep the previous status fields and now also expose `role`,
`current_phase`, `current_job_kind` and `current_job_id` while a claimed item is being processed.
The admin health API and web Health panel render these fields with per-lane counters, so operators
can distinguish idle, stale and actively running work without reading logs.

## Consequences

- Local demo behavior is unchanged: `flight-hunter-worker` still runs one complete pass.
- Production deployments can split lanes under an external supervisor without code changes.
- A stuck job is easier to diagnose because the last heartbeat includes the active lane and job ID.
- This is not a replacement for a production supervisor, graceful drain dashboard or alerting
  rules. Those remain deployment/operations work on top of the durable DB state.

## Verification

- Unit coverage exercises role gating for a deal-only worker and verifies watch jobs are not run by
  that lane.
- Admin worker health API and web UI tests cover `current_job_kind` and `current_job_id`.
- Existing watch, Telegram, browser and deal job tests continue to cover each lane's lifecycle.
