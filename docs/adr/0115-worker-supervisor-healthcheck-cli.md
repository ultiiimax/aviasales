# ADR 0115: Worker Supervisor Healthcheck CLI

Date: 2026-06-29

## Status

Accepted.

## Context

Systemd templates can restart failed worker processes, and the admin API exposes worker health. A
production supervisor still benefits from a local command that checks durable heartbeat/queue state
without requiring HTTP access or provider credentials.

## Decision

- Add `flight-hunter-worker-healthcheck`.
- Read `worker_heartbeats`, queue health and worker control state from the configured database.
- Support role-lane checks with `--role` plus heartbeat staleness threshold through
  `--max-age-seconds`.
- Return JSON summary and exit non-zero for missing heartbeat, stale/failed worker, or critical
  role-relevant alert.
- Add a `make worker-healthcheck` target and document systemd/runbook usage.

## Consequences

- Operators can wire the command into cron, systemd health scripts, or external monitoring.
- The healthcheck does not make provider calls and does not print secrets, job summaries or raw
  payloads.
- This complements, but does not replace, an external process supervisor.
