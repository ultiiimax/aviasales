# Flight Hunter Local v1 Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Flight Hunter 1.0.0 as a reproducible, secure, local-only FastAPI/SQLite release with readable Russian UI, reliable worker processing, optional live Aviasales search, browser acceptance coverage, and a single credential-free quality gate.

**Architecture:** Keep the existing modular Python monolith. Add a shared SQLite engine factory, explicit readiness and release command surfaces, typed provider failure mapping, and hardened Compose packaging; preserve the existing domain/application/provider boundaries and server-bundled web UI.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, SQLite/Alembic, curl_cffi, pytest, Playwright, Ruff, mypy, uv, Docker Compose, GitHub Actions.

## Global Constraints

- Target package and API version is exactly `1.0.0`.
- Packaged network exposure is exactly `127.0.0.1:8000`.
- Demo mode requires no external provider or Telegram credentials.
- `AUTH_ALLOW_LEGACY_HEADERS=false` in packaged and CI environments.
- Money remains integer minor units plus ISO currency.
- All datetimes remain timezone-aware.
- Live provider calls never run in CI.
- Provider secrets, markers, raw refs, signed URLs, and session tokens never enter logs or client assets.
- Existing migrations are immutable; any schema change uses a new migration.
- Each task follows red-green-refactor and ends with fresh focused verification.

---

## Planned File Structure

### New focused units

- `src/flight_hunter/persistence/database.py`: shared async-engine construction and SQLite pragmas.
- `src/flight_hunter/ops/init_local.py`: safe `.env` initialization.
- `src/flight_hunter/ops/browser_bootstrap.py`: optional browser dependency/runtime bootstrap.
- `src/flight_hunter/ops/release_check.py`: versioned release-stage orchestration and JSON results.
- `tests/integration/test_sqlite_concurrency.py`: API/worker contention and single-claim proof.
- `tests/integration/test_upgrade_from_pre_v1.py`: populated revision-0021 compatibility proof.
- `tests/e2e/conftest.py`: temporary migrated server and browser fixtures.
- `tests/e2e/test_local_v1_browser.py`: required local browser scenarios.
- `.github/workflows/ci.yml`: Linux, Windows/Unicode-path, browser, and image gates.
- `CHANGELOG.md`, `SECURITY.md`, `docs/runbooks/local-deployment.md`: release documentation.

### Existing units to modify

- `src/flight_hunter/api/app.py`: 1.0.0 metadata, readiness, coded Aviasales errors.
- `src/flight_hunter/api/web.py`: repaired UTF-8 literals only; existing DOM/API contracts stay stable.
- `src/flight_hunter/config.py`: credential-shape state and safe local defaults.
- `src/flight_hunter/ops/worker.py` and other DB entry points: shared engine factory.
- `src/flight_hunter/application/personal_observations.py` and personal observer adapter: terminal missing-runtime classification.
- `src/flight_hunter/providers/aviasales_search/client.py`, `adapter.py`, and `schemas.py`: typed provider error classes.
- `src/flight_hunter/ops/source_smoke.py`: sanitized exact-date live smoke.
- `Dockerfile`, `compose.yaml`, `Makefile`, `pyproject.toml`, `.env.example`: release command and runtime surface.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/provider-contracts/aviasales-search.md`, `IMPLEMENTATION_STATUS.md`: verified release truth.

---

### Task 1: Remove Wall-Clock Test Expiry

**Files:**
- Modify: `tests/unit/ops/test_worker_command.py`
- Modify: `tests/unit/providers/personal_observer/test_worker_cli.py`

**Interfaces:**
- Consumes: existing `PersonalObservationService` clock injection.
- Produces: non-expired fixture jobs created relative to `datetime.now(UTC)`; explicit expiry tests retain fixed past clocks.

- [ ] **Step 1: Add a regression assertion for current validity**

Add a helper and assertion to each fixture module:

```python
def _active_clock() -> datetime:
    return datetime.now(UTC)


def test_default_queued_job_clock_is_current() -> None:
    now = _active_clock()
    assert now - timedelta(seconds=2) <= _active_clock() <= now + timedelta(seconds=2)
