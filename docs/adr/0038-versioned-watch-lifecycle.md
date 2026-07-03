# ADR 0038: Versioned Watch Lifecycle

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter already had household-scoped watch create/list/detail, pause/resume and price
history. The product plan also requires full watch CRUD/versioning and lifecycle controls so web
and Telegram clients can edit watches without overwriting concurrent changes, and so archived or
deleted watches do not keep running in the scheduler.

## Decision

- Add `version`, `updated_at`, `archived_at`, `archived_by_user_id`, `deleted_at` and
  `deleted_by_user_id` to `watches`.
- Add a general `audit_events` table for user/API lifecycle events instead of reusing
  `agent_audit_events`, which is intentionally scoped to agent tool decisions.
- Add `PATCH /api/v1/watches/{watch_id}` with an `expected_version` optimistic lock.
- Add `POST /api/v1/watches/{watch_id}/archive` and `DELETE /api/v1/watches/{watch_id}` as
  soft lifecycle operations with the same version check.
- Hide archived/deleted watches from list/detail/history and from scheduler due queries.
- Keep scan-result updates from bumping watch version; background scans should not create false
  client-side edit conflicts.

## Consequences

- Clients must read the latest watch before mutating it and handle `watch_version_conflict`.
- Archive/delete preserve price history and auditability while stopping future scans.
- A fuller admin/audit UI can now read a general audit stream in a later slice.
