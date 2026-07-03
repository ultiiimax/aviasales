# ADR 0097: Personal observation expired direct-run guard

Date: 2026-06-29

## Status

Accepted.

## Context

The durable worker claim path already filters browser observation jobs by `expires_at > now`, so
expired queued jobs are not claimed by the normal `flight-hunter-worker` browser lane. The direct
job runner path, used by `flight-hunter-run-personal-observation` and service-level `run_job()`,
looked up a queued job and immediately marked it running. That could bypass the claim-time expiry
guard and run stale browser work after the user-action observation window had elapsed.

## Decision

`PersonalObservationService.run_job()` now checks `job.expires_at <= now` before marking the job
running. Expired queued jobs are marked terminal `expired` with `error_code=expired`; the runner is
not invoked and no browser-observed offers are persisted.

## Consequences

- Direct and worker-driven personal observation execution now share the same no-expired-work
  invariant.
- The CLI returns `accepted=false`, `code=job_expired` and exits non-zero for an expired job.
- No schema migration is required because observation status/error code are stored as strings.

## Verification

- Service tests cover that an expired job does not call the runner and stores no offers.
- CLI tests cover that an expired job is marked `expired` and exits with code 2.