```

Use `_active_clock` when normal queued jobs are created. Keep `lambda: datetime(2026, 1, 1,
tzinfo=UTC)` only in the intentional `job_expired` case.

- [ ] **Step 2: Run the six previously failing tests before editing helpers**

Run:

```powershell
uv run pytest tests/unit/ops/test_worker_command.py tests/unit/providers/personal_observer/test_worker_cli.py -q
```

Expected: six failures showing zero claimed jobs or `job_expired`.

- [ ] **Step 3: Replace fixed active-job clocks and travel dates**

Change normal helper construction to:

```python
clock = _active_clock
departure_date = (clock().date() + timedelta(days=60)).isoformat()
return_date = (clock().date() + timedelta(days=70)).isoformat()
```

Pass `clock=clock` to `PersonalObservationService`. Do not alter production expiry policy.

- [ ] **Step 4: Verify the worker slice**

Run the focused command from Step 2.

Expected: all tests in both files pass; the explicit expired-job test still produces
`job_expired`.

- [ ] **Step 5: Commit**

```powershell
git add tests/unit/ops/test_worker_command.py tests/unit/providers/personal_observer/test_worker_cli.py
git commit -m "test: remove worker clock expiry"
```

---

### Task 2: Centralize SQLite Safety and Readiness

**Files:**
- Create: `src/flight_hunter/persistence/database.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `src/flight_hunter/ops/airport_import.py`
- Modify: `src/flight_hunter/ops/live_observation_cleanup.py`
- Modify: `src/flight_hunter/ops/seed_demo.py`
- Modify: `src/flight_hunter/ops/worker.py`
- Modify: `src/flight_hunter/ops/worker_healthcheck.py`
- Modify: `src/flight_hunter/providers/personal_observer/cli.py`
- Modify: `src/flight_hunter/providers/personal_observer/worker_cli.py`
- Test: `tests/unit/persistence/test_database.py`
- Test: `tests/unit/api/test_api_app.py`
- Create: `tests/integration/test_sqlite_concurrency.py`

**Interfaces:**
- Produces: `create_database_engine(database_url: str) -> AsyncEngine`.
- Produces: `GET /readyz` with `ReadyResponse` or coded HTTP 503.
- Consumes: existing repository compare-and-swap `claim_queued` methods.

- [ ] **Step 1: Write failing pragma and readiness tests**

```python
@pytest.mark.anyio
async def test_file_sqlite_engine_enables_local_safety_pragmas(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite+aiosqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    async with engine.connect() as connection:
        journal = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
        timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
    await engine.dispose()
    assert str(journal).lower() == "wal"
    assert timeout == 30_000
    assert foreign_keys == 1
```

Add API tests asserting `/healthz` does not touch the DB, `/readyz` returns `database_unavailable`
for an invalid path, and a migrated DB returns `{"status":"ready","database":"ok"}`.

- [ ] **Step 2: Run the new tests and confirm missing interfaces**

```powershell
uv run pytest tests/unit/persistence/test_database.py tests/unit/api/test_api_app.py -q
```

Expected: import/route failures for `create_database_engine` and `/readyz`.

- [ ] **Step 3: Implement the shared engine factory**

```python
from __future__ import annotations

from typing import Any

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_database_engine(database_url: str) -> AsyncEngine:
    url = make_url(database_url)
    connect_args: dict[str, object] = {}
    if url.drivername.startswith("sqlite"):
        connect_args["timeout"] = 30.0
    engine = create_async_engine(database_url, connect_args=connect_args)
    if url.drivername.startswith("sqlite"):
        file_backed = url.database not in {None, "", ":memory:"}

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA synchronous=NORMAL")
                if file_backed:
                    cursor.execute("PRAGMA journal_mode=WAL")
            finally:
                cursor.close()
    return engine
```

Replace every production `create_async_engine` call listed in Files with this factory.

- [ ] **Step 4: Implement database readiness**

Add:

```python
class ReadyResponse(BaseModel):
    status: Literal["ready"]
    database: Literal["ok"]


@app.get("/readyz", response_model=ReadyResponse)
async def readyz() -> ReadyResponse | JSONResponse:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
            revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    except SQLAlchemyError:
        return _coded_error_response(503, "database_unavailable", "database is unavailable")
    if revision != current_alembic_head():
        return _coded_error_response(503, "migration_pending", "database migration is pending")
    return ReadyResponse(status="ready", database="ok")
```

Implement `current_alembic_head()` with Alembic `ScriptDirectory.from_config` and no network call.

- [ ] **Step 5: Prove single-claim and contention behavior**

In `tests/integration/test_sqlite_concurrency.py`, create two engines/sessions against one file,
race `WatchScanJobRepository.claim_queued` with `asyncio.gather`, and assert the combined claim IDs
contain the job exactly once. Add a second test that holds a short write transaction, releases it,
and proves the other writer completes within the configured timeout.

