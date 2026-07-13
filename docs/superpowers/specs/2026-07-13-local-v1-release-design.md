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
- `windows-latest` is a required CI job for locked installation, tests, Ruff, mypy, migrations,
  security checks, and PowerShell command examples. A test workspace with Cyrillic and spaces in
  its path verifies the supported Windows path shape.
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

Credential validation has two layers. Empty values are `credentials_missing`. Values that fail
the documented local signature/marker shape are `credentials_invalid` and are rejected before an
HTTP call. An upstream HTTP 401 is `auth_failed`. None of these configuration/authentication
states is retried automatically; HTTP 403 remains the separately observable provider/WAF
`blocked` state.

**Telegram mode** remains optional. With `TELEGRAM_ENABLED=false`, webhook and delivery workers
must remain inert. Enabling it requires the existing webhook secret and bot-token checks.

### 3.2.1 Clean-install authentication and secrets

The release adds `flight-hunter-init-local --output .env`. It copies documented non-secret
defaults from `.env.example`, generates cryptographically random values for `APP_SECRET_KEY` and
`AUTH_BOOTSTRAP_TOKEN`, sets `AUTH_ALLOW_LEGACY_HEADERS=false`, leaves all provider and Telegram
credentials blank, writes the ignored `.env` with user-only permissions where the platform allows,
and refuses to overwrite an existing file unless `--force` is passed.

Packaged startup requires a non-placeholder `APP_SECRET_KEY`; it never falls back to a committed
Compose default. An empty `AUTH_BOOTSTRAP_TOKEN` is valid only after an owner already exists and
means that creation of new bootstrap invitations is disabled. Direct credential-free demo startup
may omit both secrets, but booking-action and bootstrap endpoints then return their existing typed
disabled responses.

The first-owner flow is:

1. run the initializer and start the stack;
2. enter the generated bootstrap token in the local UI;
3. call `POST /api/v1/auth/bootstrap-invitation` with
   `X-Flight-Hunter-Bootstrap-Token`;
4. accept the returned one-time invitation through `POST /api/v1/auth/accept-invitation`;
5. use the returned bearer session for household-scoped operations;
6. clear `AUTH_BOOTSTRAP_TOKEN` and restart if no further owner bootstrap invitations are needed.

Session tokens remain hashed in SQLite. Bearer authentication takes precedence over legacy
headers. `AUTH_ALLOW_LEGACY_HEADERS=true` is an explicit direct-development compatibility option
and is forbidden in the packaged release and CI acceptance environment.

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

- `api`: is the sole migration owner, runs Alembic migrations once, then serves FastAPI and the
  bundled web UI;
- `worker`: waits for API readiness, then runs the existing durable worker loop.

SQLite remains the intentional local persistence engine. The release will not introduce Redis,
PostgreSQL, a separate frontend build, or a reverse proxy. SQLite connection settings and worker
claim behavior must remain safe for the existing low-concurrency personal workload.

All application processes use one `create_database_engine(database_url)` factory. For file-backed
SQLite it configures a 30-second driver timeout and connection pragmas
`journal_mode=WAL`, `busy_timeout=30000`, `foreign_keys=ON`, and `synchronous=NORMAL`. In-memory
test databases retain their compatible pool behavior. Alembic keeps its own migration connection
but applies the same foreign-key and busy-timeout safety settings.

Job claims remain compare-and-swap updates: candidate selection may race, but only an `UPDATE`
whose expected queued/retry state still matches can set `locked_by`, increment attempts, and
return a claimed job. The claim transaction is committed before provider/browser work begins.
Concurrency integration tests use two independent sessions to prove that one job is claimed once,
that API and worker writes survive expected contention inside the timeout, and that a crashed
claim is recovered by the existing lease path.

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

The minimal packaged worker has `PERSONAL_OBSERVER_ENABLED=false` and does not claim browser jobs.
In an explicitly browser-enabled direct runtime, a missing Playwright package or Chromium binary
is a permanent local configuration failure: the job becomes `failed` with
`browser_runtime_unavailable`, no `next_retry_at`, and no automatic retry. After running browser
bootstrap, the operator must explicitly create or requeue the observation. Transient navigation,
timeout, or provider-page failures keep their existing classified retry policy.

CI installs the browser runtime before running browser smoke and local web E2E checks.

The browser E2E server uses a temporary migrated SQLite database, generated test secrets,
`AUTH_ALLOW_LEGACY_HEADERS=false`, fake provider mode, disabled Telegram/live providers, and a
random loopback port. The suite covers these exact scenarios:

