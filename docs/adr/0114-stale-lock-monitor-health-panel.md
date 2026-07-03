# ADR 0114: Stale Lock Monitor in Health Panel

Date: 2026-06-29

## Status

Accepted.

## Context

Worker queue health already exposes stale locked work through API fields and Prometheus metrics.
Operators still need a clear in-app signal instead of scanning each queue row manually.

## Decision

- Add a read-only "Stale lock monitor" section to the existing web Health panel.
- Show only lanes with `stale_count > 0`.
- Include stale count and oldest locked age, using the same API snapshot as worker queue health.
- Keep the section diagnostic-only; lease recovery remains in the worker pass and supervisor flow.

## Consequences

- Stale worker leases are visible in the built-in admin workbench.
- No new background calls or destructive operations are introduced.
- The dedicated production supervisor remains separate operational work.