- [ ] **Step 6: Run database and repository gates**

```powershell
uv run pytest tests/unit/persistence tests/integration/test_sqlite_concurrency.py tests/unit/api/test_api_app.py -q
uv run mypy
```

Expected: all pass.

- [ ] **Step 7: Commit**

```powershell
git add src/flight_hunter/persistence src/flight_hunter/api/app.py src/flight_hunter/ops src/flight_hunter/providers/personal_observer tests/unit/persistence tests/unit/api/test_api_app.py tests/integration/test_sqlite_concurrency.py
git commit -m "feat: harden local sqlite runtime"
```

---

### Task 3: Add Safe Local Initialization and Auth Defaults

**Files:**
- Create: `src/flight_hunter/ops/init_local.py`
- Modify: `src/flight_hunter/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `tests/unit/test_config.py`
- Create: `tests/unit/ops/test_init_local.py`
- Modify: `tests/unit/test_env_example.py`
- Modify: `tests/unit/api/test_auth_api.py`

**Interfaces:**
- Produces: `initialize_local_env(template_path: Path, output_path: Path, force: bool = False) -> InitLocalResult`.
- Produces CLI: `flight-hunter-init-local --output .env [--force]`.
- Produces: `AppSettings.aviasales_search_credentials_valid: bool`.

- [ ] **Step 1: Write initializer and credential-shape tests**

```python
def test_initializer_generates_safe_local_secrets(tmp_path: Path) -> None:
    result = initialize_local_env(
        template_path=Path(".env.example"),
        output_path=tmp_path / ".env",
    )
    values = parse_env_file(result.path)
    assert result.ok
    assert len(values["APP_SECRET_KEY"]) >= 43
    assert len(values["AUTH_BOOTSTRAP_TOKEN"]) >= 43
    assert values["AUTH_ALLOW_LEGACY_HEADERS"] == "false"
    assert values["AVIASALES_SEARCH_SIGNATURE"] == ""
    assert values["AVIASALES_SEARCH_MARKER"] == ""
```

Also assert a second call returns `env_exists` and does not change bytes unless `force=True`.

- [ ] **Step 2: Run tests and observe missing CLI/state**

```powershell
uv run pytest tests/unit/ops/test_init_local.py tests/unit/test_config.py tests/unit/test_env_example.py tests/unit/api/test_auth_api.py -q
```

Expected: missing module/properties and unsafe legacy default assertions fail.

- [ ] **Step 3: Implement initialization**

Use `secrets.token_urlsafe(48)`, replace only exact `KEY=` lines, keep provider/Telegram secrets
blank, set SQLite local defaults, write UTF-8 with LF, and return JSON without secret values:

```python
@dataclass(frozen=True, slots=True)
class InitLocalResult:
    ok: bool
    code: str
    path: Path


def initialize_local_env(*, template_path: Path, output_path: Path, force: bool = False) -> InitLocalResult:
    if output_path.exists() and not force:
        return InitLocalResult(False, "env_exists", output_path)
    values = {
        "APP_SECRET_KEY": secrets.token_urlsafe(48),
        "AUTH_BOOTSTRAP_TOKEN": secrets.token_urlsafe(48),
        "AUTH_ALLOW_LEGACY_HEADERS": "false",
        "DATABASE_URL": "sqlite+aiosqlite:///./flight_hunter_dev.db",
    }
    rendered = replace_env_values(template_path.read_text(encoding="utf-8"), values)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    output_path.chmod(0o600)
    return InitLocalResult(True, "ok", output_path)
```

- [ ] **Step 4: Register the command and secure defaults**

Add to `[project.scripts]`:

```toml
flight-hunter-init-local = "flight_hunter.ops.init_local:main"
```

Set `AUTH_ALLOW_LEGACY_HEADERS=false` in `.env.example`; keep `APP_SECRET_KEY`,
`AUTH_BOOTSTRAP_TOKEN`, Aviasales, and Telegram secret values blank. Preserve direct demo startup
behavior when secrets are absent.

- [ ] **Step 5: Verify auth bootstrap and initializer**

Run the Step 2 command.

Expected: all pass; bearer session still wins over headers and stored tokens remain hashed.

- [ ] **Step 6: Commit**

```powershell
git add src/flight_hunter/ops/init_local.py src/flight_hunter/config.py pyproject.toml .env.example tests/unit
git commit -m "feat: add safe local initialization"
```

---

### Task 4: Stabilize Aviasales Failure and Smoke Contracts

**Files:**
- Modify: `src/flight_hunter/providers/aviasales_search/client.py`
- Modify: `src/flight_hunter/providers/aviasales_search/adapter.py`
- Modify: `src/flight_hunter/providers/aviasales_search/schemas.py`
- Modify: `src/flight_hunter/config.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `src/flight_hunter/application/search_service.py`
- Modify: `src/flight_hunter/ops/source_smoke.py`
- Modify: `tests/unit/providers/aviasales_search/test_client.py`
- Modify: `tests/unit/providers/aviasales_search/test_adapter.py`
- Modify: `tests/unit/api/test_aviasales_mobile_api.py`
- Modify: `tests/unit/api/test_api_app.py`
- Modify: `tests/unit/ops/test_source_smoke.py`