1. load `/`, assert representative Russian headings are readable, and reject mojibake markers;
2. bootstrap an owner, accept the invitation, and confirm `/api/v1/auth/me` through the UI session;
3. submit an exact-date fake-provider search and assert demo/source/freshness/passenger labels;
4. create a watch, list it, pause it, resume it, open history, and archive it;
5. submit a signed booking-action token fixture and assert lazy resolution plus visible failure for
   an expired/tampered token;
6. verify a typed unavailable message when live Aviasales is disabled;
7. verify `/healthz` and `/readyz` without making any external provider request.

Each scenario starts from deterministic seeded state and records a screenshot only on failure.
Browser tests use the `browser_e2e` pytest marker; aggregate credential-free checks exclude that
marker unless browser bootstrap has completed, while the dedicated Ubuntu browser job requires it.

### 5.4 Container packaging

The Docker image must:

- use the locked dependency graph;
- run as a non-root user;
- contain application source and Alembic migrations;
- expose a health endpoint without embedding credentials;
- stop cleanly on termination;
- contain no development, scraping/browser runtime dependencies, or provider-secret material.
  Optional observer source code may remain in the application package so existing opt-in direct
  development commands import cleanly, but Playwright, Chromium, Crawl4AI, and Scrapling are not
  installed in the minimal image.

Compose must:

- bind port 8000 to `127.0.0.1` only;
- start API and worker in the default profile;
- add API and worker healthchecks;
- use restart policies appropriate for a local daemon;
- persist SQLite data in a named volume;
- prevent the worker from claiming jobs before migrations and API readiness;
- allow optional deal-discovery services only through their existing profile.

The health interfaces are fixed:

- `GET /healthz` is liveness only. It returns HTTP 200 with
  `{"app":"Flight Hunter","status":"ok","external_credentials_required":false}` and performs no
  database or provider call.
- `GET /readyz` executes a database `SELECT 1` and verifies that the stored Alembic revision equals
  the code migration head. It returns HTTP 200 with `status=ready` and `database=ok`; database
  connection failure returns HTTP 503/code `database_unavailable`, and revision mismatch returns
  HTTP 503/code `migration_pending`. It never calls an external provider.
- The API Compose healthcheck calls `/readyz` through Python's standard-library HTTP client with a
  5-second timeout, 10-second interval, 5 retries, and a 30-second start period.
- The worker Compose healthcheck runs `flight-hunter-worker-healthcheck --max-age-seconds 120`.
  It succeeds only with a recent non-failed heartbeat and no critical matching alert. It uses a
  30-second interval, 10-second timeout, 5 retries, and a 45-second start period.

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

Each stage emits one JSON object with keys and types represented by this valid example:
`{"schema_version":1,"stage":"tests","status":"passed","code":"ok","skipped_reason":null}`.
`schema_version` is integer `1`; `stage` and `code` are non-empty strings; `status` is one of
`passed`, `failed`, or `skipped`; and `skipped_reason` is null or a non-empty string.
Human-readable progress goes to stderr; stdout remains machine-readable. A failed required stage
sets the process exit code to non-zero. An optional stage may be `skipped` only with a populated
stable reason such as `docker_unavailable` or `browser_runtime_not_requested`.

Migration validation has two paths. The fresh path upgrades an empty temporary SQLite database to
head. The upgrade path creates a temporary database at revision `0017`, inserts representative
owner/household/session and watch records using the revision-0017 schema, upgrades through every
remaining migration to head, and verifies both the preserved records and the final Alembic
revision. Its exact automated entry point is
`uv run pytest tests/integration/test_upgrade_from_pre_v1.py -q` and release-check stage name is
`upgrade_migrations`.

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

The main code-quality job runs on both `ubuntu-latest` and `windows-latest`. Browser E2E and Docker
build run on Ubuntu. The Windows job executes the release-check's non-Docker stages from a copied
workspace under a path containing `Документы` and `Flight Hunter`; commands use PowerShell Core
and must not rely on Bash or GNU Make. CI never sets `AUTH_ALLOW_LEGACY_HEADERS=true`.

CI receives no live provider credentials and makes no Aviasales calls.

### 5.7 Versioning and documentation

Set the package and API version to `1.0.0`. Add:

- `CHANGELOG.md` with the local v1 scope;
- `SECURITY.md` describing local-only exposure and secret handling;
- a local deployment/update guide;
- exact browser-bootstrap and release-check commands;
- accurate backup/verify/restore commands;
- provider contract verification dated 2026-07-13;
- updated `.env.example` with SQLite/local-v1 defaults and blank secret/provider values;
- reconciled `docs/ARCHITECTURE.md` that distinguishes the implemented local-v1 architecture from
  the long-term optional target;
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

