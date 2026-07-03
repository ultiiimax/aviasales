# ADR 0030: Browser Observation Worker Loop And Retries

Date: 2026-06-29

## Status

Accepted for the first durable DB-backed worker loop.

## Context

Browser observations must not block API requests. They are allowed only for jobs that were already
created from a real user action grant. The worker needs enough durable state to avoid tight retry
loops and to make failures explainable.

## Decision

1. Extend `browser_observation_jobs` with `attempts`, `last_attempted_at` and `next_retry_at`.
2. Treat `expires_at` as the job deadline for the current SQLite-backed implementation.
3. Make `BrowserObservationJobRepository.list_queued()` return only unexpired queued jobs whose
   `next_retry_at` is absent or due.
4. Increment attempts in `mark_running()`.
5. Retry only transient browser runner statuses: `timed_out` and `source_unavailable`.
6. Keep parser drift/no-price/policy/source-challenge errors terminal for now.
7. Run expired live observation cleanup from `flight-hunter-worker` by default, with
   `--skip-live-cleanup` for focused local troubleshooting.
8. Record append-only `source_health_events` for each processed browser observation job.
9. Add `flight-hunter-worker --loop` with idle sleep and test-only `--stop-after-iterations`.
10. Do not create provider/browser work from the worker. It processes only already queued
   `browser_observation_jobs`.

## Consequences

- Local Windows/Mac usage can run a simple polling worker without Redis.
- Future Docker/systemd deployment can wrap the same command.
- This is not yet a distributed lease/lock implementation; concurrent workers should still be
  treated as future work.
- Watch scans remain a future worker responsibility.
- Source health events currently cover processed browser observation jobs; provider quota/contract
  health screens can build on the same table later.

## Verification

- `tests/unit/application/test_personal_observations.py`
- `tests/unit/persistence/test_browser_observation_job_repository.py`
- `tests/unit/ops/test_worker_command.py`
- `tests/unit/persistence/test_source_health_event_repository.py`
- `tests/unit/persistence/test_alembic_upgrade.py`
- `migrations/versions/0010_browser_observation_job_retries.py`
- `migrations/versions/0011_source_health_events.py`