**Interfaces:**
- Produces exceptions: `AviasalesSearchAuthFailed`, `AviasalesSearchBlocked`,
  `AviasalesSearchRateLimited`, `AviasalesSearchSchemaError`.
- Produces direct HTTP mappings from the approved spec.
- Produces CLI flags: `--exact-search --origin --destination --departure-offset-days`.

- [ ] **Step 1: Add negative client and HTTP mapping tests**

```python
def test_client_classifies_upstream_auth_failure() -> None:
    client = client_with_response(status=401, payload={})
    with pytest.raises(AviasalesSearchAuthFailed, match="aviasales_search_auth_failed"):
        client.suggest_places("LED")


def test_direct_endpoint_preserves_rate_limit_code() -> None:
    response = client.get("/api/v1/aviasales/suggest?q=LED")
    assert response.status_code == 429
    assert response.json()["code"] == "aviasales_search_rate_limited"
```

Add aggregate search/date-matrix tests asserting HTTP 200, valid fake/partial data, and stable
`provider_errors`/`pricing_denials` when Aviasales is disabled, blocked, or unavailable.

- [ ] **Step 2: Run provider and API tests to verify red state**

```powershell
uv run pytest tests/unit/providers/aviasales_search tests/unit/api/test_aviasales_mobile_api.py tests/unit/api/test_api_app.py tests/unit/ops/test_source_smoke.py -q
```

Expected: raw `detail` envelopes and collapsed unavailable codes fail new assertions.

- [ ] **Step 3: Add typed client/schema exceptions**

```python
class AviasalesSearchAuthFailed(AviasalesSearchError):
    pass


class AviasalesSearchSchemaError(AviasalesSearchError):
    pass
```

Map 401 before 403, never retry either, retain `Retry-After` on 429, and wrap
`AviasalesSearchParseError`, invalid/empty JSON, and missing required fields as
`aviasales_search_schema_error` without raw payload text.

- [ ] **Step 4: Add one coded error adapter for direct routes**

```python
def _aviasales_error_response(exc: AviasalesSearchError) -> JSONResponse:
    if isinstance(exc, AviasalesSearchRateLimited):
        headers = ({"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else {})
        return JSONResponse(
            status_code=429,
            content={"code": str(exc), "message": "provider rate limited"},
            headers=headers,
        )
    status, code = {
        AviasalesSearchAuthFailed: (502, "aviasales_search_auth_failed"),
        AviasalesSearchBlocked: (502, "aviasales_search_blocked"),
        AviasalesSearchSchemaError: (502, "aviasales_search_schema_error"),
    }.get(type(exc), (502, "aviasales_search_unavailable"))
    return _coded_error_response(status_code=status, code=code, message="provider unavailable")
```

Return this envelope from direct Aviasales routes. Distinguish disabled, missing, and locally
invalid credentials before provider construction. Preserve aggregate partial-success behavior.

- [ ] **Step 5: Extend sanitized exact-date smoke**

Extend `SourceSmokeResult` with `source_ids: tuple[str, ...]` and
`freshness_values: tuple[str, ...]`. With `--exact-search`, compute
`date.today() + timedelta(days=departure_offset_days)`, use one adult/RUB, call the adapter, and
print counts/source/freshness only. Reject missing route flags with `smoke_arguments_invalid`.

- [ ] **Step 6: Verify provider contract and secret absence**

Run the Step 2 command and:

```powershell
uv run flight-hunter-security-scan
```

Expected: all pass, zero findings.

- [ ] **Step 7: Commit**