The local-v1 stable mappings are below. HTTP statuses apply only to direct Aviasales-specific
operations (`/api/v1/aviasales/*` and booking resolution). Aggregate `/api/v1/searches` and
`/api/v1/searches/date-matrix` return HTTP 200 with fake/partial results and put the same stable
codes in `provider_errors` or `pricing_denials`; a disabled or failed Aviasales call must not hide
valid fake/other-source results.

| Condition | Direct HTTP/command result | Retry | Stable code |
|---|---:|---:|---|
| Aviasales disabled | HTTP 503 | no | `aviasales_search_disabled` |
| Aviasales credentials absent | HTTP 503 | no | `aviasales_search_credentials_missing` |
| Aviasales credential shape invalid | HTTP 503 | no | `aviasales_search_credentials_invalid` |
| Provider authentication rejected (HTTP 401) | HTTP 502 | no | `aviasales_search_auth_failed` |
| CloudFront/provider block (HTTP 403) | HTTP 502 | no | `aviasales_search_blocked` |
| Provider rate limit | HTTP 429 plus safe `Retry-After` when supplied | header/backoff | `aviasales_search_rate_limited` |
| Provider transport/network failure | HTTP 502 | bounded transport retry | `aviasales_search_unavailable` |
| Required provider schema missing/invalid | HTTP 502 | no | `aviasales_search_schema_error` |
| Browser package or Chromium absent | CLI non-zero / job failed | no | `browser_runtime_unavailable` |
| Database cannot be opened | HTTP 503 readiness | healthcheck retry | `database_unavailable` |
| Database revision is not current | HTTP 503 readiness | after migration | `migration_pending` |
| Cached or stale offer | HTTP 200, explicit freshness field | n/a | `cached` or `stale`, never `live` |

All HTTP failures use the repository's coded error envelope rather than FastAPI's raw `detail`
shape. Provider exception text, request IDs, signed URLs, tokens, markers, and signatures are not
returned.

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
10. fixture-based Aviasales contract tests pass. A manual sanitized suggest and exact-date search
    smoke is attempted when local credentials and network are available, without exposing
    credentials or raw provider data. `aviasales_search_blocked`,
    `aviasales_search_rate_limited`, or `aviasales_search_unavailable` is recorded as an external
    limitation and does not fail the credential-free release gate;
11. documentation matches the exact commands and observed results;
12. no `TODO`, `pass`, `NotImplementedError`, fake return, or commented incomplete code exists in
    the changed production flow.

### 8.1 Acceptance ownership matrix

| Requirement | Owner | Automated evidence / exact command |
|---|---|---|
| Full Python behavior | `src/flight_hunter/`, `tests/unit`, `tests/integration` | `uv run pytest --disable-warnings -q` |
| Formatting and lint | all tracked Python | `uv run ruff format --check .` and `uv run ruff check .` |
| Public type safety | `src/flight_hunter/` | `uv run mypy` |
| Fresh migrations | `migrations/`, persistence | `uv run flight-hunter-release-check --stage migrations` |
| Existing database upgrade | migrations and pre-v1 fixture builder | `uv run pytest tests/integration/test_upgrade_from_pre_v1.py -q` |
| Secret/log safety | ops and full tree | `uv run flight-hunter-security-scan` |
| Russian UI and browser flows | `api/web.py`, `tests/e2e` | `uv run pytest tests/e2e -q` after `uv run flight-hunter-browser-bootstrap` |
| API liveness/readiness | `api/app.py`, database engine factory | unit tests plus `uv run flight-hunter-release-check --stage health` |
| SQLite API/worker contention | database engine factory and repositories | `uv run pytest tests/integration/test_sqlite_concurrency.py -q` |
| Compose topology | `compose.yaml`, `Dockerfile` | `docker compose config` and `docker compose build` |
| Windows/PowerShell support | command surfaces and docs | `windows-latest` CI code-quality job |
| Aviasales offline contract | provider schemas/client/mapper | `uv run pytest tests/unit/providers/aviasales_search -q` |
| Aviasales external smoke | manual provider check | `uv run flight-hunter-source-smoke --source aviasales_search` plus sanitized exact-date smoke |
| Backup/restore | `ops/backup.py`, runbook | `uv run pytest tests/unit/ops/test_backup_restore.py -q` |
| Release aggregate | all credential-free gates | `uv run flight-hunter-release-check` |

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
