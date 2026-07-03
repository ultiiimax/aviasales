# ADR 0108: Worker Prometheus Metrics

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter already exposes worker heartbeat, queue health and derived alerts through
`GET /api/v1/admin/workers/health`. Operators still need a low-friction text surface for external
monitoring without scraping logs or parsing the rich JSON health response.

## Decision

- Add `render_worker_health_prometheus(...)` in the application layer.
- Add `GET /api/v1/admin/workers/metrics` returning Prometheus text format
  (`text/plain; version=0.0.4`).
- Reuse the existing worker health snapshot, including queue aggregates, worker effective status,
  drain state and active alert codes.
- Keep metrics side-effect free and bounded. Metrics do not include `current_job_id`,
  `last_summary`, secrets, raw payloads, URLs, callback data or user identifiers.
- Omit queue age samples when no queued/locked item exists, rather than inventing a sentinel age.

## Consequences

- Self-host deployments can scrape worker health with Prometheus, VictoriaMetrics or a simple curl
  probe.
- The JSON health endpoint remains the richer operator view; the metrics endpoint is a compact
  monitoring surface.
- Metrics inherit the same database freshness as worker heartbeats and queue aggregate queries.