```powershell
git add src/flight_hunter/providers/aviasales_search src/flight_hunter/config.py src/flight_hunter/api/app.py src/flight_hunter/application/search_service.py src/flight_hunter/ops/source_smoke.py tests/unit/providers/aviasales_search tests/unit/api tests/unit/ops/test_source_smoke.py
git commit -m "feat: stabilize Aviasales release errors"
```

---

### Task 5: Repair and Guard the Russian Web UI

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Modify: `tests/unit/api/test_web_ui.py`

**Interfaces:**
- Preserves: all existing DOM IDs, JavaScript function names, and `/api/v1/*` paths.
- Produces: UTF-8 response containing readable Russian labels and no known mojibake markers.

- [ ] **Step 1: Write the failing response-level encoding test**

```python
def test_web_ui_contains_readable_russian_without_mojibake() -> None:
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert response.encoding.lower() == "utf-8"
    for text in ("Найти билеты", "Отслеживания", "Источник", "Недостаточно данных"):
        assert text in response.text
    for marker in ("Рќ", "РЎ", "вЂ", "рџ", "Р Р"):
        assert marker not in response.text
```

- [ ] **Step 2: Run the web test and capture the current corruption**

```powershell
uv run pytest tests/unit/api/test_web_ui.py -q
```

Expected: failure with missing Russian labels and mojibake markers present.

- [ ] **Step 3: Perform one bounded encoding repair**

Apply exactly one Windows-1251-byte to UTF-8 repair pass to `api/web.py`. For characters that are
undefined in Python's cp1251 encoder but have code points 0x80–0x9F, map the code point directly to
the original byte before decoding the collected bytes as UTF-8. Review the diff to ensure Python,
HTML, CSS, JS, IDs, and URLs are unchanged except for user-visible Unicode literals.

Do not add `ftfy` or another runtime dependency. Do not repeatedly transform already-correct
text.

- [ ] **Step 4: Verify web contracts and search for corruption**

```powershell
uv run pytest tests/unit/api/test_web_ui.py -q
rg.exe -n "Рќ|РЎ|вЂ|рџ|Р Р" src/flight_hunter/api/web.py
```

Expected: tests pass and `rg` returns no mojibake hits.

- [ ] **Step 5: Commit**

```powershell
git add src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py
git commit -m "fix: restore Russian web interface"
```

---

### Task 6: Make Browser Runtime and E2E Explicit

**Files:**
- Create: `src/flight_hunter/ops/browser_bootstrap.py`
- Modify: `src/flight_hunter/application/personal_observations.py`
- Modify: `src/flight_hunter/domain/observation.py`
- Modify: `src/flight_hunter/providers/personal_observer/adapter.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Modify: `tests/unit/application/test_personal_observations.py`
- Modify: `tests/unit/providers/personal_observer/test_runner_adapter.py`
- Modify: `tests/unit/ops/test_worker_command.py`
- Create: `tests/unit/ops/test_browser_bootstrap.py`
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_local_v1_browser.py`

**Interfaces:**
- Produces CLI: `flight-hunter-browser-bootstrap`.
- Produces terminal `ObservationErrorCode.BROWSER_RUNTIME_UNAVAILABLE`.
- Registers strict marker `browser_e2e`.

- [ ] **Step 1: Write terminal-classification tests**

```python
@pytest.mark.anyio
async def test_missing_browser_runtime_fails_without_retry(service, claimed_job) -> None:
    service.runner = PlaywrightUnavailableRunner()
    decision = await service.run_claimed_job(claimed_job)
    assert not decision.accepted
    assert not decision.retry_scheduled
    assert decision.job is not None
    assert decision.job.status == ObservationStatus.FAILED
    assert decision.job.error_code == "browser_runtime_unavailable"
    assert decision.job.next_retry_at is None
```

Update the existing worker test that currently expects a retry.

- [ ] **Step 2: Verify current retry behavior fails the new contract**

```powershell
uv run pytest tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_runner_adapter.py tests/unit/ops/test_worker_command.py -q
```

Expected: missing Playwright is still retry-scheduled.

- [ ] **Step 3: Preserve the stable runtime error through the adapter**

Add `BROWSER_RUNTIME_UNAVAILABLE` to `ObservationErrorCode`. Add optional
`error_code: ObservationErrorCode | None` to `PersonalObservationRunnerError`; map
`PLAYWRIGHT_UNAVAILABLE` to `ObservationStatus.FAILED` plus that code. In the service use
`exc.error_code or _error_code_for_status(exc.status)`.

- [ ] **Step 4: Implement browser bootstrap**

