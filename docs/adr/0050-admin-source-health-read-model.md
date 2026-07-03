# ADR 0050: Admin Source Health Read Model

Date: 2026-06-29

## Status

Accepted for operational visibility.

## Context

Workers already record append-only `source_health_events` for browser observations and watch scans,
while source contract readiness explains which providers are enabled, blocked, or policy-only.
Operators need a single admin API that combines these facts without running live smoke checks from a
GET request.

## Decision

1. Add `SourceHealthService` as an application read model over source contracts and recent
   `source_health_events`.
2. Include known contract sources and event-only sources such as browser observer source ids.
3. Return latest event metadata, blocked reasons and current status without secrets or raw payloads.
4. Add `GET /api/v1/admin/sources/health`.
5. Keep live/source smoke commands as explicit CLI actions, not implicit admin-page behavior.

## Consequences

- Admin users can inspect source status from persisted facts without causing provider calls.
- Browser/deal/worker events are visible even when they do not have a full provider contract entry.
- A richer web dashboard remains future work.

## Verification

- `tests/unit/api/test_admin_source_health_api.py`
- `tests/unit/persistence/test_source_health_event_repository.py`
