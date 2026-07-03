# ADR 0033: Durable Watch Scan Worker

Date: 2026-06-29

## Status

Accepted for the cached-provider watch scan slice.

## Context

The project already had a pure `WatchSchedulerPlanner`, append-only `price_snapshots`, and durable
alert dedupe, but the worker only processed user-action personal browser observation jobs. That left
watches without a production background path for cached providers, and it also risked future code
calling live/browser/user-action sources from the scheduler.

## Decision

1. Add schedule fields to `watches`: passenger count, currency, pause/next-eligible metadata,
   scan interval, allowed providers, and last scan status/error.
2. Add `watch_scan_jobs` as a durable queue with idempotency key, status, attempts, retry time,
   deadline, provider ids and provider-denial provenance.
3. Add `WatchScanService` in the application layer. It:
   - lists due watches through the repository;
   - runs `WatchSchedulerPlanner` in `ExecutionContext.SCHEDULER`;
   - creates idempotent scan jobs only for scheduler-approved providers;
   - calls only configured cached/background providers;
   - persists deterministic snapshot ids so retries do not duplicate partial success;
   - evaluates price-drop alerts only after a newly inserted non-stale snapshot;
   - records source health events without raw provider payloads or secrets.
4. Wire `flight-hunter-worker` to process watch scans in one-pass and loop modes. The worker uses
   Aviasales Data when `AVIASALES_DATA_ENABLED=true` and `TRAVELPAYOUTS_API_TOKEN` is present;
   otherwise it uses `FakeFlightProvider` as a local demo fallback only.
5. Keep personal browser observation separate. The watch scanner never uses Playwright, Scrapling,
   Crawl4AI, personal observer grants, or live/user-action providers.

## Consequences

- Due watches now produce durable price history through the normal worker command.
- Background-disallowed providers are denied before any provider `search()` call.
- Partial success is preserved: if one provider succeeds and another fails, snapshots and alert
  dedupe remain durable while the job can retry.
- Worker claims are now hardened with conditional DB leases; see ADR 0035.
- Telegram delivery is handled by a separate durable outbox slice; alert dedupe remains the source
  of notification idempotency.

## Verification

- `tests/unit/application/test_watch_scans.py`
- `tests/unit/ops/test_worker_command.py`
- `tests/unit/persistence/test_household_watch_repository.py`
- `tests/unit/persistence/test_alembic_upgrade.py`
- `uv run pytest tests\unit\application\test_watch_scans.py tests\unit\ops\test_worker_command.py tests\unit\persistence\test_household_watch_repository.py tests\unit\persistence\test_price_history_and_alert_dedupe.py tests\unit\api\test_watch_api.py tests\unit\persistence\test_alembic_upgrade.py --quiet`
- `uv run ruff format --check ...`
- `uv run ruff check ...`
- `uv run mypy`
