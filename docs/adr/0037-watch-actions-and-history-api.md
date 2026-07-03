# ADR 0037: Watch Actions And History API

Date: 2026-06-29

## Status

Accepted for the first watch management API slice.

## Context

Watches could be created and listed, and the worker could scan due watches, but the API did not yet
expose watch detail, pause/resume actions or append-only price history. The architecture and monster
plan both require household-isolated watch management and history views.

## Decision

1. Add `GET /api/v1/watches/{watch_id}`.
2. Add `POST /api/v1/watches/{watch_id}/pause`; callers can provide `paused_until`, otherwise the
   service pauses for 24 hours.
3. Add `POST /api/v1/watches/{watch_id}/resume`; resume clears `paused_until` and makes the watch
   eligible immediately.
4. Add `GET /api/v1/watches/{watch_id}/history` backed by append-only `price_snapshots`.
5. Keep all routes household-scoped. A watch from another household returns `watch_not_found`.
6. Include scheduler metadata in watch responses: pause state, next eligible time, interval and
   last scan status/error.

## Consequences

- Users can inspect and control watches without direct database access.
- Paused watches are skipped by the existing due-watch query until `paused_until`.
- History remains read-only and append-only; API actions do not mutate snapshots.
- Full PATCH/versioned watch edits and archive/delete remain future slices.

## Verification

- `tests/unit/api/test_watch_api.py`
- `tests/unit/persistence/test_household_watch_repository.py`
- `tests/unit/application/test_watch_scans.py`
