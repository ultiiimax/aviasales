# ADR 0105: Systemd worker supervision templates

Date: 2026-06-29

## Status

Accepted.

## Context

`flight-hunter-worker` already supports durable role lanes, heartbeats, drain control and graceful
shutdown. Production self-hosting still needed concrete external-supervisor packaging that does not
embed secrets or bypass application policy gates.

## Decision

Add systemd templates under `deploy/systemd/`:

- `flight-hunter-api.service` for the FastAPI app and migrations at startup;
- `flight-hunter-worker@.service` for one worker lane per instance, such as `browser`, `watch`,
  `deal`, `telegram` and `maintenance`.

Both units load secrets from `/etc/flight-hunter/flight-hunter.env`, use restart-on-failure,
SIGTERM shutdown and conservative systemd hardening. The runbook documents drain-before-restart,
health checks and browser-lane caveats.

## Consequences

- Self-hosted deployments can run separate supervised worker lanes without changing application
  code.
- Secrets stay out of unit files and command-line arguments.
- Browser observation policy remains unchanged: the supervisor only runs queued user-action jobs.

## Verification

- Unit tests assert environment-file usage, no inline secret placeholders, restart policy, hardening
  directives and role-template behavior.
