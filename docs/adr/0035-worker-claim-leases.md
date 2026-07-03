# ADR 0035: Worker Claim Leases

Date: 2026-06-29

## Status

Accepted for DB-backed worker queues.

## Context

`flight-hunter-worker` now handles three durable queues:

- personal browser observation jobs created only after a user-action grant;
- cached watch scan jobs created by scheduler policy planning;
- Telegram notification outbox rows created after alert dedupe.

The previous worker implementation listed due rows and then marked them running/sending inside the
service. That was idempotent enough for a single local worker, but two worker processes could list
the same due row before either had changed its status.

## Decision

1. Add `locked_at` and `locked_by` to `browser_observation_jobs` and
   `telegram_notification_outbox`. `watch_scan_jobs` already had these columns.
2. Add repository-level claim methods:
   - `BrowserObservationJobRepository.claim_queued`;
   - `WatchScanJobRepository.claim_queued`;
   - `TelegramNotificationOutboxRepository.claim_due`.
3. Each claim method performs a conditional `UPDATE` against the current eligible state and only
   returns rows whose update affected exactly one row.
4. Browser/watch claims move work to `running` and increment attempts at claim time.
5. Telegram claims move rows to `sending` but do not increment attempts until a real send failure.
   Quiet-hours deferral returns the row to `retry_scheduled` without consuming an attempt.
6. Success, failure and retry scheduling clear `locked_at`/`locked_by`.
7. The worker processes only claimed rows. Direct service paths still support single-job execution
   by first marking the row running and then using the same claimed-job execution method.
8. Recover stale leases before each worker claim pass:
   - browser jobs in stale `running` return to `queued` when still before `expires_at`, otherwise
     fail with `timed_out`;
   - watch scan jobs in stale `running` return to `retry_scheduled` when attempts/deadline allow,
     otherwise fail;
   - Telegram rows in stale `sending` return to `retry_scheduled` without incrementing attempts.

## Consequences

- Parallel local workers no longer intentionally process the same due browser, watch or Telegram
  row when the database enforces conditional updates.
- A crashed worker no longer leaves claimed work permanently stuck in `running`/`sending`.
- Retry accounting is tied to claim/execution attempts, not passive queue visibility.
- This is still a relational-database queue, not a separate Redis/Celery deployment. A production
  supervisor can run multiple workers, but future deployment work may still add metrics dashboards
  and graceful drain controls.
- Provider policies are unchanged: browser jobs must already exist from user action, and watch
  scans still call only scheduler-approved cached/background providers.

## Verification

- `tests/unit/persistence/test_browser_observation_job_repository.py`
- `tests/unit/persistence/test_watch_scan_job_repository.py`
- `tests/unit/application/test_telegram_notifications.py`
- `tests/unit/application/test_watch_scans.py`
- `tests/unit/application/test_personal_observations.py`
- `tests/unit/ops/test_worker_command.py`
- `tests/unit/persistence/test_alembic_upgrade.py`
