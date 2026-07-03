# ADR 0079: Personal Observer Checkpoint Controls

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer can run a visible Playwright browser and mark a job as
`waiting_for_user`, but the previous checkpoint behavior was only a fixed local timeout. That made
operator intent implicit: the worker would eventually capture DOM even if the operator still needed
time, and there was no durable way to cancel a challenged or wrong page.

## Decision

- Add nullable durable control timestamps to `browser_observation_jobs`:
  `operator_resume_requested_at` and `operator_abort_requested_at`.
- Add scoped API actions:
  `POST /api/v1/personal-observations/{job_id}/resume` and
  `POST /api/v1/personal-observations/{job_id}/abort`.
- Allow these actions only while the job is owned by the household/user and currently
  `waiting_for_user`.
- Let the worker poll the durable control signal during the visible manual checkpoint. Resume moves
  to DOM capture; abort ends as `needs_human` with machine error code `operator_aborted`.
- Keep the old bounded timeout behavior as a fallback when no checkpoint callback is configured.

## Consequences

- A visible browser checkpoint is now an explicit operator handshake, not just a sleep.
- Worker restarts and API processes communicate through durable job state; no in-memory browser
  control channel is required.
- Browser observation remains user-action-only. The scheduler still cannot create or resume browser
  observations in the background.
