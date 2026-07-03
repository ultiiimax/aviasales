# ADR 0112: Admin Health and Audit Paging

Date: 2026-06-29

## Status

Accepted.

## Context

Worker health already supports bounded heartbeat windows. Admin source health and household audit
surfaces still used fixed or in-memory recent windows, which is awkward for long-running
self-hosted installs.

## Decision

- Add `sources_limit`, `sources_offset` and `event_limit` to `GET /api/v1/admin/sources/health`.
- Paginate the returned source list, not the latest-event selection, so source status remains based
  on the newest available event window.
- Add `limit` and `offset` metadata to `GET /api/v1/admin/audit-events`.
- Add repository-level newest-first audit pagination scoped by household.

## Consequences

- Admin panels can request deterministic pages without fetching all household audit history.
- Source health keeps honest current-status semantics while still bounding response size.
- Provider health remains unpaged because the provider catalog is a tiny static readiness surface.
