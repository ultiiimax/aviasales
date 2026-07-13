# Flight Hunter Local v1 Release Design

**Date:** 2026-07-13
**Target version:** 1.0.0
**Deployment class:** single-machine, local-only self-hosted application

## 1. Goal

Ship a reliable local Flight Hunter v1 on the existing Python/FastAPI architecture. A clean
checkout must run without external credentials in demo mode, while an explicitly configured
Aviasales mobile API path provides real live offers. The release must be reproducible, tested,
honest about data freshness, and safe to operate on one personal machine.

This release is not an implementation of the broader target architecture in `MEGA_PROMPT.md`.
It deliberately keeps FastAPI, the server-rendered static web application, SQLite, the existing
durable worker tables, and the current provider/application/domain boundaries.

## 2. Current Evidence and Release Blockers

The 2026-07-13 audit established this baseline:

- `pytest`: 460 passed and 6 failed. The failures are caused by fixed test clocks creating jobs
  that are expired when production code evaluates them using the real current time.
- `ruff format --check`, `ruff check`, and strict `mypy`: pass.
- Alembic upgrade, integration acceptance test, security scan, and `docker compose config`: pass.
- The root web response contains widespread mojibake even though it returns UTF-8.
- Browser smoke reports `browser_runtime_unavailable` because the optional Playwright/Chromium
  runtime is not bootstrapped by the documented development setup.
- Docker configuration parses, but the image cannot currently be built on the audit machine
  because Docker Desktop is not running.
- The repository has no CI workflow, browser E2E suite, changelog, security guide, or local
  deployment guide.
- A sanitized live Aviasales smoke succeeded, and an exact-date MOW-LED search returned 50
  normalized offers marked `aviasales_search` and `live`. No raw payload, provider reference,
  signature, marker, or purchase URL was printed.

## 3. Release Contract

### 3.1 Supported runtime

- Windows 11 with PowerShell Core for direct development and operation.
- Docker Desktop with Linux containers for the packaged local stack.
- Python `>=3.13,<3.14`, managed by `uv`.
- Access through `http://127.0.0.1:8000`; the packaged release does not bind a public host port.
- SQLite on a persistent named Docker volume or a local file for direct execution.

### 3.2 Startup modes

**Demo mode** is the default. It requires no provider or Telegram credentials, uses
`FakeFlightProvider`, and visibly labels fake data.

**Live Aviasales mode** requires all of:

- `AVIASALES_SEARCH_ENABLED=true`;
- `AVIASALES_SEARCH_SIGNATURE`;
- `AVIASALES_SEARCH_MARKER`;
- a non-default `APP_SECRET_KEY`.

Missing or invalid credentials must produce a typed unavailable state without preventing startup
or falling back to invented live data.

**Telegram mode** remains optional. With `TELEGRAM_ENABLED=false`, webhook and delivery workers
must remain inert. Enabling it requires the existing webhook secret and bot-token checks.

### 3.3 Supported user flows

The local v1 release supports:

1. opening the Russian web UI without corrupted text;
2. exact-date and date-matrix search;
3. fake-provider demo search without credentials;
4. Aviasales live search when configured;
5. source, freshness, observation time, passenger count, baggage uncertainty, and risk display;
6. lazy booking-action resolution from a signed, expiring token;
7. watch create/list/detail/pause/resume/archive/history flows;
8. worker processing with retry, lease, drain, cleanup, dedupe, and graceful shutdown behavior;
9. optional Telegram linking/webhook/outbox behavior;
10. local backup, verification, and restore.

## 4. Architecture

### 4.1 Runtime topology

The packaged stack has two long-running processes sharing one SQLite volume:

- `api`: runs Alembic migrations once, then serves FastAPI and the bundled web UI;
- `worker`: waits for API readiness, then runs the existing durable worker loop.

SQLite remains the intentional local persistence engine. The release will not introduce Redis,
PostgreSQL, a separate frontend build, or a reverse proxy. SQLite connection settings and worker
claim behavior must remain safe for the existing low-concurrency personal workload.

### 4.2 Module boundaries

- `domain/` continues to own money, offers, policy, search, observation, and ranking invariants.
- `application/` continues to orchestrate searches, watches, booking actions, and worker jobs.
- `providers/aviasales_search/` remains the only live fare adapter. Provider DTOs stay behind its
  schema and mapper boundary.
- `persistence/` continues to implement repositories and append-only history.
- `api/app.py` remains the composition root and HTTP adapter.
- `api/web.py` owns the single bundled local web surface but not business decisions.
- `ops/` owns release checks, worker entry points, backup/restore, browser smoke, and security
  checks.

No release-hardening change may move provider DTOs into API responses, calculate money in
JavaScript, or put search/watch policy into route handlers.

## 5. Component Design

### 5.1 Time-stable worker tests

Production expiry behavior remains unchanged. Tests that create non-expired jobs must derive
creation and deadline times from the same injected clock used by the execution service, or patch
the runtime clock at the process boundary. Tests specifically covering expiry keep explicit past
timestamps. A regression test must prove the normal worker fixture remains valid regardless of
the wall-clock date.

### 5.2 UTF-8 web surface

Repair corrupted literals in `api/web.py` without changing element IDs, endpoint paths, or
JavaScript data contracts. Add a response-level regression test that checks representative
Russian labels and rejects common mojibake markers such as `Рќ`, `РЎ`, `вЂ`, and `рџ`.

The browser must receive `text/html; charset=utf-8`. User-visible provider failures remain typed
and readable. Unknown baggage, fare rules, or price freshness must not be converted into confident
claims.

### 5.3 Browser verification

Keep Playwright and Chromium outside the minimal runtime image. Add an explicit browser bootstrap
command that installs the optional Python group and Chromium. The browser smoke command must:

- return success only after Chromium can launch and load a minimal local page;
- return a stable machine-readable failure code when the runtime is absent;
- avoid network access to live providers.

CI installs the browser runtime before running browser smoke and local web E2E checks.

### 5.4 Container packaging

The Docker image must:

- use the locked dependency graph;
- run as a non-root user;
- contain application source and Alembic migrations;
- expose a health endpoint without embedding credentials;
- stop cleanly on termination;
- contain no development, scraping, browser, or provider-secret material.

Compose must:

- bind port 8000 to `127.0.0.1` only;
- start API and worker in the default profile;
- add API and worker healthchecks;
- use restart policies appropriate for a local daemon;
- persist SQLite data in a named volume;
- prevent the worker from claiming jobs before migrations and API readiness;
- allow optional deal-discovery services only through their existing profile.

### 5.5 Release validation

Add one deterministic release-check command that executes the repository-owned checks in a fixed
order and exits non-zero at the first failed stage. Its credential-free gate covers:

1. unit and integration tests;
2. formatter check and lint;
3. strict type checking;
4. Alembic upgrade on a fresh temporary SQLite database;
5. security scan;
6. Compose configuration validation;
7. API/web acceptance checks;
8. browser smoke when the browser runtime is explicitly requested or installed.

Live provider smoke is a separate manual command so CI never contacts Aviasales. Docker image
build is part of CI and the documented final local release procedure, but the release-check must
report Docker unavailability clearly rather than misclassifying it as an application test failure.

### 5.6 CI

GitHub Actions runs on a clean supported Python environment and verifies:

- locked dependency installation;
- tests, Ruff, and mypy;
- migration and security checks;
- browser bootstrap and smoke;
- Compose config;
- Docker image build.

CI receives no live provider credentials and makes no Aviasales calls.

### 5.7 Versioning and documentation

Set the package and API version to `1.0.0`. Add:

- `CHANGELOG.md` with the local v1 scope;
- `SECURITY.md` describing local-only exposure and secret handling;
- a local deployment/update guide;
- exact browser-bootstrap and release-check commands;
- accurate backup/verify/restore commands;
- provider contract verification dated 2026-07-13;
- updated `README.md` and `IMPLEMENTATION_STATUS.md` containing only freshly verified claims.

## 6. Data and Error Flow

### 6.1 Search

Web/API input is validated into `SearchIntent`, authorized through provider policy, sent to the
selected adapter, mapped into canonical `FlightOffer` values, ranked deterministically, and
serialized without raw provider references. Fake results are explicitly demo data. Aviasales
results are `LIVE` with `observed_at` from the adapter clock.

### 6.2 Booking action

Search results expose a short-lived signed token. The resolve endpoint validates signature,
expiry, provider, and encoded references before making the click call. Only the direct resolve
response may contain the purchase URL. Tokens and URLs are excluded from logs, callbacks, and
client bundles.

### 6.3 Worker

The worker claims durable jobs by role, records attempts and heartbeat state, applies provider
policy before background calls, persists successful snapshots append-only, deduplicates alerts,
and schedules classified retryable failures. Expired, paused, drained, stale, or policy-blocked
work must be skipped with an observable reason.

### 6.4 Failure presentation

Network failure, provider block, rate limit, missing credentials, schema failure, stale data, and
browser-runtime absence retain distinct machine-readable codes. The web UI shows a concise next
action and never substitutes fake or cached prices for failed live data without an explicit label.

## 7. Security Boundary

This is a local release, not an internet-facing service. Compose binds to loopback. Users who put
it behind a public proxy must supply TLS, secure cookies, trusted proxy configuration, and their
own perimeter controls; that deployment is outside v1 support.

The release must preserve:

- invitation/session checks and household filters;
- webhook secret and Telegram update dedupe;
- signed booking tokens;
- outbound URL validation for untrusted discovery links;
- structured-log redaction;
- no secrets in repository, image, logs, OpenAPI examples, or browser assets;
- no live provider calls in CI.

## 8. Verification and Acceptance

The release is accepted only when fresh evidence proves all of the following:

1. full pytest suite has zero failures;
2. Ruff format/check and strict mypy pass;
3. fresh and existing-database migration checks pass;
4. security scan reports zero findings;
5. representative Russian UI text is readable and mojibake regression checks pass;
6. demo search, booking token, watch lifecycle, worker retry/dedupe, Telegram security, and
   backup/restore tests pass;
7. browser smoke passes after documented bootstrap;
8. Compose config passes and the Docker image builds when Docker is available;
9. default Compose binds only to loopback and starts API plus worker;
10. a manual sanitized Aviasales suggest and exact-date search smoke pass without exposing
    credentials or raw provider data;
11. documentation matches the exact commands and observed results;
12. no `TODO`, `pass`, `NotImplementedError`, fake return, or commented incomplete code exists in
    the changed production flow.

## 9. Upgrade and Rollback

Before update, create and verify a backup. The normal update path is: stop processes, back up,
install the locked release, run Alembic upgrade, start API and worker, then run health and demo
smoke checks. Schema changes, if audit fixes require any, use a new forward migration.

Rollback restores the previous application version and the pre-upgrade database backup. Existing
migrations are never edited. Version 1.0.0 does not promise downgrade migrations.

## 10. Explicit Non-Goals

- Next.js or another separate frontend toolchain;
- PostgreSQL/PostGIS, Redis, Caddy, Kubernetes, or public SaaS deployment;
- automatic purchasing or payment handling;
- new unverified fare providers;
- automatic live calls in CI;
- broad refactoring unrelated to a measured release blocker;
- claiming Docker verification on a machine where the Docker engine is unavailable.
