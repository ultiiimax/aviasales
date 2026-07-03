# ADR 0032: Command Surface And Local Compose Stack

Date: 2026-06-29

## Status

Accepted for the first self-hosted command surface.

## Context

The project Definition of Done requires a single command interface and a `docker compose up --build`
path. The existing Makefile covered the core Python loop but missed integration/e2e/security,
demo seeding and compose targets. Runtime SQLite also requires `aiosqlite`, so it must be a runtime
dependency rather than only a dev dependency.

## Decision

1. Move `aiosqlite` into project runtime dependencies.
2. Add `Dockerfile` and `compose.yaml` for a local self-hosted API stack with a shared SQLite
   volume and an optional worker profile.
3. Add Make targets for `test-integration`, `test-e2e`, `seed-demo`, `security`,
   `compose-up`, `compose-worker-up` and `compose-down`.
4. Add `flight-hunter-seed-demo` for deterministic local seed data.
5. Add `flight-hunter-security-scan` for high-confidence local secret scanning.
6. Keep absent integration/e2e suites explicit: the Make targets report that the directory is not
   present instead of pretending tests ran.

## Consequences

- Clean checkouts have a clearer operational entrypoint.
- Docker Compose can start the API stack without local Python setup, assuming Docker is installed.
- The compose stack is still local/self-hosted SQLite, not the final production Postgres/Redis
  topology.
- Security scanning is a local high-confidence secret scan, not a full SAST/dependency audit.

## Verification

- `tests/unit/ops/test_makefile_commands.py`
- `tests/unit/ops/test_seed_demo.py`
- `tests/unit/ops/test_security_scan.py`
- `make security`
- `make test-integration`
- `make test-e2e`
