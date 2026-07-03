# ADR 0027: Durable Personal Observation Jobs

Date: 2026-06-29

## Status

Accepted for the personal browser observer queue slice.

## Context

The personal observer runtime can parse sanitized fixtures and can run a local Playwright browser,
but API requests must not block on browser work. The monster plan requires durable browser
observation jobs with user-action grants, idempotency, status tracking and short-lived normalized
results.

## Decision

1. Add a separate `browser_observation_jobs` table instead of overloading the older demo
   `live_observations` table.
2. Keep `BrowserObservedOffer` persistence separate from job status. Search responses read recent
   normalized offers by household/user/search id.
3. Add `POST /api/v1/personal-observations/grants`, `POST /api/v1/personal-observations` and
   `GET /api/v1/personal-observations/{id}`.
4. Require user context for grants, and both household/user context plus `Idempotency-Key` for job
   creation.
5. Execute jobs through `flight-hunter-run-personal-observation`, not inside the HTTP request.
6. Keep the worker tied to already-created user-action jobs. The scheduler must not create browser
   observation jobs or run browser observations as background discovery.

## Consequences

- API latency stays predictable and does not depend on browser startup or external page behavior.
- Browser observations are durable and recoverable across app instances.
- Search result enrichment remains tenant-scoped and short-lived.
- A long-running worker daemon and web UI button can be added later on top of the same job table.
- The implementation still does not perform CAPTCHA bypass, stealth, proxy rotation, foreign cookie
  reuse or login-required scraping.

## Verification

- `tests/unit/persistence/test_browser_observation_job_repository.py`
- `tests/unit/application/test_personal_observations.py`
- `tests/unit/providers/personal_observer/test_worker_cli.py`
- `tests/unit/api/test_api_app.py`
- `tests/unit/persistence/test_alembic_upgrade.py`