```python
def browser_bootstrap(*, run: CommandRunner = subprocess.run) -> int:
    commands = (
        ("uv", "sync", "--group", "dev", "--group", "scraping"),
        ("uv", "run", "playwright", "install", "chromium"),
    )
    for command in commands:
        completed = run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0
```

Unit tests inject a fake runner and assert exact argv/no shell.

- [ ] **Step 5: Register strict marker and write browser fixtures**

Add to `pyproject.toml`:

```toml
markers = ["browser_e2e: requires bootstrapped Playwright Chromium"]
```

`tests/e2e/conftest.py` must allocate a free loopback port, migrate a temporary SQLite DB, start
Uvicorn in a background thread with fake/live-disabled settings and generated secrets, yield a
Playwright page, then stop server/browser in `finally`.

- [ ] **Step 6: Implement the seven approved browser scenarios**

Mark every test `@pytest.mark.browser_e2e`. Cover readable root UI, owner bootstrap/accept/me,
fake exact search labels, watch lifecycle/history, signed booking token success plus tamper/expiry,
disabled Aviasales message, and `/healthz`/`/readyz`. Save screenshots under
`.pytest-tmp/browser-failures` only when a test fails.

- [ ] **Step 7: Bootstrap and run browser gates**

```powershell
uv run flight-hunter-browser-bootstrap
uv run flight-hunter-browser-smoke
uv run pytest tests/e2e -q -m browser_e2e --strict-markers
```

Expected: browser smoke and all selected E2E pass.

- [ ] **Step 8: Commit**

```powershell
git add src/flight_hunter/application/personal_observations.py src/flight_hunter/domain/observation.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/ops/browser_bootstrap.py pyproject.toml Makefile tests/unit tests/e2e
git commit -m "test: add local browser acceptance"
```

---

### Task 7: Add Release Check and Pre-v1 Upgrade Proof

**Files:**
- Create: `src/flight_hunter/ops/release_check.py`
- Modify: `pyproject.toml`
- Modify: `Makefile`
- Create: `tests/unit/ops/test_release_check.py`
- Create: `tests/integration/test_upgrade_from_pre_v1.py`

**Interfaces:**
- Produces: `ReleaseStageResult(schema_version: int, stage: str, status: str, code: str, skipped_reason: str | None)`.
- Produces CLI: `flight-hunter-release-check [--stage NAME] [--include-browser] [--include-docker-build]`.

- [ ] **Step 1: Write release-result and command-order tests**

```python
def test_default_release_stages_are_deterministic() -> None:
    assert default_stages() == (
        "tests", "format", "lint", "types", "migrations", "upgrade_migrations",
        "security", "compose", "health", "browser",
    )


def test_skipped_stage_has_versioned_json_reason() -> None:
    result = ReleaseStageResult.skipped("browser", "browser_runtime_not_requested")
    assert result.to_json_dict() == {
        "schema_version": 1,
        "stage": "browser",
        "status": "skipped",
        "code": "skipped",
        "skipped_reason": "browser_runtime_not_requested",
    }
```

Mock command execution and assert subprocess output is relayed to stderr while stdout contains
only one JSON object per stage.

- [ ] **Step 2: Run tests and confirm missing command**

```powershell
uv run pytest tests/unit/ops/test_release_check.py -q
```

Expected: missing module.

- [ ] **Step 3: Implement stage orchestration**

Use argv tuples and `subprocess.run(..., shell=False, capture_output=True, text=True)`. Commands:

```python
STAGE_COMMANDS = {
    "tests": ("uv", "run", "pytest", "--disable-warnings", "-q", "-m", "not browser_e2e", "--strict-markers"),
    "format": ("uv", "run", "ruff", "format", "--check", "."),
    "lint": ("uv", "run", "ruff", "check", "."),
    "types": ("uv", "run", "mypy"),
    "migrations": ("uv", "run", "pytest", "tests/unit/persistence/test_alembic_upgrade.py", "-q"),
    "upgrade_migrations": ("uv", "run", "pytest", "tests/integration/test_upgrade_from_pre_v1.py", "-q"),
    "security": ("uv", "run", "flight-hunter-security-scan"),
    "compose": ("docker", "compose", "config"),
    "health": ("uv", "run", "pytest", "tests/unit/api/test_api_app.py", "-q", "-k", "health"),
}
```

The `compose` runner supplies a subprocess-only environment containing a generated
`APP_SECRET_KEY`, blank optional provider values, and `AUTH_ALLOW_LEGACY_HEADERS=false`; it does
not write or print those values. This lets `docker compose config` validate required-variable
syntax on clean CI without weakening Compose startup requirements.

