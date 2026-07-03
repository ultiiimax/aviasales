# ADR 0059: Worker Graceful Shutdown

Date: 2026-06-29

## Status

Accepted.

## Context

`flight-hunter-worker --loop` processes durable browser observation jobs, watch scan jobs, Telegram
outbox rows and cleanup in repeated passes. A production-ish local worker should stop cleanly when a
supervisor sends SIGINT/SIGTERM: finish the current pass, avoid starting a new pass, and interrupt
idle sleep quickly.

## Decision

- Add a stop predicate to `run_loop`.
- Install SIGINT/SIGTERM handlers in the CLI loop path.
- Use a signal-aware sleep wrapper so idle sleep returns as soon as shutdown is requested.
- Keep `run_once` unchanged: already-claimed jobs finish through the existing durable retry/error
  paths before the loop exits.

## Consequences

- Local and container workers can drain between passes instead of requiring hard termination during
  idle sleeps.
- A shutdown signal does not create new browser/provider work.
- This is still not a full production supervisor, autoscaler or dashboard; it is the worker-side
  shutdown primitive those layers can rely on.
