# ADR 0048: Browser Observer Claim Guards

Date: 2026-06-29

## Status

Accepted for durable worker hardening.

## Context

Personal Browser Observer jobs are user-action work, but the worker can run in more than one
process. Before this slice, queued jobs were claimed with a lease but did not materially enforce
`PERSONAL_OBSERVER_MAX_CONCURRENT` or `PERSONAL_OBSERVER_MIN_GAP_SECONDS` before starting browser
runtime side effects.

## Decision

1. Enforce `max_concurrent` inside `BrowserObservationJobRepository.claim_queued()` with a
   conditional DB update.
2. Enforce `min_gap_seconds` by source id using recent `last_attempted_at` values before a queued
   job can move to `running`.
3. Pass `AppSettings.personal_observer_max_concurrent` and
   `AppSettings.personal_observer_min_gap_seconds` from `flight-hunter-worker`.
4. Keep the guard at claim time so API requests still only enqueue jobs and do not run browser work.
5. Do not add live scraping or new browser sources in this hardening slice.

## Consequences

- Parallel workers cannot intentionally exceed the configured browser runtime concurrency through
  normal claim paths.
- Same-source jobs are naturally spaced out before any Playwright/Scrapling work starts.
- Stale lease recovery remains the escape hatch for crashed workers.

## Verification

- `tests/unit/persistence/test_browser_observation_job_repository.py`
- `tests/unit/ops/test_worker_command.py`