Browser defaults to skipped; `--include-browser` runs smoke plus marker-selected E2E. Docker build
is opt-in and reports `docker_unavailable` when the engine ping fails.

- [ ] **Step 4: Build the immediate pre-v1 database test**

Use a temporary Alembic config with its URL set to a temp DB. Run `upgrade 0021`, insert valid
records into `households`, `users`, memberships, auth sessions, watches, browser control,
heartbeats, drain control, and deal discovery jobs using SQLAlchemy Core/text matching revision
0021 columns. Run `upgrade head`, assert rows and values remain, and assert `alembic_version`
matches `ScriptDirectory.get_current_head()`.

- [ ] **Step 5: Register commands and run release unit/integration tests**

Add:

```toml
flight-hunter-release-check = "flight_hunter.ops.release_check:main"
```

Run:

```powershell
uv run pytest tests/unit/ops/test_release_check.py tests/integration/test_upgrade_from_pre_v1.py -q
uv run flight-hunter-release-check --stage upgrade_migrations
```

Expected: pass and one `schema_version: 1` result.

- [ ] **Step 6: Commit**

```powershell
git add src/flight_hunter/ops/release_check.py pyproject.toml Makefile tests/unit/ops/test_release_check.py tests/integration/test_upgrade_from_pre_v1.py
git commit -m "feat: add deterministic release gate"
```

---

### Task 8: Package and Continuously Verify 1.0.0

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/flight_hunter/__init__.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `Dockerfile`
- Modify: `compose.yaml`
- Modify: `tests/unit/ops/test_compose_config.py`
- Modify: `tests/unit/ops/test_makefile_commands.py`
- Modify: `tests/unit/api/test_api_app.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces package/API version `1.0.0`.
- Produces default services `api` and `worker` with fixed healthchecks.
- Produces Linux/Windows/browser/image CI jobs without live credentials.

- [ ] **Step 1: Write packaging assertions first**

Add tests asserting:

```python
assert project_version() == "1.0.0"
assert api_openapi()["info"]["version"] == "1.0.0"
assert compose["services"]["api"]["ports"] == ["127.0.0.1:8000:8000"]
assert "profiles" not in compose["services"]["worker"]
assert compose["services"]["worker"]["depends_on"]["api"]["condition"] == "service_healthy"
assert compose["services"]["api"]["healthcheck"]["interval"] == "10s"
assert compose["services"]["worker"]["healthcheck"]["interval"] == "30s"
```

Read the Dockerfile and assert a non-root `USER`, `/data` ownership, and no scraping group install.

- [ ] **Step 2: Run packaging tests to see current failures**

```powershell
uv run pytest tests/unit/ops/test_compose_config.py tests/unit/ops/test_makefile_commands.py tests/unit/api/test_api_app.py -q
```

Expected: current 0.1.0, profiled worker, public port, missing healthchecks/non-root fail.

- [ ] **Step 3: Harden the image**

Use locked runtime install, create uid 10001, own `/app` and `/data`, and switch users:

```dockerfile
RUN groupadd --gid 10001 flight-hunter \
    && useradd --uid 10001 --gid 10001 --create-home flight-hunter \
    && mkdir -p /data \
    && chown -R flight-hunter:flight-hunter /app /data
RUN uv sync --frozen --no-dev
USER 10001:10001
```

Do not install scraping/crawler/browser groups.

- [ ] **Step 4: Harden Compose topology**

Make API the sole migration owner. Bind `127.0.0.1:8000:8000`; set `init: true`,
`restart: unless-stopped`, `stop_grace_period`, and the approved healthchecks. Remove the worker
profile and migration command; make it depend on API `service_healthy`. Require
`APP_SECRET_KEY` from initialized `.env`, pass `AUTH_BOOTSTRAP_TOKEN`, and force
`AUTH_ALLOW_LEGACY_HEADERS=false`.

- [ ] **Step 5: Add CI jobs**

`quality-linux`: checkout, setup uv/Python 3.13, `uv sync --frozen --group dev`, run release-check
without browser/Docker build.

`quality-windows`: checkout into `Документы/Flight Hunter`, use PowerShell Core, sync locked dev
deps, run release-check with browser excluded.

`browser`: Ubuntu, sync dev+scraping, install Chromium, run browser smoke and
`pytest tests/e2e -m browser_e2e --strict-markers`.

`image`: Ubuntu, generate a temporary non-secret `.env` through init-local, validate Compose,
build the API/worker image, and never set live provider credentials.

- [ ] **Step 6: Verify local packaging where available**

```powershell
uv run pytest tests/unit/ops/test_compose_config.py tests/unit/ops/test_makefile_commands.py tests/unit/api/test_api_app.py -q
docker compose config
docker compose build
```

Expected: tests/config pass; build passes when Docker engine is available. If unavailable, record
`docker_unavailable` without claiming a successful image build.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml src/flight_hunter/__init__.py src/flight_hunter/api/app.py Dockerfile compose.yaml .github/workflows/ci.yml tests/unit
git commit -m "release: package Flight Hunter 1.0.0"
```

---

### Task 9: Reconcile Documentation and Run the Final Gate

**Files:**
- Create: `CHANGELOG.md`
- Create: `SECURITY.md`
- Create: `docs/runbooks/local-deployment.md`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/provider-contracts/aviasales-search.md`
- Modify: `docs/runbooks/backup-restore.md`
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify: `.env.example` if command examples require final alignment

**Interfaces:**
- Documents exact direct/Docker install, owner bootstrap, demo/live modes, update, backup,
  verification, restore, browser bootstrap, release check, and external-smoke behavior.

- [ ] **Step 1: Write documentation contract tests**

Extend `tests/unit/test_env_example.py` and add README assertions to ensure all documented commands
exist in `pyproject.toml`/Makefile, version is 1.0.0, loopback binding is stated, legacy headers are
false, and no old `466 passed` claim remains.

- [ ] **Step 2: Reconcile primary documentation**

`README.md`: separate demo, initialized local, Docker, Aviasales, browser, test, backup, and update
commands. State local-only support and Docker dependency explicitly.

`docs/ARCHITECTURE.md`: add an opening implemented-local-v1 section that is authoritative for
1.0.0 and label Next.js/Postgres/Redis/Caddy content as long-term optional target. Repair its
encoding if it contains the same mojibake pattern.

`CHANGELOG.md`: add `[1.0.0] - 2026-07-13` with verified scope.

`SECURITY.md`: loopback boundary, secrets, report process, public proxy non-support.

`local-deployment.md`: exact initialization/start/health/stop/update/rollback commands.

Provider contract: record 2026-07-13 suggest and exact-date live verification without credentials,
raw refs, prices, or purchase URLs.

- [ ] **Step 3: Run documentation and no-placeholder checks**

```powershell
uv run pytest tests/unit/test_env_example.py tests/unit/ops/test_makefile_commands.py -q
rg.exe -n "TODO|FIXME|NotImplementedError|\bpass\b|fake return" src/flight_hunter
git diff --check
```

Expected: tests pass; search returns no production-flow placeholders; diff check is clean.

- [ ] **Step 4: Run the full credential-free gate fresh**

```powershell
uv run flight-hunter-release-check
uv run pytest --disable-warnings -q -m "not browser_e2e" --strict-markers
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run flight-hunter-security-scan
```

Read every exit code and result object. Do not update verification claims until these runs finish.

- [ ] **Step 5: Run optional browser and Docker gates**

```powershell
uv run flight-hunter-browser-smoke
uv run pytest tests/e2e -q -m browser_e2e --strict-markers
docker compose config
docker compose build
```

If Docker remains unavailable, record that exact external limitation. Browser is required after
successful bootstrap.

- [ ] **Step 6: Run sanitized live Aviasales checks**

```powershell
uv run flight-hunter-source-smoke --source aviasales_search
uv run flight-hunter-source-smoke --source aviasales_search --exact-search --origin MOW --destination LED --departure-offset-days 30
```

Confirm output contains only the approved summary fields. External `blocked`, `rate_limited`, or
`unavailable` results are recorded, not converted to fake success.

- [ ] **Step 7: Update implementation status with fresh evidence**

Record exact test counts, lint/type/security/migration/browser/Compose/image/smoke results and the
current date. Remove stale claims.

- [ ] **Step 8: Commit documentation and status**

```powershell
git add CHANGELOG.md SECURITY.md README.md docs .env.example IMPLEMENTATION_STATUS.md tests/unit/test_env_example.py
git commit -m "docs: publish local v1 release"
```

- [ ] **Step 9: Final repository audit**

```powershell
git status --short
git diff --check
git log -10 --oneline --decorate
```

Expected: clean working tree and coherent local-v1 commits.
