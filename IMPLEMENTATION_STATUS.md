# IMPLEMENTATION_STATUS

> Этот файл ведёт coding agent. Статус `done` ставится только после выполнения exit criteria и записи фактических test results.

## External access

| Provider | Adapter | Credentials | Access approved | Enabled | Background allowed | Merge allowed | Last docs verification |
|---|---|---:|---:|---:|---:|---:|---|
| Fake | implemented | n/a | n/a | yes | yes | yes | n/a |
| Aviasales Data | implemented | env/local | token-based | env flag | policy/cached | yes/cached | 2026-06-29 |
| Aviasales Search | policy skeleton only | no | no | no | no | no | 2026-06-23 |
| Skyscanner Indicative | pending | no | no | no | contract | contract | 2026-06-23 |
| Skyscanner Live | pending | no | no | no | no/user action | contract | 2026-06-23 |
| Duffel | pending | no | no | no | contract | contract | 2026-06-23 |
| SearXNG | implemented URL discovery | self-hosted optional | n/a | env flag | no/user action | no/candidate only | 2026-06-29 |
| Crawl4AI | implemented markdown extraction | self-hosted optional | n/a | env flag | no/user action | no/candidate only | 2026-06-29 |
| Deal discovery | implemented orchestrator | local components | n/a | component flags | no/user action | no/candidate only | 2026-06-29 |
| Telegram Bot API | implemented webhook/outbox transport | env/local bot token | bot token | env flag | delivery worker only | n/a | 2026-06-29 |

## Current slice: Offer risk visibility

- Goal: expose deterministic risk flags for returned offers so cached/live-confirmation/baggage and
  provider price-basis assumptions are visible before richer split/self-transfer generation exists.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing domain/API/UI tests for risk flags on existing offers.
  2. [done] Add a minimal `itinerary_engine` risk assessment layer.
  3. [done] Surface risk level/flags/explanation in API and web result rows without inventing
     split/self-transfer candidates.
  4. [done] Update ADR/README/status and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/itinerary_engine/risk.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0122-offer-risk-visibility.md`
  - `README.md`
  - `docs/ARCHITECTURE.md`
- Tests added/updated:
  - `tests/unit/itinerary_engine/test_risk.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/api/test_cached_radar_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - This is deterministic risk visibility for current offers. It does not generate hidden-city,
    split-ticket or self-transfer itineraries.
- Verification:
  - `uv run pytest tests/unit/itinerary_engine/test_risk.py tests/unit/api/test_api_app.py::test_search_endpoint_returns_demo_cached_result_and_provider_denials tests/unit/api/test_cached_radar_api.py::test_cached_radar_returns_month_matrix_cached_offers tests/unit/api/test_web_ui.py::test_root_serves_beginner_friendly_search_screen_without_secrets -q`
    -> 7 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 504 passed, 11 warnings.
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format .` -> 1 file reformatted, 238 files unchanged.
  - `uv run ruff format --check .` -> 239 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 100 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token result:
    `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng --query flights` -> expected local
    disabled result: `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com` -> expected
    local disabled result: `code=crawl4ai_disabled`.
  - `docker compose config --quiet` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError|fake return|закомментированный недоделанный" src`
    -> no matches.

## Current slice: Application Prometheus metrics

- Goal: expose the non-worker Prometheus metric names required by `MEGA_MONSTER_PLAN.md` from the
  safe observability events already emitted by the application.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing tests for metric recording/rendering and API exposure.
  2. [done] Add a small in-process application metrics recorder behind structured events.
  3. [done] Expose plaintext Prometheus metrics without secrets, URLs or raw payloads.
  4. [done] Update ADR/README/status and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/application_metrics.py`
  - `src/flight_hunter/ops/structured_logging.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0121-application-prometheus-metrics.md`
  - `README.md`
  - `docs/ARCHITECTURE.md`
- Tests added/updated:
  - `tests/unit/ops/test_application_metrics.py`
  - `tests/unit/api/test_metrics_api.py`
  - `tests/unit/ops/test_structured_logging.py`
- Risk:
  - Metrics are process-local operational telemetry and not durable accounting. Labels must remain
    low-cardinality and safe.
- Verification:
  - `uv run pytest tests/unit/ops/test_application_metrics.py tests/unit/api/test_metrics_api.py tests/unit/ops/test_structured_logging.py -q`
    -> 4 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 500 passed, 32 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 236 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 98 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Structured observability logging

- Goal: add safe structured log events required by `MEGA_MONSTER_PLAN.md` for searches,
  Aviasales Data provider calls, browser observations, parser extraction and sent alerts.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing tests for safe structured event fields and redaction boundaries.
  2. [done] Add a small reusable structured logging helper.
  3. [done] Emit `search_started`, `provider_call`, `browser_observation_started`,
     `parser_result` and `alert_sent` without secrets, raw payloads or full URLs.
  4. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/structured_logging.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/application/telegram_notifications.py`
- ADR/docs:
  - `docs/adr/0120-structured-observability-logging.md`
  - `README.md`
  - `docs/ARCHITECTURE.md`
- Tests added/updated:
  - `tests/unit/ops/test_structured_logging.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/application/test_telegram_notifications.py`
- Risk:
  - Log events intentionally use IDs, provider/source names, counts, durations and coarse status
    only. They must not contain tokens, raw provider payloads, callback data, signed URLs or
    message text.
- Verification:
  - `uv run pytest tests/unit/ops/test_structured_logging.py tests/unit/api/test_api_app.py::test_search_endpoint_logs_safe_structured_started_event tests/unit/providers/aviasales_data/test_client.py::test_prices_for_dates_logs_safe_provider_call_event tests/unit/application/test_personal_observations.py::test_personal_observation_job_runs_and_persists_browser_offers tests/unit/providers/personal_observer/test_runner.py::test_runner_observes_fixture_without_live_browser_enabled tests/unit/application/test_telegram_notifications.py::test_linked_price_alert_is_delivered_once tests/unit/application/test_telegram_notifications.py::test_quiet_hours_defer_delivery_without_transport_call -q`
    -> 7 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 497 passed, 2 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 233 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 97 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: URL redaction CLI

- Goal: add `flight-hunter-redact-url` so operators can safely paste signed or tokenized URLs into
  logs, bug reports and sanitized fixtures.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing redaction/CLI/make-target tests.
  2. [done] Implement deterministic URL credential/query/fragment redaction.
  3. [done] Add script and make target.
  4. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/redact_url.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0119-url-redaction-cli.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_redact_url.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This is a local safety tool, not permission to store signed booking URLs or raw provider
    payloads.
- Verification:
  - `uv run pytest tests/unit/ops/test_redact_url.py tests/unit/ops/test_makefile_commands.py -q`
    -> 3 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 494 passed, 2 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 231 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 96 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Backup manifest and restore integrity

- Goal: add an integrity-checked local backup/restore path with manifest verification and an
  explicit restore drill command surface.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing tests for backup manifest, verification and corrupted restore guard.
  2. [done] Write SHA-256/size manifest beside SQLite backups.
  3. [done] Add backup verify CLI and make target.
  4. [done] Make restore reject corrupted backups when a manifest is present.
  5. [done] Update ADR/README/runbook and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/backup.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0118-backup-manifest-restore-integrity.md`
  - `docs/runbooks/backup-restore.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/ops/test_backup_restore.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This improves current SQLite backup integrity. Production PostgreSQL encrypted backup
    automation remains a separate deployment slice.
- Verification:
  - `uv run pytest tests/unit/ops/test_backup_restore.py tests/unit/ops/test_makefile_commands.py -q`
    -> 5 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 492 passed, 2 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 229 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 95 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Account deactivation API

- Goal: add `DELETE /api/v1/account` as a retention-safe account deactivation path that revokes
  access and delivery links without deleting append-only household history.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add failing API/persistence tests for session revocation, membership disable,
     Telegram link revocation, owned watch stop and audit.
  2. [done] Add repository primitives for current-user deactivation.
  3. [done] Add `DELETE /api/v1/account` response model and route.
  4. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0117-account-deactivation-api.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_account_delete_api.py`
  - `tests/unit/persistence/test_identity_repository.py`
  - `tests/unit/persistence/test_telegram_link_repository.py`
  - `tests/unit/api/test_api_app.py`
- Risk:
  - This is deactivation/retention, not hard erasure; append-only audit and price history remain.
- Verification:
  - `uv run pytest tests/unit/api/test_account_delete_api.py tests/unit/persistence/test_identity_repository.py tests/unit/persistence/test_telegram_link_repository.py -q`
    -> 5 passed.
  - `uv run pytest tests/unit/api/test_account_delete_api.py tests/unit/api/test_api_app.py::test_search_endpoint_returns_user_scoped_browser_observed_offers tests/unit/persistence/test_identity_repository.py tests/unit/persistence/test_telegram_link_repository.py -q`
    -> 6 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 491 passed, 2 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 229 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 95 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Privacy export API

- Goal: add a household-scoped privacy export endpoint that returns retained user-visible data
  without provider secrets, raw payload references, idempotency keys or internal queue payloads.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add tests for auth, household scoping, archived/deleted watches and omitted
     internal fields.
  2. [done] Add bounded repository export readers for retained data.
  3. [done] Add `POST /api/v1/privacy/export` with fixed collection limits.
  4. [done] Audit export generation without leaking the export payload.
  5. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0116-privacy-export-api.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_privacy_export_api.py`
  - `tests/unit/persistence/test_household_watch_repository.py`
  - `tests/unit/persistence/test_deal_candidate_repository.py`
  - `tests/unit/persistence/test_manual_price_confirmation_repository.py`
  - `tests/unit/persistence/test_browser_observed_offer_repository.py`
- Risk:
  - This adds export only. Account deletion/erasure remains a separate destructive privacy slice.
- Verification:
  - `uv run pytest tests/unit/api/test_privacy_export_api.py tests/unit/persistence/test_household_watch_repository.py tests/unit/persistence/test_manual_price_confirmation_repository.py tests/unit/persistence/test_deal_candidate_repository.py tests/unit/persistence/test_browser_observed_offer_repository.py -q`
    -> 18 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 487 passed, 31 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 227 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 95 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker supervisor healthcheck CLI

- Goal: add a local supervisor-friendly worker healthcheck that reads durable DB heartbeat/queue
  state without HTTP access, provider calls or secrets.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `flight-hunter-worker-healthcheck` CLI.
  2. [done] Support role-lane checks and configurable heartbeat max age.
  3. [done] Return JSON and non-zero exit for missing, stale, failed or critical-alert workers.
  4. [done] Add `make worker-healthcheck`.
  5. [done] Update ADR/README/runbook and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/worker_healthcheck.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0115-worker-supervisor-healthcheck-cli.md`
  - `docs/runbooks/systemd-worker-supervision.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_worker_healthcheck.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This complements external process supervision; it is not itself a daemon manager.
- Verification:
  - `uv run pytest tests/unit/ops/test_worker_healthcheck.py tests/unit/ops/test_makefile_commands.py tests/unit/ops/test_systemd_units.py --quiet`
    -> 7 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 481 passed, 16 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 226 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 95 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Stale lock monitor in Health panel

- Goal: make stale worker leases visible as a dedicated read-only dashboard signal instead of
  requiring operators to inspect every queue row.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a "Stale lock monitor" section to the web Health panel.
  2. [done] Show only queue lanes with `stale_count > 0`.
  3. [done] Display stale count and oldest locked age from the existing worker health snapshot.
  4. [done] Keep recovery/destructive actions out of the dashboard.
  5. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0114-stale-lock-monitor-health-panel.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - This is a monitoring surface. Actual stale lease recovery still runs through worker passes.
- Verification:
  - `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_admin_worker_health_api.py --quiet`
    -> 8 passed, 1 existing `aiosqlite` warning.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 478 passed, 21 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: PWA shell without API cache

- Goal: make the FastAPI-served web workbench installable as a PWA shell without ever serving
  cached prices, observations or source health API responses as fresh data.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `/manifest.webmanifest`, `/pwa-icon.svg` and `/service-worker.js` endpoints.
  2. [done] Register the service worker from the existing web UI.
  3. [done] Cache only `/`, `/manifest.webmanifest` and `/pwa-icon.svg`.
  4. [done] Let every `/api/` request bypass service-worker caching.
  5. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0113-pwa-shell-without-api-cache.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - This is an installable app shell, not a full offline/Next.js UI. Offline API UX remains an
    honest network failure.
- Verification:
  - `uv run pytest tests/unit/api/test_web_ui.py --quiet` -> 2 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 478 passed, 17 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Admin health and audit paging

- Goal: remove fixed/in-memory admin windows by adding deterministic pagination to source health
  and household audit surfaces.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add newest-first `AuditEventRepository.list_recent(limit, offset)` scoped by household.
  2. [done] Add `limit`/`offset` response metadata to `/api/v1/admin/audit-events`.
  3. [done] Add `sources_limit`, `sources_offset` and `event_limit` to
     `/api/v1/admin/sources/health`.
  4. [done] Keep source status based on the newest event window instead of offset event pages.
  5. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0112-admin-health-audit-paging.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_admin_audit_api.py`
  - `tests/unit/api/test_admin_source_health_api.py`
  - `tests/unit/persistence/test_household_watch_repository.py`
- Risk:
  - Provider health remains unpaged because it is a small static provider readiness catalog.
- Verification:
  - `uv run pytest tests/unit/api/test_admin_audit_api.py tests/unit/api/test_admin_source_health_api.py tests/unit/persistence/test_household_watch_repository.py --quiet`
    -> 10 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 477 passed, 10 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery egress allowlist

- Goal: turn deal-discovery egress metadata into an optional runtime guard so operators can limit
  Crawl4AI page fetches to explicit public hosts.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add optional `DEAL_DISCOVERY_ALLOWED_HOSTS` to settings and `.env.example`.
  2. [done] Extend `DealUrlPolicy` with exact host and `*.subdomain` allowlist matching.
  3. [done] Reject invalid/internal allowlist entries through the same hostname/IP guards.
  4. [done] Wire the allowlist into `DealDiscoveryService` before Crawl4AI markdown fetches.
  5. [done] Expose configured allowlist shape in source contract `egress_policy`.
  6. [done] Update ADR/provider contracts/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/deals/url_policy.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/config.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0111-deal-discovery-egress-allowlist.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `docs/provider-contracts/searxng.md`
  - `.env.example`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_url_policy.py`
  - `tests/unit/deals/test_service.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - This is an application-layer crawler egress guard. Network firewall/container egress controls
    remain operations hardening.
- Verification:
  - `uv run pytest tests/unit/deals/test_url_policy.py tests/unit/deals/test_service.py tests/unit/test_config.py tests/unit/test_env_example.py tests/unit/application/test_source_contracts.py tests/unit/api/test_source_contracts_api.py --quiet`
    -> 45 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 477 passed, 19 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Source contract egress policy metadata

- Goal: make the source contract catalog expose secret-free outbound network boundaries so operators
  can audit provider/component egress before enabling optional sources.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Extend source contract/readiness DTOs with bounded `egress_policy` metadata.
  2. [done] Populate fixed provider hosts, self-hosted component hosts and public-URL policy markers.
  3. [done] Expose `egress_policy` from `GET /api/v1/source-contracts` without path/query/token
     leakage.
  4. [done] Update ADR/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/application/source_contracts.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0110-source-contract-egress-policy.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_source_contracts.py`
  - `tests/unit/api/test_source_contracts_api.py`
- Risk:
  - This is operator-facing contract metadata, not a packet-filter implementation. Network-level
    egress enforcement remains operations work.
- Verification:
  - `uv run pytest tests/unit/application/test_source_contracts.py tests/unit/api/test_source_contracts_api.py --quiet`
    -> 8 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 469 passed, 20 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker health paging

- Goal: make worker health and metrics surfaces production-bounded for larger self-host deployments
  instead of always returning the fixed latest-20 heartbeat window.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `offset` support to `WorkerHeartbeatRepository.list_recent`.
  2. [done] Thread `limit`/`offset` through `WorkerHealthService.snapshot`.
  3. [done] Add `workers_limit` and `workers_offset` query parameters to JSON health and metrics
     endpoints.
  4. [done] Return paging metadata in `AdminWorkerHealthResponse`.
  5. [done] Update ADR/README/runbook and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0109-worker-health-paging.md`
  - `docs/runbooks/systemd-worker-supervision.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_worker_heartbeat_repository.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
- Risk:
  - Queue health remains lane-level aggregate data and is intentionally not paged.
- Verification:
  - `uv run pytest tests/unit/api/test_admin_worker_health_api.py tests/unit/application/test_worker_health.py tests/unit/persistence/test_worker_heartbeat_repository.py --quiet`
    -> 9 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 469 passed, 10 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal URL egress SSRF hardening

- Goal: harden fetched deal/page URLs before SearXNG/Crawl4AI-derived page fetches, closing legacy
  IP alias SSRF shapes without changing internal compose service URLs.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Normalize candidate hostnames through IDNA and reject IPv6 zone ids.
  2. [done] Reject legacy IPv4 aliases: integer, hex, octal and shortened dotted forms.
  3. [done] Preserve canonical public IPv4 and public hostname support for legitimate deal pages.
  4. [done] Keep the guard scoped to fetched deal URLs, not internal SearXNG/Crawl4AI base URLs.
  5. [done] Update ADR/provider contracts/README and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/deals/url_policy.py`
- ADR/docs:
  - `docs/adr/0049-deal-discovery-url-policy.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_url_policy.py`
- Risk:
  - This is URL-shape hardening before fetch. Broader outbound host allowlisting and network-level
    egress controls remain future operations work.
- Verification:
  - `uv run pytest tests/unit/deals/test_url_policy.py tests/unit/deals/test_service.py tests/unit/deals/test_crawl4ai_client.py tests/unit/deals/test_searxng_client.py --quiet`
    -> 35 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 468 passed, 2 warnings
    (existing `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker Prometheus metrics

- Goal: expose production-scrapable worker/queue metrics without log scraping, job-id leakage or
  parsing rich JSON health payloads.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add an application-layer Prometheus text renderer for worker health snapshots.
  2. [done] Expose `GET /api/v1/admin/workers/metrics` as `text/plain; version=0.0.4`.
  3. [done] Include bounded gauges for snapshot time, drain state, worker heartbeat age, queue
     counts/ages and active alerts.
  4. [done] Exclude `current_job_id`, `last_summary`, secrets, raw payloads and user identifiers.
  5. [done] Update README/runbook/ADR and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0108-worker-prometheus-metrics.md`
  - `docs/runbooks/systemd-worker-supervision.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_worker_health.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
- Risk:
  - Metrics are scrape-friendly but intentionally compact. Operators still use
    `/api/v1/admin/workers/health` for interactive diagnosis.
- Verification:
  - `uv run pytest tests/unit/application/test_worker_health.py tests/unit/api/test_admin_worker_health_api.py --quiet`
    -> 6 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 462 passed, 2 warnings
    (existing `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 224 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Telegram callback answer transport

- Goal: deliver Telegram watch callback acknowledgements through Bot API `answerCallbackQuery` while
  preserving durable webhook dedupe, household ownership checks and no-secret callback payloads.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Telegram Bot API callback-answer contract and record it.
  2. [done] Extract `callback_query.id` in the webhook and pass it through the application service.
  3. [done] Store callback acknowledgements as durable `callback_ack` outbox rows without raw
     callback data.
  4. [done] Add `TelegramTransport.answer_callback_query` and Bot API
     `/answerCallbackQuery` delivery.
  5. [done] Keep callback acknowledgements out of quiet-hours deferral and independent of `chat_id`.
  6. [done] Update tests, ADR/docs and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0107-telegram-callback-answer-transport.md`
  - `docs/provider-contracts/telegram-bot-api.md`
  - `docs/adr/0040-telegram-watch-callback-actions.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_telegram_notifications.py`
  - `tests/unit/application/test_telegram_watch_commands.py`
  - `tests/unit/api/test_telegram_api.py`
- Risk:
  - Telegram API calls remain worker-delivered. If the Telegram worker is down long enough,
    `callback_query_id` values may expire before retry; worker health alerts/supervision are the
    operational guard.
- Verification:
  - `uv run pytest tests/unit/application/test_telegram_notifications.py tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py --quiet`
    -> 23 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 460 passed, 9 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 223 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker health alert snapshot

- Goal: expose deterministic worker/queue alert conditions for external supervisors without
  requiring log scraping or custom client-side inference.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `WorkerHealthAlert` and derive alerts from heartbeat/queue snapshot state.
  2. [done] Expose alerts through `GET /api/v1/admin/workers/health`.
  3. [done] Render alerts in the web Health panel.
  4. [done] Add tests for stale worker/queue, backlog and deadline-risk alert codes.
  5. [done] Run targeted and full quality gate, then update final status.
- Files/modules:
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0106-worker-health-alert-snapshot.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_admin_worker_health_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - Alerts are read-only derived state. They do not send notifications, mutate worker queues or
    expose secrets/raw payloads.
- Verification:
  - `uv run pytest tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py --quiet`
    -> 5 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 458 passed, 2 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 223 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Systemd worker supervision templates

- Goal: provide concrete external-supervisor packaging for the existing API and worker lanes without
  embedding secrets or bypassing Flight Hunter policy gates.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add API and worker-lane systemd unit templates.
  2. [done] Add a runbook covering install, lane enablement, drain/restart, health checks and
     rollback.
  3. [done] Add tests for environment-file usage, hardening directives, restart policy and role
     templating.
  4. [done] Run targeted and full quality gate, then update final status.
- Files/modules:
  - `deploy/systemd/flight-hunter-api.service`
  - `deploy/systemd/flight-hunter-worker@.service`
- ADR/docs:
  - `docs/adr/0105-systemd-worker-supervision-templates.md`
  - `docs/runbooks/systemd-worker-supervision.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_systemd_units.py`
- Risk:
  - These are packaging templates only. They do not start services locally, do not store secrets and
    do not change provider policy. Browser observation remains user-action-only.
- Verification:
  - `uv run pytest tests/unit/ops/test_systemd_units.py --quiet` -> 3 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 457 passed, 10 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 223 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery compose server-mode default

- Goal: make the optional SearXNG/Crawl4AI compose profile use the pinned internal Crawl4AI server
  by default instead of accidentally selecting library mode inside API/worker containers.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Default compose API/worker `CRAWL4AI_MODE` to `server` for the deal-discovery stack.
  2. [done] Add `make compose-deals-config` for deployment review without starting containers.
  3. [done] Update `.env.example`, README, Crawl4AI contract and ADR.
  4. [done] Run targeted and full quality gate, then update final status.
- Files/modules:
  - `compose.yaml`
  - `Makefile`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0104-deal-discovery-compose-server-mode-default.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_compose_config.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This changes only the compose container default. Non-compose app settings still default to
    `CRAWL4AI_MODE=library`, and Crawl4AI remains disabled unless explicitly enabled.
- Verification:
  - `uv run pytest tests/unit/ops/test_compose_config.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 2 passed.
  - `docker compose --profile deal-discovery config` -> passed and renders `CRAWL4AI_MODE: server`.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 454 passed, 11 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 222 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal Observer Crawl4AI diagnostic bridge

- Goal: connect optional Crawl4AI markdown extraction to production Personal Browser Observer runs
  without turning markdown into confirmed prices or hidden background crawling.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Reuse the shared Crawl4AI client and URL policy from deal discovery.
  2. [done] Add a sync runner-safe markdown fetch path for the Personal Observer thread boundary.
  3. [done] Inject a final-URL-only diagnostic provider in API, worker and observer CLI runtime.
  4. [done] Keep fixture parsing network-free and classify Crawl4AI failures as sanitized warnings.
  5. [done] Update source contracts and ADR.
  6. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/deals/crawl4ai_client.py`
  - `src/flight_hunter/providers/personal_observer/crawl4ai_diagnostics.py`
  - `src/flight_hunter/providers/personal_observer/cli.py`
  - `src/flight_hunter/providers/personal_observer/worker_cli.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0103-personal-observer-crawl4ai-diagnostic-bridge.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_crawl4ai_client.py`
  - `tests/unit/providers/personal_observer/test_crawl4ai_diagnostics.py`
  - `tests/unit/browser/test_html_offer_extractor.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - Crawl4AI markdown is diagnostic-only. It creates rejected `PriceCandidate` hints after DOM
    parser failure, never `BrowserObservedOffer`, booking links or ranked prices.
- Verification:
  - `uv run pytest tests/unit/deals/test_crawl4ai_client.py tests/unit/providers/personal_observer/test_crawl4ai_diagnostics.py tests/unit/browser/test_html_offer_extractor.py tests/unit/application/test_source_contracts.py --quiet`
    -> 28 passed.
  - `uv run pytest tests/unit/providers/personal_observer/test_cli.py tests/unit/providers/personal_observer/test_worker_cli.py tests/unit/ops/test_worker_command.py --quiet`
    -> 16 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 454 passed, 13 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 222 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 94 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data cached deal seeds

- Goal: let explicitly requested cached-radar Aviasales Data rows enter the existing
  manual-verification deal-candidate lifecycle without treating them as live prices or booking
  links.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Map cached Aviasales Data offers to low-confidence `DealCandidate` seeds.
  3. [done] Persist seeds only for authenticated cached-radar requests with explicit `search_id`.
  4. [done] Use deterministic scoped IDs so repeated saves do not duplicate candidates.
  5. [done] Update provider/source contracts and ADR.
  6. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/deals/aviasales_data_seeds.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0102-aviasales-data-cached-deal-seeds.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_aviasales_data_seeds.py`
  - `tests/unit/api/test_cached_radar_api.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - Cached deal seeds are visible as candidate-only, manual-verification hints. They are not
    `FlightOffer`s, not live availability, and provider signed fields are not exposed.
- Verification:
  - `uv run pytest tests/unit/deals/test_aviasales_data_seeds.py tests/unit/api/test_cached_radar_api.py tests/unit/application/test_source_contracts.py --quiet`
    -> 20 passed.
  - `uv run pytest tests/unit --quiet --disable-warnings` -> 450 passed, 6 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 220 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 93 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal Observer Playwright unavailable retry

- Goal: treat a missing/unavailable local Playwright runtime as retryable source unavailability,
  not as a terminal runner failure.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add adapter coverage for `PLAYWRIGHT_UNAVAILABLE`.
  2. [done] Map `PLAYWRIGHT_UNAVAILABLE` to `ObservationStatus.SOURCE_UNAVAILABLE`.
  3. [done] Cover worker retry/source-health behavior without live browser work.
  4. [done] Document the runtime-unavailable retry policy.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/providers/personal_observer/adapter.py`
- ADR/docs:
  - `docs/adr/0101-personal-observer-playwright-unavailable-retry.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_runner_adapter.py`
  - `tests/unit/ops/test_worker_command.py`
- Risk:
  - Only local runtime unavailability is newly retryable. Policy, parser, challenge and user-action
    failures remain non-retryable terminal classifications.
- Verification:
  - `uv run pytest tests/unit/providers/personal_observer/test_runner_adapter.py tests/unit/ops/test_worker_command.py -k "playwright" --quiet`
    -> 2 passed, 10 deselected.
  - `uv run pytest tests/unit/providers/personal_observer/test_runner_adapter.py tests/unit/ops/test_worker_command.py --quiet`
    -> 12 passed.
  - `uv run pytest tests/unit --quiet` -> 448 passed, 10 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 218 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observation claimed expiry guard

- Goal: prevent already-claimed browser observation jobs from launching or persisting offers after
  their short execution deadline has passed.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check claimed jobs before invoking the browser runner.
  2. [done] Re-check claimed jobs after runner return and before persisting offers.
  3. [done] Align stale active job recovery to `expired`/`expired` after deadline.
  4. [done] Document the expiry invariant.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/persistence/repositories.py`
- ADR/docs:
  - `docs/adr/0100-personal-observation-claimed-expiry-guard.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
- Risk:
  - A claimed job can now expire even after the runner produced offers; those offers are discarded
    because the observation deadline is the freshness boundary.
- Verification:
  - `uv run pytest tests/unit/application/test_personal_observations.py -k "expired" --quiet`
    -> 2 passed, 8 deselected.
  - `uv run pytest tests/unit/application/test_personal_observations.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/ops/test_worker_command.py --quiet`
    -> 32 passed.
  - `uv run pytest tests/unit --quiet` -> 446 passed, 3 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 217 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery partial page success

- Goal: preserve useful deal candidates when one Crawl4AI page fetch fails inside the same manual
  discovery request, while still failing/retrying when every page fetch fails.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Skip individual `Crawl4AiClientError` page failures while continuing URL candidates.
  2. [done] Re-raise the first Crawl4AI error if no candidates were extracted.
  3. [done] Keep URL-policy errors fail-closed before markdown fetch.
  4. [done] Document the partial-success invariant.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/deals/service.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0099-deal-discovery-partial-page-success.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_service.py`
  - `tests/unit/application/test_deal_discovery_jobs.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - A discovery job can now succeed with fewer candidates than attempted URLs when some pages fail.
    Complete crawler failure still follows existing retry/failure classification.
- Verification:
  - `uv run pytest tests/unit/deals/test_service.py tests/unit/application/test_deal_discovery_jobs.py --quiet`
    -> 10 passed.
  - `uv run ruff check src/flight_hunter/deals/service.py tests/unit/deals/test_service.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/deals/service.py`
    -> Success: no issues found in 1 source file.
  - `uv run pytest tests/unit/deals/test_service.py tests/unit/application/test_deal_discovery_jobs.py tests/unit/application/test_source_contracts.py --quiet`
    -> 17 passed.
  - `uv run pytest tests/unit --quiet` -> 443 passed, 12 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 217 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: SearXNG typed transport errors

- Goal: ensure SearXNG deal discovery failures are stable, sanitized error codes for source health
  and worker classification instead of raw transport/JSON exceptions.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Wrap timeout and transport failures in typed `SearxngClientError` codes.
  2. [done] Split HTTP 429 into `searxng_rate_limited`.
  3. [done] Wrap invalid JSON as `searxng_invalid_json` without echoing payload text.
  4. [done] Update SearXNG contract docs and ADR.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/deals/searxng_client.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0098-searxng-typed-transport-errors.md`
  - `docs/provider-contracts/searxng.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_searxng_client.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - Existing callers that matched `searxng_http_429` now see the more specific
    `searxng_rate_limited`. Other 4xx/5xx codes keep the `searxng_http_<status>` form.
- Verification:
  - `uv run pytest tests/unit/deals/test_searxng_client.py tests/unit/deals/test_service.py tests/unit/application/test_deal_discovery_jobs.py tests/unit/application/test_source_contracts.py --quiet`
    -> 20 passed.
  - `uv run ruff check src/flight_hunter/deals/searxng_client.py src/flight_hunter/application/source_contracts.py tests/unit/deals/test_searxng_client.py tests/unit/application/test_source_contracts.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/deals/searxng_client.py src/flight_hunter/application/source_contracts.py`
    -> Success: no issues found in 2 source files.
  - `uv run pytest tests/unit --quiet` -> 441 passed, 9 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 217 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observation expired direct-run guard

- Goal: prevent direct personal-observation execution paths from running browser work after the
  durable job `expires_at` window has elapsed.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a terminal `expired` observation error code.
  2. [done] Fail closed in `PersonalObservationService.run_job()` before `mark_running`.
  3. [done] Keep the runner uncalled and offer persistence empty for expired direct jobs.
  4. [done] Cover the service and CLI direct-run paths with tests.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/domain/observation.py`
  - `src/flight_hunter/application/personal_observations.py`
- ADR/docs:
  - `docs/adr/0097-personal-observation-expired-direct-run-guard.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/providers/personal_observer/test_worker_cli.py`
- Risk:
  - Existing queued jobs that are already expired now end as `expired` instead of being allowed
    through the direct runner. The normal worker claim path already skipped them.
- Verification:
  - `uv run pytest tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_worker_cli.py --quiet`
    -> 11 passed.
  - `uv run ruff check src/flight_hunter/domain/observation.py src/flight_hunter/application/personal_observations.py tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_worker_cli.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/domain/observation.py src/flight_hunter/application/personal_observations.py src/flight_hunter/providers/personal_observer/worker_cli.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 439 passed, 21 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 217 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data price-basis guard

- Goal: stop inferring multi-passenger totals from cached Aviasales Data prices and expose an
  explicit `price_basis` without adding live Search API behavior, booking-link preload or scraping.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a domain `PriceBasis` enum and preserve the existing total-price default.
  2. [done] Map Aviasales Data rows as `provider_single_adult_ticket` without multiplying prices.
  3. [done] Reject Aviasales Data `passengers != 1`, child and infant mixes before provider lookup.
  4. [done] Expose `price_basis` in priced-offer API responses and the web result labels.
  5. [done] Run the full quality gate and update final status.
- Files/modules:
  - `src/flight_hunter/domain/offers.py`
  - `src/flight_hunter/providers/aviasales_data/mapper.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0096-aviasales-data-price-basis-guard.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/domain/test_offers.py`
  - `tests/unit/providers/aviasales_data/test_mapper.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/api/test_cached_radar_api.py`
  - `tests/unit/api/test_date_matrix_api.py`
- Risk:
  - Multi-passenger Aviasales Data cached pricing now fails closed until a documented provider
    total-price/passenger-count contract is added. Demo and external click-out flows remain
    available for multi-passenger searches.
- Verification:
  - `uv run pytest tests/unit/application/test_source_contracts.py tests/unit/domain/test_offers.py tests/unit/providers/aviasales_data/test_mapper.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/api/test_cached_radar_api.py tests/unit/api/test_date_matrix_api.py tests/unit/api/test_api_app.py --quiet`
    -> 78 passed, 1 warning.
  - `uv run ruff format --check` on touched Python files -> 14 files already formatted.
  - `uv run ruff check` on touched Python files -> All checks passed.
  - `uv run mypy src/flight_hunter/domain/offers.py src/flight_hunter/providers/aviasales_data/mapper.py src/flight_hunter/providers/aviasales_data/query_planner.py src/flight_hunter/api/app.py src/flight_hunter/application/source_contracts.py`
    -> Success: no issues found in 5 source files.
  - `uv run pytest tests/unit --quiet` -> 437 passed, 8 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 217 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data contract hardening

- Goal: harden cached Aviasales Data parsing and provider-contract inventory without adding live
  Search API behavior, legacy endpoint calls or booking-link preload.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add shared parser for integer major-unit prices and integer-valued float examples.
  2. [done] Normalize empty optional return-date fields to `None`.
  3. [done] Add negative test for fractional float prices.
  4. [done] Document implemented/superseded/deprecated endpoint inventory.
  5. [done] Run targeted/full gate and update final status.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `docs/provider-contracts/aviasales-data.md`
- ADR/docs:
  - `docs/adr/0095-aviasales-data-contract-hardening.md`
  - `docs/provider-contracts/aviasales-data.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
- Risk:
  - This slice does not address passenger price-basis modeling or server-side cache/circuit breaker
    beyond existing policy gates; those remain separate Aviasales hardening work.
- Verification:
  - `uv run pytest tests/unit/providers/aviasales_data/test_client.py --quiet`
    -> 26 passed.
  - `uv run ruff check src/flight_hunter/providers/aviasales_data/client.py tests/unit/providers/aviasales_data/test_client.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/providers/aviasales_data/client.py`
    -> Success: no issues found in 1 source file.
  - `uv run pytest tests/unit --quiet` -> 430 passed, 24 warnings
    (existing `lxml` deprecation and `aiosqlite` thread cleanup warnings).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 216 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker queue health dashboard

- Goal: expose read-only backlog, retry, stale-lock and deadline/expiry aggregates for durable
  worker queues without changing claim/retry behavior or making provider calls.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add read-only queue aggregate persistence for browser/watch/deal/Telegram lanes.
  2. [done] Add queue warning levels to `WorkerHealthService`.
  3. [done] Expose queue health through `GET /api/v1/admin/workers/health`.
  4. [done] Render worker queues in the web Health panel.
  5. [done] Update final docs/status with the full quality gate result.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0094-worker-queue-health-dashboard.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_worker_queue_health_repository.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - This is an operator visibility slice only. It does not implement external process
    supervision, push alerts or Prometheus metrics.
- Verification:
  - `uv run pytest tests/unit/persistence/test_worker_queue_health_repository.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py --quiet`
    -> 5 passed.
  - `uv run ruff check src/flight_hunter/persistence/repositories.py src/flight_hunter/application/worker_health.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py tests/unit/persistence/test_worker_queue_health_repository.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/persistence/repositories.py src/flight_hunter/application/worker_health.py src/flight_hunter/api/app.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 428 passed, 2 warnings
    (existing `lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 216 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer explicit Crawl4AI diagnostic input

- Goal: make browser-observer Crawl4AI markdown diagnostics explicit so `CRAWL4AI_ENABLED=true`
  cannot relabel visible DOM text as Crawl4AI markdown or trigger hidden markdown fetches.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Stop `Crawl4AiMarkdownHintExtractor` from falling back to visible DOM text.
  2. [done] Add explicit runner/provider and markdown-fixture input for local diagnostics.
  3. [done] Add `--crawl4ai-markdown-fixture` to personal observer fixture/live CLIs.
  4. [done] Add parser, runner and CLI tests for no-provider, explicit-provider and no-raw-output
     behavior.
  5. [done] Update final docs/status with the full quality gate result.
- Files/modules:
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/parse_fixture_cli.py`
  - `src/flight_hunter/providers/personal_observer/cli.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0093-personal-observer-explicit-crawl4ai-input.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/browser/test_html_offer_extractor.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/providers/personal_observer/test_parse_fixture_cli.py`
  - `tests/unit/application/test_source_contracts.py`
  - `tests/fixtures/crawl4ai/browser_observer_markdown_hint.md`
- Risk:
  - This slice adds explicit local diagnostic input only. It does not implement production Crawl4AI
    network fetches for personal browser observation.
- Verification:
  - `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/providers/personal_observer/test_cli.py --quiet`
    -> 33 passed, 1 warning (`lxml` deprecation warning from Scrapling dependency).
  - Targeted:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/providers/personal_observer/test_cli.py tests/unit/application/test_source_contracts.py --quiet`
    -> 40 passed, 1 warning (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/parse_fixture_cli.py src/flight_hunter/providers/personal_observer/cli.py tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/providers/personal_observer/test_cli.py`
    -> All checks passed.
  - `uv run mypy src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/parse_fixture_cli.py src/flight_hunter/providers/personal_observer/cli.py`
    -> Success: no issues found in 4 source files.
  - `uv run pytest tests/unit --quiet` -> 427 passed, 2 warnings
    (existing `lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> 215 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery evidence guard

- Goal: prevent SearXNG title/content snippets from becoming extracted price, route, date or
  confidence evidence for deal candidates.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Split deal extraction evidence from discovery metadata.
  2. [done] Extract price, route, date/month and confidence only from fetched page markdown.
  3. [done] Stop passing SearXNG titles into markdown page title evidence.
  4. [done] Add adversarial extractor/service tests and source contract invariant coverage.
  5. [done] Update final docs/status with the full quality gate result.
- Files/modules:
  - `src/flight_hunter/deals/extractor.py`
  - `src/flight_hunter/deals/service.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0092-deal-discovery-evidence-guard.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
- Tests added/updated:
  - `tests/unit/deals/test_extractor.py`
  - `tests/unit/deals/test_service.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - This slice intentionally avoids parsing Russian natural-language month names. Numeric
    `YYYY-MM-DD` and `YYYY-MM` evidence are supported; richer text parsing belongs in a later
    extractor enhancement.
- Verification:
  - `uv run pytest tests/unit/deals tests/unit/api/test_api_app.py tests/unit/application/test_deal_discovery_jobs.py --quiet`
    -> 61 passed.
  - Targeted:
    `uv run pytest tests/unit/deals tests/unit/api/test_api_app.py tests/unit/application/test_deal_discovery_jobs.py tests/unit/application/test_source_contracts.py --quiet`
    -> 68 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/deals/extractor.py src/flight_hunter/deals/service.py src/flight_hunter/application/source_contracts.py tests/unit/deals/test_extractor.py tests/unit/deals/test_service.py tests/unit/application/test_source_contracts.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/deals/extractor.py src/flight_hunter/deals/service.py src/flight_hunter/application/source_contracts.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 424 passed, 1 warning
    (existing `lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration -ra` -> 1 passed.
  - `uv run ruff format --check .` -> passed.
  - `uv run ruff check .` -> passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data special offers cached radar

- Goal: add official cached `/aviasales/v3/get_special_offers` support and contract hardening
  without treating special-offer rows as live availability or booking links.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Verify Travelpayouts Data API/rate-limit docs and update provider contract notes.
  2. [done] Add typed client/query planner/adapter support for `get_special_offers`.
  3. [done] Expose `special_offers` only through cached-radar API/web, outside exact-date
     merged search.
  4. [done] Harden source contract operations and nearest-places matrix response parsing.
  5. [done] Update ADR/status/docs and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/adr/0091-aviasales-data-special-offers.md`
  - `docs/provider-contracts/aviasales-data.md`
- Tests planned:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
  - `tests/unit/api/test_cached_radar_api.py`
  - `tests/unit/application/test_source_contracts.py`
- Risk:
  - Special-offer rows are cached/abnormal-price hints. They must remain explicit cached-radar
    output with external confirmation required, and `link`/`signature`/`search_id` must not be
    exposed as ready booking URLs.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/api/test_cached_radar_api.py tests/unit/application/test_source_contracts.py tests/unit/api/test_web_ui.py --quiet`
    -> 66 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/providers/aviasales_data/client.py src/flight_hunter/providers/aviasales_data/query_planner.py src/flight_hunter/providers/aviasales_data/adapter.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py src/flight_hunter/application/source_contracts.py tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/api/test_cached_radar_api.py tests/unit/application/test_source_contracts.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/providers/aviasales_data/client.py src/flight_hunter/providers/aviasales_data/query_planner.py src/flight_hunter/providers/aviasales_data/adapter.py src/flight_hunter/api/app.py src/flight_hunter/application/source_contracts.py`
    -> Success: no issues found in 5 source files.
  - `uv run pytest tests/unit --quiet` -> 419 passed, 2 warnings
    (existing `aiosqlite` thread cleanup warning and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 215 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker drain control plane

- Goal: add a durable operator-controlled drain switch for the local worker so deployments and
  maintenance can pause new claims without deleting queued work or breaking already-running jobs.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add durable worker control persistence and migration.
  2. [done] Expose drain state through worker health.
  3. [done] Add authenticated API update path with audit.
  4. [done] Make `flight-hunter-worker` skip new browser/watch/deal/Telegram claims while
     drained, while allowing maintenance cleanup.
  5. [done] Update ADR/status/docs and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/ops/worker.py`
  - `migrations/versions/0021_worker_drain_control.py`
- ADR/docs:
  - `docs/adr/0090-worker-drain-control-plane.md`
- Tests added/updated:
  - `tests/unit/persistence/test_worker_heartbeat_repository.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - Drain must never create provider calls and must not mark queued jobs failed. It is an
    operational pause for new claims only; external supervisors are still responsible for process
    lifecycle and restarts.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_worker_heartbeat_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/api/test_admin_worker_health_api.py tests/unit/ops/test_worker_command.py tests/unit/api/test_web_ui.py --quiet`
    -> 17 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/persistence/models.py src/flight_hunter/persistence/repositories.py src/flight_hunter/application/worker_health.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py src/flight_hunter/ops/worker.py tests/unit/persistence/test_worker_heartbeat_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/api/test_admin_worker_health_api.py tests/unit/ops/test_worker_command.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/persistence/models.py src/flight_hunter/persistence/repositories.py src/flight_hunter/application/worker_health.py src/flight_hunter/api/app.py src/flight_hunter/ops/worker.py`
    -> Success: no issues found in 5 source files.
  - `uv run pytest tests/unit --quiet` -> 413 passed, 5 warnings
    (existing `aiosqlite` thread cleanup warnings and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 215 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> upgraded through `0021_worker_drain_control`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser Crawl4AI markdown hint hook

- Goal: connect the browser parser pipeline to optional Crawl4AI markdown diagnostics without
  making markdown a source of confirmed prices.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add an injectable markdown provider to `BrowserOfferParserPipeline`.
  2. [done] Make `Crawl4AiMarkdownHintExtractor` scan supplied markdown when present.
  3. [done] Keep markdown-derived prices as rejected/manual-verification hints only.
  4. [done] Add parser tests for markdown-only hints and existing fallback behavior.
  5. [done] Update ADR/status/docs and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/browser/html_extractor.py`
- ADR/docs:
  - `docs/adr/0089-browser-crawl4ai-markdown-hint-hook.md`
- Tests added/updated:
  - `tests/unit/browser/test_html_offer_extractor.py`
- Risk:
  - This slice adds a safe hook only. It does not enable automatic Crawl4AI network fetches from
    browser observation runs; a caller must explicitly provide markdown.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/browser/test_scrapling_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py --quiet`
    -> 27 passed, 1 warning (`lxml` deprecation warning from Scrapling).
  - Targeted lint:
    `uv run ruff check src/flight_hunter/browser/html_extractor.py tests/unit/browser/test_html_offer_extractor.py tests/unit/browser/test_scrapling_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/browser/html_extractor.py`
    -> Success: no issues found in 1 source file.
  - `uv run pytest tests/unit --quiet` -> 409 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 214 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data popular directions cached radar

- Goal: complete the next official cached Aviasales Data endpoint by adding explicit
  `get_popular_directions` support without mixing it into exact-date ranked search.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Verify official Travelpayouts docs and record the contract update.
  2. [done] Add typed query/client parser for `/aviasales/v3/get_popular_directions`.
  3. [done] Add planner/adapter support with cached semantics and passenger-mix fail-closed
     behavior.
  4. [done] Expose `popular_directions` through cached-radar API and web workbench only.
  5. [done] Update ADR/status/docs and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0088-aviasales-data-popular-directions.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
  - `tests/unit/api/test_cached_radar_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - Popular-directions rows can describe origins other than the user's requested origin. They stay
    in explicit cached-radar output only and are labelled cached/confirmation-required.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/api/test_cached_radar_api.py tests/unit/api/test_web_ui.py --quiet`
    -> 53 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/providers/aviasales_data/client.py src/flight_hunter/providers/aviasales_data/query_planner.py src/flight_hunter/providers/aviasales_data/adapter.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/api/test_cached_radar_api.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/providers/aviasales_data/client.py src/flight_hunter/providers/aviasales_data/query_planner.py src/flight_hunter/providers/aviasales_data/adapter.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py`
    -> Success: no issues found in 5 source files.
  - `uv run pytest tests/unit --quiet` -> 408 passed, 11 warnings
    (existing `aiosqlite` thread cleanup warnings and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 214 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer profile lock

- Goal: harden the production Playwright browser runtime by preventing concurrent persistent
  Chromium contexts from opening the same source profile.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add profile-lock timeout/stale settings and `.env.example` entries.
  2. [done] Acquire a source-scoped `.flight_hunter_profile.lock` before Playwright launch.
  3. [done] Remove stale profile locks and release the active lock after context shutdown.
  4. [done] Map lock contention to retryable `SOURCE_UNAVAILABLE` durable job behavior.
  5. [done] Update docs/ADR/status and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/adapter.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0087-personal-observer-profile-lock.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risk:
  - The profile lock is a local filesystem guard. It protects normal self-hosted single-machine
    deployments and separate local worker processes, but it is not a distributed lock for
    multi-host browser workers on unrelated filesystems.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_cli.py tests/unit/application/test_personal_observations.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
    -> 33 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/config.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/config.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 403 passed, 4 warnings
    (existing `aiosqlite` thread cleanup warnings and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 214 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker role lanes and active heartbeats

- Goal: make the durable worker runtime production-operable by splitting browser/watch/deal/
  Telegram/maintenance work into role-scoped lanes while keeping local all-in-one behavior.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add repeatable `--role` and comma-separated `--roles` CLI parsing with conservative
     default all-in-one behavior.
  2. [done] Gate browser, watch, deal, Telegram and maintenance lanes by effective worker roles.
  3. [done] Add active job heartbeat metadata and expose it through admin health/web UI.
  4. [done] Preserve legacy skip flags as aliases for removing lanes.
  5. [done] Update docs/ADR/status and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/api/web.py`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0086-worker-role-lanes-heartbeats.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - Role lanes do not relax provider policy. Browser jobs still require previously queued
    user-action work; watch scans still use scheduler-approved providers only; deal discovery jobs
    still process previously enqueued candidate-only searches.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_worker_command.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py tests/unit/application/test_watch_scans.py tests/unit/application/test_telegram_notifications.py tests/unit/application/test_deal_discovery_jobs.py --quiet`
    -> 24 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/ops/worker.py src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/web.py tests/unit/ops/test_worker_command.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/ops/worker.py src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/web.py`
    -> Success: no issues found in 3 source files.
  - CLI help:
    `uv run flight-hunter-worker --help`
    -> shows repeatable `--role {browser,deal,maintenance,telegram,watch}` and comma-separated
    `--roles`.
  - Focused regression:
    `uv run pytest tests/unit/ops/test_worker_command.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 12 passed.
  - `git diff --check` -> passed.
  - `uv run pytest tests/unit --quiet` -> 401 passed, 2 warnings
    (existing `aiosqlite` thread cleanup warning and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 214 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Durable deal discovery jobs

- Goal: move manual deal discovery toward production worker execution by adding durable job
  persistence, claim/retry lifecycle and worker processing, while keeping candidates
  manual-verification-only.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `deal_discovery_jobs` migration/model/repository with idempotency and leases.
  2. [done] Add application worker flow that runs `DealDiscoveryService`, persists candidates
     and records source health events.
  3. [done] Wire `flight-hunter-worker` to process due deal discovery jobs and report summary.
  4. [done] Add API/job status surface without live work inside GET/admin endpoints.
  5. [done] Update docs/ADR/status and run the full quality gate.
- Files/modules:
  - `migrations/versions/0020_deal_discovery_jobs.py`
  - `src/flight_hunter/application/deal_discovery_jobs.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/config.py`
- ADR/docs:
  - `docs/adr/0085-durable-deal-discovery-jobs.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
  - `.env.example`
- Tests added/updated:
  - `tests/unit/application/test_deal_discovery_jobs.py`
  - `tests/unit/persistence/test_deal_discovery_job_repository.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risk:
  - SearXNG/Crawl4AI remain optional and disabled by default. Durable deal jobs only run after an
    authenticated user action enqueues them; results remain `DealCandidate` hints and never priced
    offers.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_api_app.py::test_deal_discovery_job_endpoint_requires_auth_context tests/unit/api/test_api_app.py::test_deal_discovery_job_endpoint_is_disabled_without_crawler_settings tests/unit/api/test_api_app.py::test_deal_discovery_job_api_enqueues_idempotently_and_scopes_status tests/unit/ops/test_worker_command.py::test_worker_processes_queued_deal_discovery_job tests/unit/application/test_deal_discovery_jobs.py --quiet`
    -> 8 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/api/app.py src/flight_hunter/application/deal_discovery_jobs.py src/flight_hunter/ops/worker.py src/flight_hunter/persistence/repositories.py src/flight_hunter/config.py tests/unit/api/test_api_app.py tests/unit/ops/test_worker_command.py tests/unit/application/test_deal_discovery_jobs.py tests/unit/persistence/test_deal_discovery_job_repository.py tests/unit/test_config.py tests/unit/test_env_example.py`
    -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 400 passed, 2 warnings
    (existing `aiosqlite` thread cleanup warning and `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 214 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 92 source files.
  - `uv run alembic upgrade head` -> SQLite head verified, including
    `0020_deal_discovery_jobs`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Cached radar web coverage

- Goal: expose all public cached-radar API modes already implemented for Aviasales Data in the
  FastAPI-served web workbench, especially `grouped_prices` and `latest_prices`, without changing
  cached/not-live semantics.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add grouped/latest cached radar modes to the web cached-radar runner.
  2. [done] Add visible mode labels so users can distinguish cached endpoints.
  3. [done] Update tests/docs/status.
  4. [done] Run targeted tests and the full quality gate.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0084-cached-radar-web-coverage.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - Pressing Cached radar may make more Aviasales Data calls when credentials are configured, but
    the action remains explicit, user-triggered and cached-only.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_cached_radar_api.py --quiet`
    -> 9 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run pytest tests/unit --quiet` -> 388 passed, 20 warnings
    (existing `aiosqlite` thread cleanup warnings and one `lxml` deprecation warning from
    Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 210 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal candidate expiry lifecycle

- Goal: expose deal-candidate expiry as first-class domain/API/UI data and add expired candidate
  cleanup, so deal discovery hints have an explicit lifecycle before the durable job queue slice.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `expires_at` to `DealCandidate` and API responses.
  2. [done] Persist/read candidate expiry into domain objects and list it in search/discovery.
  3. [done] Add repository cleanup for expired deal candidates and wire it into the worker pass.
  4. [done] Render candidate expiry/freshness in the web workbench.
  5. [done] Update README/ADR/status and run the full quality gate.
- Files/modules:
  - `src/flight_hunter/domain/search_results.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/ops/worker.py`
- ADR/docs:
  - `docs/adr/0083-deal-candidate-expiry-lifecycle.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_deal_candidate_repository.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/api/test_web_ui.py`
  - `tests/unit/ops/test_worker_command.py`
- Risk:
  - This keeps deal discovery synchronous for now; durable asynchronous deal-discovery jobs remain
    the next production-readiness slice.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/domain/test_search_results.py tests/unit/persistence/test_deal_candidate_repository.py tests/unit/api/test_api_app.py tests/unit/api/test_web_ui.py tests/unit/ops/test_worker_command.py --quiet`
    -> 36 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/domain/search_results.py src/flight_hunter/persistence/repositories.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py src/flight_hunter/ops/worker.py tests/unit/persistence/test_deal_candidate_repository.py tests/unit/api/test_api_app.py tests/unit/api/test_web_ui.py tests/unit/ops/test_worker_command.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run pytest tests/unit --quiet` -> 388 passed, 8 warnings
    (existing `aiosqlite` thread cleanup warnings and one `lxml` deprecation warning from
    Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 210 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser runtime diagnostic manifest

- Goal: add safe, operator-readable runtime artifact manifests for personal browser observations,
  so production debugging can inspect capture hashes and artifact paths without storing raw cookies,
  query strings or DOM payloads in logs/DB.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a runner-level JSON manifest writer gated by diagnostic artifact settings.
  2. [done] Redact final URLs in manifests while keeping source, timestamps and hashes.
  3. [done] Cover sanitized DOM/screenshot/manifest behavior in runner tests.
  4. [done] Update README/provider contract/ADR/status.
  5. [done] Run targeted tests and the full quality gate.
- Files/modules:
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0082-browser-runtime-diagnostic-manifest.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risk:
  - Manifest paths are local diagnostic file paths only. Raw HTML is never written to the manifest;
    title text is hashed and final URLs are stripped of query/fragment.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
    -> 20 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/config.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run pytest tests/unit --quiet` -> 387 passed, 1 warning
    (`lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 210 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery query strategy and source contracts

- Goal: make manual deal discovery less brittle while keeping every output a candidate-only,
  manual-verification hint, and expose SearXNG/Crawl4AI/deal-discovery readiness in admin source
  health without live GET checks.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add bounded multi-query route/month strategy for SearXNG deal URL discovery.
  2. [done] Make deal discovery iterate bounded queries, dedupe canonical URLs across them and
     stop at the requested candidate limit.
  3. [done] Add source contract defaults for non-provider sources and register SearXNG,
     Crawl4AI and `deal_discovery`.
  4. [done] Extend admin source health response with policy/readiness fields.
  5. [done] Update README/provider contracts/ADR/status.
  6. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/deals/query_builder.py`
  - `src/flight_hunter/deals/service.py`
  - `src/flight_hunter/application/source_contracts.py`
  - `src/flight_hunter/application/source_health.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0081-deal-discovery-query-strategy-contracts.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_query_builder.py`
  - `tests/unit/deals/test_service.py`
  - `tests/unit/application/test_source_contracts.py`
  - `tests/unit/api/test_admin_source_health_api.py`
- Risk:
  - Deal discovery still depends on optional self-hosted SearXNG/Crawl4AI. Disabled-by-default
    readiness is deliberate; no admin GET endpoint performs search/crawl work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/deals tests/unit/application/test_source_contracts.py tests/unit/api/test_admin_source_health_api.py --quiet`
    -> 35 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/deals/query_builder.py src/flight_hunter/deals/service.py src/flight_hunter/application/source_contracts.py src/flight_hunter/application/source_health.py src/flight_hunter/api/app.py tests/unit/deals/test_query_builder.py tests/unit/deals/test_service.py tests/unit/application/test_source_contracts.py tests/unit/api/test_admin_source_health_api.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run pytest tests/unit --quiet` -> 386 passed, 8 warnings
    (existing `aiosqlite` thread cleanup warnings and one `lxml` deprecation warning from
    Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 210 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run alembic upgrade head` -> SQLite head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker heartbeat health surface

- Goal: add durable worker liveness/phase visibility for the production browser/watch/Telegram
  worker without admin GET requests triggering provider or browser work.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `worker_heartbeats` persistence and migration.
  2. [done] Add heartbeat repository and read-model service with stale effective status.
  3. [done] Make `flight-hunter-worker` upsert start/end pass heartbeats without changing stdout.
  4. [done] Add admin worker health API and web Health panel rendering.
  5. [done] Update README/ADR/status.
  6. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/worker_health.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `migrations/versions/0019_worker_heartbeats.py`
- ADR/docs:
  - `docs/adr/0080-worker-heartbeats.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_worker_heartbeat_repository.py`
  - `tests/unit/api/test_admin_worker_health_api.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/api/test_web_ui.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risk:
  - Heartbeats are operational metadata only; admin health reads do not perform live browser,
    crawler or provider checks.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_worker_command.py tests/unit/persistence/test_worker_heartbeat_repository.py tests/unit/api/test_admin_worker_health_api.py tests/unit/api/test_web_ui.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 11 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/application/worker_health.py src/flight_hunter/persistence/models.py src/flight_hunter/persistence/repositories.py src/flight_hunter/ops/worker.py src/flight_hunter/api/app.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/persistence/test_worker_heartbeat_repository.py tests/unit/api/test_admin_worker_health_api.py tests/unit/ops/test_worker_command.py tests/unit/api/test_web_ui.py migrations/versions/0019_worker_heartbeats.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run pytest tests/unit --quiet` -> 382 passed, 1 warning
    (`lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 210 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 91 source files.
  - `uv run alembic upgrade head` -> migration `0019_worker_heartbeats` applied on SQLite head.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer checkpoint controls

- Goal: replace implicit fixed visible-browser checkpoint sleeps with durable operator resume/abort
  controls while keeping browser observation user-action-only.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add durable operator control timestamps to `browser_observation_jobs`.
  2. [done] Add scoped service/API controls for waiting jobs only.
  3. [done] Make the Playwright runner poll durable checkpoint decisions and close contexts on abort.
  4. [done] Surface refresh/resume/abort controls in the FastAPI-served web UI.
  5. [done] Update docs/ADR/provider contract.
  6. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/domain/observation.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/adapter.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `migrations/versions/0018_browser_observation_operator_controls.py`
- ADR/docs:
  - `docs/adr/0079-personal-observer-checkpoint-controls.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risk:
  - Resume/abort are durable operator signals only; they do not authorize background browser runs
    and do not make browser-observed prices live or guaranteed.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/api/test_api_app.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 54 passed, 2 warnings (existing `aiosqlite` thread cleanup warnings).
  - Targeted lint:
    `uv run ruff check src/flight_hunter/domain/observation.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py src/flight_hunter/persistence/models.py src/flight_hunter/persistence/repositories.py src/flight_hunter/api/app.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/api/test_api_app.py migrations/versions/0018_browser_observation_operator_controls.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run pytest tests/unit --quiet` -> 380 passed, 25 warnings
    (existing `aiosqlite` thread cleanup warnings and one `lxml` deprecation warning from
    Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 206 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run alembic upgrade head` -> migration
    `0018_browser_observation_operator_controls` applied on SQLite head.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales grouped/latest cached radar API

- Goal: expose already-implemented Aviasales Data `grouped_prices` and `get_latest_prices`
  endpoints through the public cached-radar API without mixing them into exact-date ranking.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `grouped_prices` and `latest_prices` to cached-radar request validation.
  2. [done] Dispatch those modes to the policy-gated Aviasales Data adapter.
  3. [done] Add cached-specific ranking reasons and API coverage.
  4. [done] Update provider contract/docs/ADR.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0078-aviasales-data-grouped-latest-radar-api.md`
  - `docs/adr/0068-aviasales-data-cached-radar-api.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_cached_radar_api.py`
- Risk:
  - These endpoints remain cached hints only; they are not live availability and do not create
    booking links.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_cached_radar_api.py --quiet` -> 8 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run pytest tests/unit --quiet` -> 374 passed, 11 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 205 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer runtime statuses

- Goal: expose durable operator-visible browser observation phases without allowing background
  browser discovery or leaking DOM/browser state.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add non-terminal runtime phases to `ObservationStatus`.
  2. [done] Persist runtime phases on `browser_observation_jobs` using existing status/lease fields.
  3. [done] Make runtime phases count for claim concurrency and stale recovery.
  4. [done] Emit runner progress callbacks and run sync Playwright work off the event loop.
  5. [done] Expose attempts, waiting/retry timestamps and operator instruction in the API response.
  6. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/domain/observation.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/adapter.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/providers/personal_observer/worker_cli.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0077-personal-observer-runtime-statuses.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/api/test_api_app.py`
- Risk:
  - Runtime phase updates are operational status only; they do not make browser-observed prices
    live, guaranteed or background-refreshable.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_runner.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/api/test_api_app.py tests/unit/ops/test_worker_command.py --quiet`
    -> 54 passed, 2 warnings.
  - `uv run ruff check src/flight_hunter/domain/observation.py src/flight_hunter/persistence/repositories.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py src/flight_hunter/ops/worker.py src/flight_hunter/providers/personal_observer/worker_cli.py src/flight_hunter/api/app.py tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_runner.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/api/test_api_app.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run pytest tests/unit --quiet` -> 372 passed, 3 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 205 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Sanitized browser DOM artifacts

- Goal: make Personal Browser Observer diagnostic DOM artifacts and fixture preparation sanitized by
  default, closing the monster-plan requirement for `flight-hunter-sanitize-html`.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a reusable browser DOM fixture sanitizer.
  2. [done] Make runtime `PERSONAL_OBSERVER_SAVE_DOM_FIXTURES=true` write sanitized HTML only.
  3. [done] Add `flight-hunter-sanitize-html` and `make sanitize-html`.
  4. [done] Cover sanitizer, runner artifacts, CLI output and command surface with unit tests.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/ops/sanitize_html.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0076-sanitized-browser-dom-artifacts.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/browser/test_html_sanitizer.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/ops/test_sanitize_html.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - Sanitization is a best-effort privacy guard for local diagnostics; it is not permission to
    commit full copyrighted pages or browser profile state.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/browser/test_html_sanitizer.py tests/unit/providers/personal_observer/test_runner.py tests/unit/ops/test_sanitize_html.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 14 passed.
  - `uv run ruff format --check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/ops/sanitize_html.py tests/unit/browser/test_html_sanitizer.py tests/unit/providers/personal_observer/test_runner.py tests/unit/ops/test_sanitize_html.py tests/unit/ops/test_makefile_commands.py`
    -> 7 files already formatted.
  - `uv run ruff check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/ops/sanitize_html.py tests/unit/browser/test_html_sanitizer.py tests/unit/providers/personal_observer/test_runner.py tests/unit/ops/test_sanitize_html.py tests/unit/ops/test_makefile_commands.py`
    -> All checks passed.
  - `uv run flight-hunter-sanitize-html --input tests/fixtures/browser/tutu/search_result_source_specific.html --output .pytest-tmp/sanitized-fixture-cli.html`
    -> `ok=true`, `input_bytes=818`, `output_bytes=775`.
  - `uv run pytest tests/unit --quiet` -> 369 passed, 8 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 205 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 90 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Fixture parser CLI

- Goal: add the plan's dedicated sanitized fixture parser command without live browser work or
  persistence.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `flight-hunter-parse-fixture`.
  2. [done] Reuse `PersonalObserverRunner` fixture mode and parser pipeline.
  3. [done] Print sanitized JSON only: offers, warnings and candidate count, not raw HTML/context.
  4. [done] Add `make parse-fixture` and command-surface coverage.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/providers/personal_observer/parse_fixture_cli.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0075-fixture-parser-cli.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_parse_fixture_cli.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This command proves fixture parsing only; it does not prove live navigation or source
    availability.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 2 passed.
  - `uv run ruff format --check src/flight_hunter/providers/personal_observer/parse_fixture_cli.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py`
    -> 3 files already formatted.
  - `uv run ruff check src/flight_hunter/providers/personal_observer/parse_fixture_cli.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 89 source files.
  - `uv run flight-hunter-parse-fixture tests/fixtures/browser/tutu/search_result_source_specific.html --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20`
    -> `confidence=medium`, `provider_offer_id=tutu-realistic-1`, `amount_minor=1842000`.
  - `uv run pytest tests/unit --quiet` -> 366 passed, 8 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 202 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 89 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal browser source catalog

- Goal: make `GET /api/v1/browser-sources` expose the personal observer RU aggregator sources used
  by parser-test and queued observation flows, while keeping them user-action-only and disabled by
  default.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Include `browser_observation_allowed` RU aggregator specs in browser source discovery.
  2. [done] Derive enabled/current-health from `PERSONAL_OBSERVER_ENABLED`,
     `RU_AGGREGATORS_ENABLED` and `PERSONAL_OBSERVER_ALLOWED_HOSTS`.
  3. [done] Keep `background_allowed=false` and `user_action_required=true` for every personal
     source.
  4. [done] Cover default-disabled and enabled-Tutu cases in API tests.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0074-personal-browser-source-catalog.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_live_observations_api.py`
- Risk:
  - The catalog reports local config readiness only; it does not perform live source checks.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_live_observations_api.py tests/unit/api/test_web_ui.py --quiet`
    -> 6 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_live_observations_api.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_live_observations_api.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run pytest tests/unit --quiet` -> 365 passed, 8 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 200 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observation confirm/stale API

- Goal: expose the planned personal-observation confirm and mark-stale endpoints without mutating
  parser/provider facts or duplicating the manual confirmation model.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `POST /api/v1/personal-observations/{job_id}/confirm`.
  2. [done] Add `POST /api/v1/personal-observations/{job_id}/mark-stale`.
  3. [done] Require household/user auth context and verify job ownership.
  4. [done] Append scoped `manual_price_confirmations` rows with
     `target_kind=browser_observation` and `target_id=<job_id>`.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0073-personal-observation-confirm-stale-api.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_api_app.py`
- Risk:
  - Job status remains the worker/parser status; user confirmation/stale state is represented by
    append-only ledger rows.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_api_app.py --quiet` -> 21 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run pytest tests/unit --quiet` -> 364 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 200 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser source parser test API

- Goal: expose the planned parser-test API for sanitized Personal Browser Observer fixtures without
  starting Playwright, navigating live sites, persisting raw HTML or echoing DOM payloads.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `POST /api/v1/browser-sources/{source_id}/test-parser`.
  2. [done] Require household/user auth context.
  3. [done] Validate source observability and `final_url` host/scheme/credentials.
  4. [done] Run `BrowserOfferParserPipeline` and return offers, warnings, snapshot hashes and
     rejected price candidates without raw HTML/context.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0072-browser-source-parser-test-api.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_api_app.py`
- Risk:
  - This endpoint verifies parser contracts only. It does not prove live navigation or source page
    availability.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_api_app.py --quiet` -> 20 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run pytest tests/unit --quiet` -> 363 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 200 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser parser pipeline

- Goal: make Personal Browser Observer extraction production-shaped by chaining source-specific DOM
  parsing, optional Scrapling, generic offer-card parsing and rejected unstructured/Crawl4AI-style
  diagnostics without turning hints into confirmed prices.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `BrowserOfferParserPipeline` and keep low-level parser contracts intact.
  2. [done] Use source-specific Tutu extraction first, then optional Scrapling and generic
     offer-card fallback.
  3. [done] Preserve visible-text and Crawl4AI-style prices only as rejected `PriceCandidate`
     diagnostics.
  4. [done] Map `source_challenge` and `selector_drift` to typed runner/application statuses.
  5. [done] Run the full quality gate and record final results.
- Files/modules:
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/adapter.py`
  - `src/flight_hunter/application/personal_observations.py`
- ADR/docs:
  - `docs/adr/0071-browser-parser-pipeline.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/browser/test_html_offer_extractor.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/application/test_personal_observations.py`
- Risk:
  - Crawl4AI-style diagnostics in the observer are hints only; live source-specific observation
    remains gated by user action, host allowlists and local browser runtime.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py --quiet`
    -> 24 passed.
  - `uv run ruff format --check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py`
    -> 7 files already formatted.
  - `uv run ruff check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run pytest tests/unit --quiet` -> 360 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 200 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser runtime smoke

- Goal: make the local Playwright Chromium dependency verifiable through a supported safe command
  before using the Personal Browser Observer against any user-action source.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Install/verify Chromium with `uv run playwright install chromium`.
  2. [done] Add `flight-hunter-browser-smoke` with a local inline-HTML persistent-context check.
  3. [done] Add `make browser-smoke` and command coverage.
  4. [done] Keep unit tests fake-runtime based so CI does not require browser binaries.
  5. [done] Run the full quality gate and record results.
- Files/modules:
  - `src/flight_hunter/ops/browser_smoke.py`
  - `pyproject.toml`
  - `Makefile`
- ADR/docs:
  - `docs/adr/0070-browser-runtime-smoke.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_browser_smoke.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risk:
  - This smoke verifies local Chromium startup only; it does not run live source-specific travel
    observations.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_browser_smoke.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 4 passed.
  - `uv run ruff format --check src/flight_hunter/ops/browser_smoke.py tests/unit/ops/test_browser_smoke.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/ops/browser_smoke.py tests/unit/ops/test_browser_smoke.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run pytest tests/unit --quiet` -> 354 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 200 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 88 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web cached radar controls

- Goal: make the Aviasales Data cached radar API usable from the main self-hosted web workbench
  without merging those hints into ranked exact-date search results.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add minor-unit price range fields and a `Cached radar` action to the route form.
  2. [done] Call `POST /api/v1/searches/cached-radar` for `price_range`, `month_matrix` and
     `nearest_places_matrix`.
  3. [done] Render cached radar offers and denial codes in a separate result section.
  4. [done] Keep manual confirmation actions available for cached radar offers.
  5. [done] Run the full quality gate and record results.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0069-web-cached-radar-controls.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risk:
  - This is a compact built-in workbench surface, not a dedicated PWA radar workspace.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py --quiet` -> 1 passed.
  - `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - Extracted inline script from `render_index_html()` and parsed it with Node
    `new Function(script)` -> `script syntax ok`.
  - `uv run pytest tests/unit --quiet` -> 351 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 198 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data cached radar API

- Goal: expose broader Aviasales Data cached radar endpoints through an explicit product API for
  price-range, month-level and nearby-place hints without mixing those rows into ranked exact-date
  search.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `POST /api/v1/searches/cached-radar` with explicit `price_range`,
     `month_matrix` and `nearest_places_matrix` modes.
  2. [done] Reuse the existing Aviasales Data adapter methods and keep authorization in
     `ExecutionContext.API_REQUEST`.
  3. [done] Return explicit denial codes for provider exclusion, missing credentials, unsupported
     passenger mix and unavailable/empty provider responses.
  4. [done] Return normal cached `OfferResponse` rows with `observed_at`, freshness and
     live-confirmation caveats, without booking/search links.
  5. [done] Accept price-range bounds as integer minor units and convert to provider major units
     only when no rounding would occur.
  6. [done] Run the full quality gate and record results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0068-aviasales-data-cached-radar-api.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_cached_radar_api.py`
- Risk:
  - Cached radar offers are not persisted as watch history in this slice.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_cached_radar_api.py tests/unit/providers/aviasales_data/test_adapter.py --quiet`
    -> 16 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run pytest tests/unit --quiet` -> 351 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 198 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data date-matrix cached pricing

- Goal: let the existing flexible-date matrix API overlay cached Aviasales Data `week-matrix`
  prices when route fields and credentials are present, while preserving no-provider planning and
  explicit degraded states.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Extend the date-matrix API request/response with optional route, passenger and cached
     price metadata fields.
  2. [done] Call the existing Aviasales Data `week_matrix` adapter only when policy-safe request
     fields and credentials are present.
  3. [done] Return explicit pricing denial codes for missing route, missing credentials, provider
     exclusion, unsupported passenger mix and unavailable/empty provider responses.
  4. [done] Prove cached price overlay uses only mapped provider offers and keeps freshness/live
     confirmation metadata visible.
  5. [done] Run the full quality gate and record results.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0067-aviasales-data-date-matrix-pricing.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_date_matrix_api.py`
- Risks:
  - This only productizes the week-level date matrix overlay; month-matrix and nearby-place matrix
    API surfaces remain separate slices.
  - Cached prices still require external confirmation before purchase and are never booking links.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_date_matrix_api.py tests/unit/providers/aviasales_data/test_adapter.py --quiet`
    -> 14 passed.
  - `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_date_matrix_api.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_date_matrix_api.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run pytest tests/unit --quiet` -> 345 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 197 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: No-credentials acceptance harness

- Goal: add a real integration acceptance test that exercises the local no-credentials demo path
  across auth, search, watches, worker scans, history, Telegram linking/outbox and household
  isolation without live provider or browser calls.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Create `tests/integration` with a file-backed SQLite acceptance scenario.
  2. [done] Drive the scenario through public API endpoints where possible and the real worker
     loop for background processing.
  3. [done] Assert household isolation, price-history persistence and Telegram alert dedupe.
  4. [done] Update docs/status and run integration plus full quality gates.
- Files/modules:
  - `tests/integration/test_no_credentials_acceptance.py`
- ADR/docs:
  - `README.md`
  - `IMPLEMENTATION_STATUS.md`
- Tests added/updated:
  - `tests/integration/test_no_credentials_acceptance.py`
- Risks:
  - This is the first integration acceptance harness; browser/UI E2E, compose-up runtime E2E and
    accessibility/i18n flows remain separate future slices.
  - Telegram alert delivery is intentionally not sent to Telegram in the no-token harness; the test
    verifies link ownership, outbox creation and dedupe.
- Verification:
  - Targeted:
    `uv run pytest tests/integration/test_no_credentials_acceptance.py --quiet`
    -> 1 passed.
  - `uv run ruff check tests/integration/test_no_credentials_acceptance.py` -> All checks passed.
  - `uv run ruff format --check tests/integration/test_no_credentials_acceptance.py`
    -> 1 file already formatted.
  - `uv run pytest tests/unit --quiet` -> 342 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run pytest tests/integration --quiet` -> 1 passed.
  - `uv run ruff format --check .` -> 197 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer runtime controls

- Goal: harden the Playwright Personal Browser Observer runtime with operator-tunable navigation,
  selector and manual checkpoint waits while keeping it disabled by default and fixture-testable
  without live browser calls.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add env-driven runtime controls for navigation timeout, ready selector and
     manual checkpoint wait.
  2. [done] Wire the controls into `PersonalObserverRunner` without adding stealth/proxy/CAPTCHA
     behavior.
  3. [done] Add unit tests for config parsing, fixture safety and Playwright control sequencing.
  4. [done] Update docs/ADR/status and run targeted plus full quality gates.
- Files/modules:
  - `src/flight_hunter/config.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
- ADR/docs:
  - `docs/adr/0066-personal-observer-runtime-controls.md`
  - `README.md`
  - `.env.example`
- Tests added/updated:
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
- Risks:
  - This adds deterministic runtime controls but does not run live E2E against real Tutu/Yandex
    Travel/OneTwoTrip pages.
  - Ready selectors remain operator-supplied; per-source selector contracts beyond the existing
    Tutu fixture path remain future slices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
    -> 14 passed.
  - `uv run ruff format --check src/flight_hunter/config.py src/flight_hunter/providers/personal_observer/runner.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
    -> 5 files already formatted.
  - `uv run ruff check src/flight_hunter/config.py src/flight_hunter/providers/personal_observer/runner.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
    -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 342 passed, 3 warnings
    (two existing `aiosqlite` event-loop-close thread warnings from Telegram API tests and one
    `lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 196 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Household admin audit surface

- Goal: expose existing household-scoped lifecycle audit rows through an authenticated admin API and
  the primary web workbench, without widening household access or logging sensitive fields.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a read-only `GET /api/v1/admin/audit-events` endpoint using the same
     household auth context as watches.
  2. [done] Prove household isolation and auth-required behavior with API tests.
  3. [done] Add a compact web audit panel that refreshes after watch lifecycle actions.
  4. [done] Update docs/ADR and run targeted plus full quality gates.
- Files/modules:
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0065-household-admin-audit-surface.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_admin_audit_api.py`
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - This is a compact read-only workbench surface, not a full RBAC admin console with filtering,
    export or audit retention tooling.
  - Full UUIDs are returned by the authenticated API for traceability; the web panel displays short
    prefixes.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_admin_audit_api.py tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py --quiet`
    -> 10 passed.
  - Extracted inline script from `render_index_html()` and parsed it with Node
    `new Function(script)` -> `script syntax ok`.
  - `uv run pytest tests/unit --quiet` -> 340 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 196 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web admin health surface

- Goal: expose existing provider/source health read models in the primary web UI without running
  live checks or leaking secrets.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a compact admin health panel to the existing workbench.
  2. [done] Load `GET /api/v1/admin/providers/health` and render provider policy/readiness.
  3. [done] Load `GET /api/v1/admin/sources/health` and render source contract/event status.
  4. [done] Keep all display sanitized: booleans and status strings only, no secrets.
  5. [done] Add web smoke assertions and inline script syntax verification.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0064-web-admin-health-surface.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - This is a read-only web surface; historical charts and auth-gated admin roles remain future
    product slices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_admin_provider_health_api.py tests/unit/api/test_admin_source_health_api.py --quiet`
    -> 3 passed.
  - Extracted inline script from `render_index_html()` and parsed it with Node
    `new Function(script)` -> `script syntax ok`.
  - `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 338 passed, 3 warnings
    (two `aiosqlite` event-loop-close thread warnings from an existing async API test harness and
    one `lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 195 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web watch control center

- Goal: expose the durable Watch API from the primary web UI so a household user can create a
  watch from the current route, list watches, pause/resume them, inspect price history and
  archive/delete with optimistic versions.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a compact watch control panel to the existing workbench.
  2. [done] Create watches from the current search form through `POST /api/v1/watches`.
  3. [done] List household watches through `GET /api/v1/watches`.
  4. [done] Add pause/resume buttons using the existing Watch API.
  5. [done] Load `GET /api/v1/watches/{watch_id}/history` into a separate history section.
  6. [done] Archive/delete with `expected_version` so stale UI state is rejected.
  7. [done] Keep session bearer headers as the first auth path and demo headers as fallback.
  8. [done] Add web smoke assertions and inline script syntax verification.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0063-web-watch-control-center.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - This is still the FastAPI-served workbench, not a dedicated PWA watch detail page.
  - The panel displays existing price snapshots; it does not force a scan or call providers.
  - Pause/resume follow the existing API and are not optimistic-versioned; archive/delete use
    `expected_version`.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py --quiet`
    -> 8 passed.
  - Extracted inline script from `render_index_html()` and parsed it with Node
    `new Function(script)` -> `script syntax ok`.
  - `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 338 passed, 13 warnings
    (`aiosqlite` event-loop-close thread warnings from existing async test harnesses and one
    `lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 195 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web invitation session panel

- Goal: make the new invitation/session auth usable from the primary web UI without manual
  localStorage edits and without mixing bearer identity with demo headers.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add a compact session panel to the existing workbench.
  2. [done] Accept invitation code/display name through `POST /api/v1/auth/accept-invitation`.
  3. [done] Store the returned bearer session token in localStorage.
  4. [done] Validate existing sessions with `GET /api/v1/auth/me` on startup.
  5. [done] Keep demo headers as fallback only when no bearer token exists.
  6. [done] Add sign-out behavior that clears the stored token.
  7. [done] Add web smoke assertions and inline script syntax verification.
  8. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0062-web-invitation-session-panel.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - Bootstrap invitation creation remains API/operator-only; this panel accepts invitations but
    does not manage invitation issuance.
  - This is not yet a full account-management screen with session revocation or member admin.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_auth_api.py --quiet`
    -> 8 passed.
  - `node -e "... new Function(script) ..."` -> `script syntax ok`.
  - `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> 2 files already formatted.
  - `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
    -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 338 passed, 3 warnings
    (two `aiosqlite` thread warnings from a deal-discovery API test harness and one `lxml`
    deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 195 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `node -e "... new Function(script) ..."` -> `script syntax ok`.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Invitation session auth foundation

- Goal: replace temporary household/user headers with a production-oriented invitation-only
  session foundation while preserving legacy demo headers behind an explicit compatibility flag.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add identity/session domain helpers for secret token generation and hash-only storage.
  2. [done] Add Alembic-managed households, users, memberships, invitations and sessions tables.
  3. [done] Add `IdentityRepository` methods for invitation acceptance and active session lookup.
  4. [done] Add bootstrap invitation, accept invitation and `/api/v1/auth/me` endpoints.
  5. [done] Accept `Authorization: Bearer ...` for Watch API, manual confirmations, Telegram link
     codes, agent/search enrichment and live/personal observation flows.
  6. [done] Keep legacy `X-Flight-Hunter-*` headers enabled only through
     `AUTH_ALLOW_LEGACY_HEADERS=true`; Bearer session identity wins on conflicts.
  7. [done] Update web fetch helpers to use a stored session token before demo headers.
  8. [done] Add regression tests for auth API, repository, migration, config/env and web helper
     coverage.
  9. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/domain/auth.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `migrations/versions/0017_invitation_auth_foundation.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0061-invitation-session-auth-foundation.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_auth_api.py`
  - `tests/unit/persistence/test_identity_repository.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/api/test_web_ui.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - Legacy header compatibility is still enabled by default for local/demo flows; production
    deployments must set `AUTH_ALLOW_LEGACY_HEADERS=false`.
  - The web page can use an already stored session token but does not yet include a polished
    invitation acceptance/login screen.
  - Session revocation/admin invitation management is not implemented in this slice.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_auth_api.py tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py tests/unit/api/test_api_app.py tests/unit/api/test_live_observations_api.py tests/unit/api/test_telegram_api.py tests/unit/api/test_agent_api.py tests/unit/persistence/test_identity_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
    -> 62 passed, 2 warnings (`aiosqlite` thread warnings from an API test harness).
  - `uv run pytest tests/unit --quiet` -> 338 passed, 2 warnings
    (`aiosqlite` thread warning from a deal-discovery API test harness and `lxml` deprecation
    warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 195 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 87 source files.
  - `uv run alembic upgrade head` -> upgraded local SQLite from
    `0016_manual_price_confirmations` to `0017_invitation_auth_foundation`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery URL dedupe

- Goal: avoid duplicate Crawl4AI markdown fetches and duplicate manual deal candidates when SearXNG
  returns the same page with tracking parameters/fragments.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Canonicalize deal search-result URLs before markdown fetch.
  2. [done] Remove fragment and common tracking params from the dedupe key.
  3. [done] Keep meaningful non-tracking query params distinct.
  4. [done] Continue scanning search results until `limit` unique candidates is reached.
  5. [done] Add service-level regression tests.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/deals/service.py`
- ADR/docs:
  - `docs/adr/0060-deal-discovery-url-dedupe.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_service.py`
- Risks:
  - URL-level dedupe does not yet cluster semantically identical pages on different domains.
  - Deal candidates remain manual-verification hints, not confirmed prices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/deals/test_service.py -q` -> 3 passed.
  - Targeted mypy:
    `uv run mypy src/flight_hunter/deals/service.py` -> Success: no issues found in 1 source file.
  - `uv run pytest tests/unit --quiet` -> 329 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker graceful shutdown

- Goal: let long-running `flight-hunter-worker --loop` drain cleanly between passes on shutdown
  signals without starting new jobs after the signal.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add stop predicate support to `run_loop`.
  2. [done] Install SIGINT/SIGTERM handlers in the CLI loop path.
  3. [done] Interrupt idle sleep through a signal-aware sleep wrapper.
  4. [done] Keep `run_once` durable job behavior unchanged.
  5. [done] Add a regression test for stop-during-idle behavior.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/ops/worker.py`
- ADR/docs:
  - `docs/adr/0059-worker-graceful-shutdown.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_worker_command.py`
- Risks:
  - This is worker-side graceful shutdown, not a full supervisor, autoscaler or drain dashboard.
  - A signal during an active pass lets the pass finish; individual long browser/provider calls
    still rely on their own timeouts.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_worker_command.py -q` -> 7 passed.
  - Targeted mypy:
    `uv run mypy src/flight_hunter/ops/worker.py tests/unit/ops/test_worker_command.py`
    -> Success: no issues found in 2 source files.
  - `uv run pytest tests/unit --quiet` -> 328 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Personal observer runtime artifacts

- Goal: harden the Playwright personal observer runtime without adding stealth/proxy/CAPTCHA
  behavior or background browsing.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Separate persistent browser profile state from optional DOM/screenshot artifacts.
  2. [done] Add `PERSONAL_OBSERVER_ARTIFACT_ROOT` config/env support.
  3. [done] Validate allowed redirect hosts by hostname rather than raw `netloc`.
  4. [done] Close Playwright persistent contexts in navigation failure paths.
  5. [done] Add regression tests for config/env and host-with-port allowlist handling.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0058-personal-observer-runtime-artifacts.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - This is runtime hardening, not live E2E browser validation against external sites.
  - Diagnostic artifact retention/cleanup policy remains a future operations slice.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_cli.py tests/unit/providers/personal_observer/test_worker_cli.py tests/unit/test_config.py tests/unit/test_env_example.py -q`
    -> 15 passed.
  - `uv run pytest tests/unit --quiet` -> 327 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Crawl4AI server-mode client

- Goal: let optional deal discovery use the self-hosted Crawl4AI compose service through a
  documented server API without enabling it by default or leaking markdown/secrets.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `CRAWL4AI_MODE=server` HTTP client support for `POST /md`.
  2. [done] Keep URL policy validation before any Crawl4AI import or HTTP request.
  3. [done] Add optional bearer-token support through `CRAWL4AI_API_TOKEN`.
  4. [done] Wire app and source-smoke factories to mode/base URL/token/timeout settings.
  5. [done] Add unit tests for request shape, auth errors, plain-text response handling and config.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/deals/crawl4ai_client.py`
  - `src/flight_hunter/config.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/ops/source_smoke.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0057-crawl4ai-server-mode-client.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_crawl4ai_client.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - Server mode still depends on a compatible self-hosted Crawl4AI deployment and is not exercised
    against a live container in CI.
  - Hooks, custom JavaScript, auth cookies, proxy behavior and LLM extraction remain intentionally
    unsupported.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/deals/test_crawl4ai_client.py tests/unit/ops/test_source_smoke.py tests/unit/test_config.py tests/unit/test_env_example.py tests/unit/api/test_api_app.py -q`
    -> 33 passed.
  - `uv run pytest tests/unit --quiet` -> 326 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed and includes
    `CRAWL4AI_API_TOKEN` / `CRAWL4AI_TIMEOUT_SECONDS` passthrough for the API container.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web manual confirmation controls

- Goal: make the manual confirmation ledger usable from the result surface without mixing user
  confirmations into provider facts, ranking or alert snapshots.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add manual confirmation actions to cached price rows.
  2. [done] Add manual confirmation actions to external/carrier links.
  3. [done] Add manual confirmation actions to browser observations and deal candidates.
  4. [done] Show recent household/user-scoped manual confirmations in a separate UI section.
  5. [done] Keep all writes behind explicit user clicks and existing local auth headers.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/api/web.py`
- ADR/docs:
  - `docs/adr/0056-web-manual-confirmation-controls.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - The current UI stores demo household/user ids in localStorage; invitation auth remains a future
    product slice.
  - Confirmations are displayed as recent history only; they do not yet annotate each matching row
    with per-target latest status.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_api_app.py -q`
    -> 18 passed.
  - `node -e "... new Function(script) ..."` -> `script syntax ok`.
  - `uv run pytest tests/unit --quiet` -> 323 passed, 5 warnings
    (`aiosqlite` event-loop-close thread warnings in existing async tests and `lxml`
    deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Manual price confirmation ledger

- Goal: let authenticated users record durable manual confirmations for cached offers, external
  links, browser observations, deal candidates and carrier confirmation links without mutating
  provider facts or creating live-price claims.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add domain model and closed status enum for manual confirmations.
  2. [done] Add append-only persistence table, Alembic migration and household/user-scoped
     repository queries.
  3. [done] Add `POST /api/v1/manual-price-confirmations` and
     `GET /api/v1/manual-price-confirmations`.
  4. [done] Validate result kinds, status values, optional Money pair and auth headers.
  5. [done] Add repository, migration and API tests.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/domain/manual_confirmation.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
  - `migrations/versions/0016_manual_price_confirmations.py`
- ADR/docs:
  - `docs/adr/0055-manual-price-confirmation-ledger.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_manual_price_confirmation_repository.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/api/test_api_app.py`
- Risks:
  - Web and Telegram controls that call the new endpoints are still future UI slices.
  - Manual confirmations are product history only; they do not update price snapshots, ranking,
    alerts or booking links yet.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_api_app.py tests/unit/persistence/test_manual_price_confirmation_repository.py tests/unit/persistence/test_alembic_upgrade.py -q`
    -> 19 passed.
  - `uv run pytest tests/unit --quiet` -> 323 passed, 5 warnings
    (`aiosqlite` event-loop-close thread warnings in existing async tests and `lxml`
    deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 191 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 86 source files.
  - `uv run alembic upgrade head` -> upgraded local SQLite head through
    `0016_manual_price_confirmations`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Extended carrier confirmation links

- Goal: broaden secondary official airline confirmation links from Aeroflot/Pobeda/S7 to the
  carrier set listed in the monster plan, without adding scraping, live-price claims or in-app
  booking.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add carrier source specs for Ural Airlines, Nordwind, Red Wings, Smartavia, Azimuth,
     Utair, Rossiya, Turkish Airlines, Air Serbia, Pegasus, Uzbekistan Airways, Emirates, Qatar
     Airways, Etihad and flydubai.
  2. [done] Keep all carrier specs `manual`, `browser_observation_allowed=False` and
     `source_type=carrier`.
  3. [done] Add the same carriers to the public price-source catalog.
  4. [done] Enable the extended carrier set by default through `CARRIER_LINKS_ENABLED`.
  5. [done] Add link-builder/catalog/config/env tests and contract notes/ADR/docs.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/providers/ru_clickout/source_specs.py`
  - `src/flight_hunter/application/price_sources.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0054-extended-carrier-confirmation-links.md`
  - `docs/provider-contracts/carrier-clickouts.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/ru_clickout/test_link_builder.py`
  - `tests/unit/application/test_price_sources.py`
  - `tests/unit/api/test_price_sources_api.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - These are base official URLs only; precise deep links and carrier-specific parsers remain future
    contracts.
  - Carrier links are manual confirmation aids and never become priced offers unless a future
    official integration provides verified data.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/ru_clickout/test_link_builder.py tests/unit/application/test_price_sources.py tests/unit/api/test_price_sources_api.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
    -> 13 passed.
  - `uv run pytest tests/unit --quiet` -> 319 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 188 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 85 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery compose hardening

- Goal: make the optional SearXNG/Crawl4AI local compose profile reproducible and internal-only
  enough for self-hosted experiments without treating deal discovery as price truth.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Verify current Docker image tags from registries on 2026-06-29.
  2. [done] Pin default `SEARXNG_IMAGE` and add `CRAWL4AI_IMAGE`.
  3. [done] Add internal-only SearXNG/Crawl4AI compose services with healthchecks and no default
     host port publication.
  4. [done] Expose `CRAWL4AI_BASE_URL` in config/env while keeping app default `library` mode.
  5. [done] Add compose/env regression tests and update provider contracts/ADR/docs.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `compose.yaml`
  - `.env.example`
  - `src/flight_hunter/config.py`
- ADR/docs:
  - `docs/adr/0053-deal-discovery-compose-hardening.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_compose_config.py`
  - `tests/unit/test_env_example.py`
  - `tests/unit/test_config.py`
- Risks:
  - This is still a local compose profile, not a final production deployment with egress policy,
    resource limits, monitoring or backup/runbook coverage.
  - Crawl4AI server mode is represented operationally, but Flight Hunter still uses library mode by
    default until a stable server-client contract is implemented.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_compose_config.py tests/unit/test_env_example.py tests/unit/test_config.py --quiet`
    -> 5 passed.
  - `docker compose --profile deal-discovery config` -> passed; config includes pinned
    `searxng/searxng:2026.6.29-0e990f78a`, pinned `unclecode/crawl4ai:0.8.9`, internal `expose`
    entries and healthchecks.
  - `uv run pytest tests/unit --quiet` -> 318 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 188 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 85 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Telegram watch manual browser check callback

- Goal: let linked Telegram users queue a personal browser observation from a real watch callback
  without running browser automation in the webhook or bypassing user-action grants.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `/watches` Check inline callback data alongside Pause/Resume.
  2. [done] Resolve linked Telegram account and household-scoped watch before any grant/job write.
  3. [done] Issue `telegram_callback` personal observation grants and create durable
     `browser_observation_jobs` rows with idempotency keys.
  4. [done] Keep webhook behavior side-effect-light: outbox acknowledgement only, no browser runner.
  5. [done] Add owner/version/idempotency tests for application and API webhook paths.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0052-telegram-watch-manual-observation-callback.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_telegram_watch_commands.py`
  - `tests/unit/api/test_telegram_api.py`
  - `tests/unit/test_config.py`
- Risks:
  - The callback queues personal observer jobs only; users still need a running
    `flight-hunter-worker` personal-observation worker to collect browser-observed offers.
  - Superseded by the Telegram callback answer transport slice: callback acknowledgements now use
    durable `callback_ack` outbox rows delivered through Bot API `answerCallbackQuery`.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py tests/unit/test_config.py --quiet`
    -> 18 passed.
  - `uv run pytest tests/unit --quiet` -> 317 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 187 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 85 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery health events

- Goal: make manual deal discovery failures/successes visible through persisted source health and
  stable API error codes.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Record best-effort `source_health_events` for deal discovery success and known failure
     paths.
  2. [done] Return stable API code `deal_discovery_url_rejected` for URL policy failures.
  3. [done] Return stable API code `deal_discovery_source_failed` for SearXNG/Crawl4AI client
     failures.
  4. [done] Add regression tests for success/failure event recording.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0051-deal-discovery-health-events.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/api/test_admin_source_health_api.py`
  - `tests/unit/deals`
- Risks:
  - Health event recording is best-effort; persistent DB outages are not hidden from dedicated DB
    operations, but manual discovery responses do not fail solely because health recording failed.
  - Deal discovery still runs synchronously when explicitly enabled; queued deal jobs remain future
    work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_api_app.py tests/unit/api/test_admin_source_health_api.py tests/unit/deals -q`
    -> 36 passed.
  - Targeted lint/type:
    `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
    -> All checks passed.
    `uv run mypy src/flight_hunter/api/app.py`
    -> Success: no issues found in 1 source file.
  - `uv run pytest tests/unit --quiet` -> 314 passed, 8 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run ruff format --check .` -> 187 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 85 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Admin source health read model

- Goal: expose source readiness plus recent persisted source health events without running live
  checks or leaking secrets from an admin GET endpoint.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `SourceHealthService` application read model over source contracts and
     `source_health_events`.
  2. [done] Include event-only source ids such as browser observer sources.
  3. [done] Add `GET /api/v1/admin/sources/health`.
  4. [done] Add API regression coverage for secrets redaction and event-only source visibility.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/application/source_health.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0050-admin-source-health-read-model.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_admin_source_health_api.py`
  - `tests/unit/persistence/test_source_health_event_repository.py`
- Risks:
  - This is an API/read model only; richer web dashboard and health charts remain future work.
  - GET does not execute source smoke checks by design; operators still run CLI smoke explicitly.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_admin_source_health_api.py tests/unit/persistence/test_source_health_event_repository.py -q`
    -> 2 passed.
  - Targeted lint/type:
    `uv run ruff check src/flight_hunter/application/source_health.py src/flight_hunter/api/app.py tests/unit/api/test_admin_source_health_api.py`
    -> All checks passed.
    `uv run mypy src/flight_hunter/application/source_health.py src/flight_hunter/api/app.py`
    -> Success: no issues found in 2 source files.
  - `uv run pytest tests/unit --quiet` -> 312 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 187 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 85 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Deal discovery URL policy hardening

- Goal: prevent SearXNG/Crawl4AI deal discovery from fetching obvious localhost/private/internal
  targets while keeping deal candidates as manual-verification hints.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `DealUrlPolicy` for public http(s) deal-page URLs.
  2. [done] Apply policy while parsing SearXNG result URLs.
  3. [done] Apply policy in `DealDiscoveryService` before markdown fetch and in
     `Crawl4AiMarkdownClient` before disabled/import/runtime checks.
  4. [done] Add markdown size cap for Crawl4AI snapshots.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/deals/url_policy.py`
  - `src/flight_hunter/deals/searxng_client.py`
  - `src/flight_hunter/deals/crawl4ai_client.py`
  - `src/flight_hunter/deals/service.py`
- ADR/docs:
  - `docs/adr/0049-deal-discovery-url-policy.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/deals/test_url_policy.py`
  - `tests/unit/deals/test_searxng_client.py`
  - `tests/unit/deals/test_crawl4ai_client.py`
  - `tests/unit/deals/test_service.py`
- Risks:
  - This blocks obvious SSRF shapes without DNS resolution; production deployment still needs
    network egress controls.
  - Deal discovery still runs synchronously in the API path when enabled; queued deal jobs remain a
    future slice.
  - SearXNG/Crawl4AI remain disabled by default and are not price-truth sources.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/deals -q`
    -> 21 passed.
  - Targeted lint/type:
    `uv run ruff check src/flight_hunter/deals tests/unit/deals` -> All checks passed.
    `uv run mypy src/flight_hunter/deals` -> Success: no issues found in 8 source files.
  - `uv run pytest tests/unit --quiet` -> 311 passed, 5 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run ruff format --check .` -> 185 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 84 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Browser observer claim guards

- Goal: make the durable Personal Browser Observer worker respect configured runtime concurrency and
  same-source minimum gap before launching browser/fixture runner work.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add repository tests for `max_concurrent` and same-source `min_gap_seconds` at claim
     time.
  2. [done] Add conditional DB claim filters in `BrowserObservationJobRepository.claim_queued`.
  3. [done] Pass `PERSONAL_OBSERVER_MAX_CONCURRENT` and `PERSONAL_OBSERVER_MIN_GAP_SECONDS` from
     `flight-hunter-worker`.
  4. [done] Add worker-level regression coverage for a multi-job same-source pass.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/ops/worker.py`
- ADR/docs:
  - `docs/adr/0048-browser-observer-claim-guards.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/ops/test_worker_command.py`
- Risks:
  - This hardens DB claim behavior only; production supervisor/readiness dashboards remain future
    work.
  - Playwright runtime is still synchronous inside a worker process.
  - No new live browser scraping or new source parser was added.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/ops/test_worker_command.py -q`
    -> 13 passed.
  - `uv run pytest tests/unit --quiet` -> 294 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data search_by_price_range cached radar

- Goal: add the official cached Aviasales Data price-band endpoint without making it a live price
  source or default search path.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Add `SearchByPriceRangeQuery` and `/aviasales/v3/search_by_price_range` client support.
  3. [done] Add explicit planner and adapter methods with a validated integer price range.
  4. [done] Keep returned offers labelled cached and requiring external/live confirmation.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0047-aviasales-data-search-by-price-range.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - `search_by_price_range` is cached Aviasales Data, not live availability.
  - Values are provider major currency units at query time; backend Money remains minor units after
    parsing.
  - Popular endpoints and user-facing price-band UI remain future explicit follow-up work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py -q`
    -> 39 passed.
  - Targeted with contract catalog:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/application/test_source_contracts.py tests/unit/api/test_source_contracts_api.py -q`
    -> 45 passed.
  - `uv run pytest tests/unit --quiet` -> 291 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Mandatory phases

- [ ] Phase 0 - Discovery and ADR
- [ ] Phase 1 - Foundation
- [ ] Phase 2 - Identity/households/audit
- [ ] Phase 3 - Provider Policy Engine
- [ ] Phase 4 - Reference data/PostGIS
- [ ] Phase 5 - Core search/flexible dates/fake provider
- [ ] Phase 6 - Aviasales Data
- [ ] Phase 7 - Canonical offers/ranking/risk/total cost
- [ ] Phase 8 - Itinerary/split/self-transfer/hidden-city gating
- [ ] Phase 9 - Watches/scheduler/history
- [ ] Phase 10 - Price intelligence/deals/alerts
- [ ] Phase 11 - Telegram
- [ ] Phase 12 - Optional live providers
- [ ] Phase 13 - Full UI/PWA/i18n/accessibility
- [ ] Phase 14 - Security/operations/backups/observability
- [ ] Phase 15 - Release readiness

## Acceptance scenarios

- [ ] A Flexible dates
- [ ] B Nearby airports
- [ ] C Split ticket safety
- [ ] D Cached vs live
- [ ] E Aviasales isolation
- [ ] F Tracking
- [ ] G Alert dedupe
- [ ] H Suspected anomaly
- [ ] I Household privacy
- [ ] J Provider failure
- [ ] K No credentials/demo
- [ ] L Telegram security
- [ ] M Booking click gate
- [ ] N Backup/restore
- [ ] O Accessibility/i18n

## Previous slice

- Goal: establish a tested foundation for domain value objects, provider policy enforcement, and deterministic demo provider.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Create ADR for runtime/tooling and no-live-provider baseline.
  2. Add failing unit tests for Money, policy guard, search planning, and fake provider.
  3. Implement minimal production code that satisfies those tests without external provider calls.
  4. Run `uv run pytest`, `uv run ruff format --check`, `uv run ruff check`, and `uv run mypy`.
- Files/modules:
  - `src/flight_hunter/domain`
  - `src/flight_hunter/policy`
  - `src/flight_hunter/application`
  - `src/flight_hunter/providers`
  - `tests/unit`
- ADR: `docs/adr/0001-python-foundation-and-policy-first.md`
- Tests added:
  - `tests/unit/domain/test_money.py`
  - `tests/unit/policy/test_policy_guard.py`
  - `tests/unit/application/test_search_planner.py`
  - `tests/unit/providers/test_fake_provider.py`
- Docs updated:
  - `README.md`
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/provider-contracts/aviasales-search.md`
- Risks:
  - The full product is not complete in this slice.
  - Local PATH lacks global `ruff`, `mypy`, and `make`; commands are routed through `uv run`.
  - No real provider adapter is implemented yet; Aviasales Data/Search contract notes are documentation and policy inputs only.

## Last verified commands

```text
python --version -> Python 3.12.5
uv --version -> uv 0.9.26
uv python list 3.13 -> cpython-3.13.11 available
uv run pytest tests\unit -> 11 passed, Python 3.14.2
uv run ruff format --check . -> 15 files already formatted
uv run ruff check . -> All checks passed
uv run mypy -> Success: no issues found in 11 source files
pytest --version -> pytest 9.0.2
ruff --version -> not installed globally
mypy --version -> not installed globally
make --version -> not installed globally
git status -> not a git repository
Official Travelpayouts docs checked -> Aviasales Data/Search contract notes recorded
```

## Known external limitations

- No provider credentials are present.
- Aviasales Search, Skyscanner, Duffel live behavior must remain disabled until access is approved and policies are verified.
- The current workspace is not initialized as a git repository.

## No-placeholder audit

- [x] No TODO/pass/NotImplementedError in mandatory production paths for this slice
- [x] No fake response in real provider paths; no real provider paths exist yet
- [x] No live provider calls in CI
- [x] No secrets in repo/client/log fixtures

## Previous slice: backend foundation and demo search

- Goal: add backend foundation endpoints and application-level demo search without real provider calls.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing tests for provider registry, search service, and FastAPI endpoints.
  2. Implement provider registry with policy-derived status/reasons.
  3. Implement demo search use case using `SearchPlanner` and `FakeFlightProvider`.
  4. Add thin FastAPI delivery adapter for `/healthz`, `/api/v1/providers`, and `/api/v1/searches`.
  5. Run tests, lint, typecheck, and update this file.
- Files/modules:
  - `src/flight_hunter/application/provider_registry.py`
  - `src/flight_hunter/application/search_service.py`
  - `src/flight_hunter/api`
  - `tests/unit/application`
  - `tests/unit/api`
- ADR: `docs/adr/0002-backend-foundation-demo-search.md`
- Tests to add:
  - `tests/unit/application/test_provider_registry.py`
  - `tests/unit/application/test_search_service.py`
  - `tests/unit/api/test_api_app.py`
- Risks:
  - This is still an in-process demo path; persistence, auth, audit, and worker scheduling remain pending.
- Verification:
  - `uv run pytest tests\unit` -> 18 passed
  - `uv run ruff format --check .` -> 22 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 15 source files

## Previous slice: airport autocomplete and nearby demo

- Goal: add airport autocomplete and nearby airport calculation with deterministic demo data.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing tests for airport distance calculation, autocomplete, nearby service, and API endpoints.
  2. Implement pure geo domain objects and distance calculation.
  3. Implement in-memory demo airport repository and application service.
  4. Add thin FastAPI endpoints for `/api/v1/airports/autocomplete` and `/api/v1/airports/nearby`.
  5. Run tests, lint, typecheck, and update this file.
- Files/modules:
  - `src/flight_hunter/geo`
  - `src/flight_hunter/application/airport_service.py`
  - `src/flight_hunter/api/app.py`
  - `tests/unit/geo`
  - `tests/unit/application`
  - `tests/unit/api`
- ADR: `docs/adr/0003-airport-demo-reference-data.md`
- Tests to add:
  - `tests/unit/geo/test_airports.py`
  - `tests/unit/application/test_airport_service.py`
  - `tests/unit/api/test_airport_api.py`
- Risks:
  - Demo data is intentionally small; full OurAirports importer, PostGIS storage, and admin overrides remain pending.
- Verification:
  - `uv run pytest tests\unit` -> 24 passed
  - `uv run ruff format --check .` -> 29 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 19 source files

## Previous slice: flexible date matrix planning

- Goal: add flexible date matrix planning without provider calls.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing tests for round-trip date expansion, stay-length filtering, budget limits, and API serialization.
  2. Implement pure date matrix planner in application layer.
  3. Add thin FastAPI endpoint for matrix planning.
  4. Run tests, lint, typecheck, and update this file.
- Files/modules:
  - `src/flight_hunter/application/date_matrix.py`
  - `src/flight_hunter/api/app.py`
  - `tests/unit/application/test_date_matrix.py`
  - `tests/unit/api/test_date_matrix_api.py`
- ADR: `docs/adr/0004-flexible-date-matrix-planning.md`
- Tests to add:
  - `tests/unit/application/test_date_matrix.py`
  - `tests/unit/api/test_date_matrix_api.py`
- Risks:
  - Matrix planning does not price cells yet; provider-backed cached matrix and heatmap persistence remain pending.
- Verification:
  - `uv run pytest tests\unit` -> 28 passed
  - `uv run ruff format --check .` -> 32 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 20 source files

## Previous slice: alert hysteresis and dedupe

- Goal: add price-drop alert hysteresis and dedupe domain logic.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing tests for 12% drop alert, duplicate retry suppression, cooldown, and insignificant changes.
  2. Implement price snapshot and alert evaluator without Telegram delivery.
  3. Keep calculations in integer minor units.
  4. Run tests, lint, typecheck, and update this file.
- Files/modules:
  - `src/flight_hunter/notifications/alerts.py`
  - `tests/unit/notifications/test_alerts.py`
- ADR: `docs/adr/0005-alert-hysteresis-and-dedupe.md`
- Tests to add:
  - `tests/unit/notifications/test_alerts.py`
- Risks:
  - This does not include persistence, Telegram transport, quiet hours, or retry queue integration yet.
- Verification:
  - `uv run pytest tests\unit` -> 32 passed
  - `uv run ruff format --check .` -> 35 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 22 source files

## Previous slice: beginner-friendly onboarding

- Goal: make the project understandable for a beginner and state what is needed from the user.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Rewrite README as a short entry point.
  2. Add a plain Russian start guide.
  3. Add the exact demo API command.
  4. Verify the command starts and `/healthz` responds.
- Files/modules:
  - `README.md`
  - `docs/START_HERE_RU.md`
  - `pyproject.toml`
  - `Makefile`
- ADR:
  - n/a
- Tests to add:
  - n/a
- Risks:
  - This improves onboarding only; web UI is still pending.
- What is needed from the user:
  - Nothing required for current demo development.
  - Later, for real Aviasales Data API: Travelpayouts account, API token, optional marker.
  - Later, for Telegram: bot token from `@BotFather`, bot name, and production webhook URL.
  - Later, for production hosting: domain, server/VPS, owner email, generated app secrets.
- Verification:
  - `uv sync --group dev` -> success
  - `uv run uvicorn flight_hunter.api.app:app --host 127.0.0.1 --port 8000` -> server started
  - `GET /healthz` -> `{"app":"Flight Hunter","status":"ok","external_credentials_required":false}`
  - `uv run pytest tests\unit --quiet` -> 32 passed
  - `uv run ruff format --check .` -> 35 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 22 source files

## Previous slice: Aviasales Data adapter and token wiring

- Goal: Aviasales Data API adapter and safe Travelpayouts token wiring.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add policy-gated Aviasales Data client/mapper/adapter.
  2. Add `.env`/environment settings without storing secrets in repo.
  3. Wire optional Aviasales Data provider into search planning.
  4. Update user docs with local token setup.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data`
  - `src/flight_hunter/config.py`
  - `src/flight_hunter/application/provider_registry.py`
  - `src/flight_hunter/application/search_service.py`
- ADR:
  - `docs/provider-contracts/aviasales-data.md`
- Tests to add:
  - `tests/unit/providers/aviasales_data`
  - `tests/unit/test_config.py`
  - `tests/unit/application/test_provider_registry_env.py`
- Risks:
  - The provided token was not stored in the repository. It must be placed in local `.env` by the operator.
  - No live smoke call was run in automated tests. CI remains fixture/transport-only.
- Verification:
  - `uv run pytest tests\unit --quiet` -> 43 passed
  - `uv run ruff format --check .` -> 45 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 27 source files
  - `uv run uvicorn flight_hunter.api.app:app --host 127.0.0.1 --port 8000` -> server started
  - `GET /healthz` -> `{"app":"Flight Hunter","status":"ok","external_credentials_required":false}`

## Previous slice: persistence history and scheduler foundation

- Goal: persistence/auth/watch scheduler foundation.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add persistence models and migration baseline.
  2. [done] Add household isolation repository tests before implementation.
  3. [done] Add watch snapshot history and scheduler eligibility tests.
  4. [done] Integrate alert evaluator with durable dedupe state.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0001_initial.py`
  - `migrations/versions/0002_price_history_and_alert_dedupe.py`
  - `src/flight_hunter/application/watch_scheduler.py`
- ADR:
  - `docs/adr/0006-persistence-history-and-scheduler-foundation.md`
- Tests to add:
  - `tests/unit/persistence/test_household_watch_repository.py`
  - `tests/unit/persistence/test_migration_baseline.py`
  - `tests/unit/persistence/test_price_history_and_alert_dedupe.py`
  - `tests/unit/application/test_watch_scheduler.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - Invitation auth, distributed locks, worker process, and watch API endpoints remain pending.
  - SQLite is used for unit tests; PostgreSQL/PostGIS integration tests remain pending.
- Verification:
  - targeted persistence/scheduler tests -> 9 passed

## Previous slice: mergeable offer ranking

- Goal: rank mergeable offers with visible caveats and keep provider-isolated results separate.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing domain tests for freshness and caveat penalties.
  2. Integrate ranker into search service for mergeable offers only.
  3. Expose ranking reasons in API response.
  4. Document the ranking decision.
- Files/modules:
  - `src/flight_hunter/domain/ranking.py`
  - `src/flight_hunter/application/search_service.py`
  - `src/flight_hunter/api/app.py`
- ADR:
  - `docs/adr/0007-mergeable-offer-ranking.md`
- Tests to add:
  - `tests/unit/domain/test_offer_ranking.py`
  - `tests/unit/application/test_search_service.py`
  - `tests/unit/api/test_api_app.py`
- Risks:
  - Ranking is intentionally simple; itinerary/risk/total-cost model remains pending.
- Verification:
  - targeted ranking/search/API tests -> 11 passed

## Previous slice: beginner web UI

- Goal: add a beginner-friendly web screen without a separate frontend toolchain.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing test for `GET /`.
  2. Serve a compact FastAPI HTML/CSS/JS screen.
  3. Reuse provider/search API endpoints.
  4. Verify desktop and mobile browser flows.
- Files/modules:
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/api/app.py`
  - `README.md`
  - `docs/START_HERE_RU.md`
- ADR:
  - `docs/adr/0008-fastapi-served-beginner-web-ui.md`
- Tests to add:
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - This is a simple served UI, not the final Next.js/PWA.
- Verification:
  - `uv run pytest tests\unit --quiet` -> 58 passed
  - `uv run ruff format --check .` -> 61 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 33 source files
  - Playwright desktop 1440x960 -> search result rendered, no console/page errors
  - Playwright mobile 390x844 -> search result rendered, no horizontal overflow

## Previous slice: migration command and Alembic async upgrade

- Goal: make migrations executable through the project command interface.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing Alembic upgrade test against temp SQLite.
  2. Switch Alembic env to async engine.
  3. Add `make migrate` / `make dev` commands.
  4. Prevent generated local DB from entering the repo.
- Files/modules:
  - `migrations/env.py`
  - `alembic.ini`
  - `Makefile`
  - `.gitignore`
  - `README.md`
  - `docs/START_HERE_RU.md`
- ADR:
  - n/a
- Tests to add:
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - PostgreSQL integration test remains pending; current migration smoke test uses SQLite.
- Verification:
  - `uv run pytest tests\unit --quiet` -> 59 passed
  - `uv run ruff format --check .` -> 62 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 33 source files
  - `uv run alembic upgrade head` -> upgraded through `0002_price_history_and_alert_dedupe`

## Previous slice: Telegram webhook security foundation

- Goal: add Telegram webhook secret verification and `update_id` dedupe without real bot delivery.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing pure handler tests.
  2. Add failing FastAPI webhook tests.
  3. Implement disabled, secret mismatch, accepted and duplicate decisions.
  4. Keep Telegram disabled by default.
- Files/modules:
  - `src/flight_hunter/notifications/telegram.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/config.py`
  - `README.md`
- ADR:
  - `docs/adr/0009-telegram-webhook-security-foundation.md`
- Tests to add:
  - `tests/unit/notifications/test_telegram_webhook.py`
  - `tests/unit/api/test_telegram_api.py`
- Risks:
  - Dedupe is in-process for this foundation slice; durable Telegram update storage remains pending.
  - No Telegram message delivery is implemented yet.
- Verification:
  - `uv run pytest tests\unit --quiet` -> 65 passed
  - `uv run ruff format --check .` -> 65 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 34 source files

## Previous slice: Aviasales Data smoke helper

- Goal: add a safe local Travelpayouts credential smoke check.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Re-check official Travelpayouts docs.
  2. Add failing tests for missing credentials, sanitized success and 429.
  3. Implement `travelpayouts-smoke` without printing secrets/raw payloads.
  4. Document local usage.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/smoke.py`
  - `pyproject.toml`
  - `Makefile`
  - `README.md`
  - `docs/START_HERE_RU.md`
  - `docs/provider-contracts/aviasales-data.md`
- ADR:
  - `docs/adr/0010-aviasales-data-smoke-helper.md`
- Tests to add:
  - `tests/unit/providers/aviasales_data/test_smoke.py`
- Risks:
  - No live smoke was run because no local `.env` token is stored by the agent.
  - The user-provided token was not written to repo files.
- Verification:
  - `uv run pytest tests\unit\providers\aviasales_data\test_smoke.py -q` -> 3 passed
  - `uv run travelpayouts-smoke` with no local token -> `credentials_missing`, no network

## Previous slice: Watch API household foundation

- Goal: add persistent watch create/list endpoints with household isolation.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing API tests for missing auth context and household isolation.
  2. Add `WatchService` over persistence repository.
  3. Add `POST /api/v1/watches` and `GET /api/v1/watches`.
  4. Keep route handlers thin and use temporary household/user headers.
- Files/modules:
  - `src/flight_hunter/application/watch_service.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/config.py`
  - `README.md`
- ADR:
  - `docs/adr/0011-watch-api-household-context.md`
- Tests to add:
  - `tests/unit/api/test_watch_api.py`
- Risks:
  - Temporary headers are not final invitation/session auth.
  - UI watch creation flow remains pending.
- Verification:
  - `uv run pytest tests\unit\api\test_watch_api.py -q` -> 2 passed
  - `uv run pytest tests\unit --quiet` -> 70 passed
  - `uv run ruff format --check .` -> 69 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 36 source files

## Previous slice: local SQLite backup and restore

- Goal: add beginner-safe local backup/restore commands for demo SQLite.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing backup/restore tests.
  2. Implement backup copy with timestamped filename.
  3. Implement restore with previous DB preserved.
  4. Add CLI commands and docs.
- Files/modules:
  - `src/flight_hunter/ops/backup.py`
  - `pyproject.toml`
  - `Makefile`
  - `.gitignore`
  - `README.md`
  - `docs/START_HERE_RU.md`
- ADR:
  - `docs/adr/0012-local-sqlite-backup-restore.md`
- Tests to add:
  - `tests/unit/ops/test_backup_restore.py`
- Risks:
  - This is local SQLite backup/restore; PostgreSQL production backup runbook remains pending.
- Verification:
  - `uv run pytest tests\unit\ops\test_backup_restore.py -q` -> 3 passed
  - `uv run flight-hunter-backup --database .\does-not-exist.db --backup-dir .\backups-test` -> `database_missing`
  - `uv run pytest tests\unit --quiet` -> 73 passed
  - `uv run ruff format --check .` -> 72 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 38 source files

## Previous slice: admin provider health endpoint

- Goal: expose provider health state for future admin UI without leaking secrets.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. Add failing API test with token present.
  2. Return provider policy/credential/access state.
  3. Expose boolean secret presence only.
- Files/modules:
  - `src/flight_hunter/api/app.py`
  - `README.md`
- ADR:
  - `docs/adr/0013-admin-provider-health-endpoint.md`
- Tests to add:
  - `tests/unit/api/test_admin_provider_health_api.py`
- Risks:
  - Quota counters, circuit breaker state, and historical health metrics remain pending.
- Verification:
  - `uv run pytest tests\unit\api\test_admin_provider_health_api.py -q` -> 1 passed
  - `uv run pytest tests\unit --quiet` -> 74 passed
  - `uv run ruff format --check .` -> 73 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 38 source files

## Previous slice: agent presets, live refresh gap, price source catalog

- Goal: add a beginner-friendly agent preset layer, a 10-minute live refresh gap,
  and a RUB-first click-out price source model.
- Plan:
  1. [done] Add failing tests for live refresh cooldown and user-action policy.
  2. [done] Add failing tests for agent presets and API responses.
  3. [done] Implement deterministic presets without external LLM/MCP dependency.
  4. [done] Add live refresh gate with default 600-second gap.
  5. [done] Add price source catalog for external purchase flows.
  6. [done] Add scraping observer policy guard for future risky adapters.
  7. [done] Run full quality gate.
- Files/modules:
  - `src/flight_hunter/application/live_refresh.py`
  - `src/flight_hunter/agent/presets.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/config.py`
  - `src/flight_hunter/application/price_sources.py`
  - `src/flight_hunter/application/scraping_policy.py`
- ADR:
  - `docs/adr/0014-agent-presets-and-live-refresh-gap.md`
  - `docs/adr/0015-rub-clickout-price-observer.md`
- Tests to add:
  - `tests/unit/application/test_live_refresh.py`
  - `tests/unit/agent/test_presets.py`
  - `tests/unit/api/test_agent_api.py`
  - `tests/unit/application/test_price_sources.py`
  - `tests/unit/api/test_price_sources_api.py`
  - `tests/unit/application/test_scraping_policy.py`
- Risks:
  - Agent mode is deterministic presets only; no external Codex/MCP worker is connected yet.
  - Live provider adapters remain disabled until official access and contract flags are verified.
  - Direct scraping of aggregator/airline pages remains feature-flagged and denied unless
    source permission is documented.
- Verification:
  - `uv run pytest tests/unit --quiet` -> 96 passed
  - `uv run ruff format --check .` -> 84 files already formatted
  - `uv run ruff check .` -> All checks passed
  - `uv run mypy` -> Success: no issues found in 43 source files
  - `rg` exact user-provided Travelpayouts token -> not found in repo files

## Previous slice: live observation control plane and fake worker

- Goal: implement the user-action-only live observation control plane from
  `mega_plan_flight_search.md` without real browser scraping or live provider calls.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing domain tests for permission attestation and typed observation states.
  2. [done] Add failing application tests for one-time grants, idempotent observation creation,
     policy denial, and no worker/scheduler background execution.
  3. [done] Add failing API tests for `/api/v1/browser-sources`,
     `/api/v1/live-observation-grants`, `POST /api/v1/live-observations`, and
     `GET /api/v1/live-observations/{observation_id}`.
  4. [done] Implement an in-memory control plane and fake worker with no external network.
  5. [done] Update ADR/docs and run the quality gate.
- Files/modules:
  - `src/flight_hunter/domain/observation.py`
  - `src/flight_hunter/application/live_observations.py`
  - `src/flight_hunter/api/app.py`
  - `docs/provider-contracts/demo-browser-observer.md`
  - `README.md`
- ADR:
  - `docs/adr/0016-live-observation-control-plane.md`
- Tests to add:
  - `tests/unit/domain/test_observation.py`
  - `tests/unit/application/test_live_observations.py`
  - `tests/unit/api/test_live_observations_api.py`
- Risks:
  - This slice intentionally does not add a real Playwright/browser worker.
  - Browser observation remains disabled by default and can only run against the fake worker
    when explicitly enabled for the local demo.
  - Live observed prices still require manual confirmation before purchase.
- Verification:
  - RED: `uv run pytest tests\unit\domain\test_observation.py tests\unit\application\test_live_observations.py tests\unit\api\test_live_observations_api.py -q` -> failed with missing modules.
  - GREEN targeted: same command -> 12 passed.
  - `uv run pytest tests\unit --quiet` -> 108 passed.
  - `uv run ruff format --check .` -> 89 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 45 source files.
  - `uv run alembic upgrade head` -> upgraded local SQLite through `0002_price_history_and_alert_dedupe`.
  - No live provider calls were made.

## Previous slice: Search API and MCP policy skeletons

- Goal: add disabled-by-default policy interfaces for Aviasales Search-style live APIs and
  optional MCP tool output without production traffic or MCP as a source of truth.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing tests for Search API provider isolation, user-action-only execution,
     click-time booking action and no background calls.
  2. [done] Add failing tests for MCP output typed validation and policy gateway denial.
  3. [done] Implement application skeletons without provider clients or external calls.
  4. [done] Update ADR/docs and run the quality gate.
- Files/modules:
  - `src/flight_hunter/application/search_api_policy.py`
  - `src/flight_hunter/application/mcp_policy.py`
  - `README.md`
- ADR:
  - `docs/adr/0017-search-api-and-mcp-policy-skeletons.md`
- Tests to add:
  - `tests/unit/application/test_search_api_policy.py`
  - `tests/unit/application/test_mcp_policy.py`
- Risks:
  - Aviasales Search remains disabled until confirmed access and current contract review.
  - MCP integration remains a policy/validation skeleton; no MCP server is called.
- Verification:
  - RED: `uv run pytest tests\unit\application\test_search_api_policy.py tests\unit\application\test_mcp_policy.py -q` -> failed with missing modules.
  - GREEN targeted: same command -> 7 passed.
  - `uv run pytest tests\unit --quiet` -> 115 passed.
  - `uv run ruff format --check .` -> 93 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 47 source files.
  - No provider clients, MCP server calls, or live external calls were added.

## Previous slice: Web UI live-check demo flow

- Goal: activate the local fake live-observer demo and expose the user-click live-check flow in
  the beginner web UI without enabling real browser scraping or provider live calls.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing UI tests for live-check endpoints, button copy and no leaked grant token.
  2. [done] Add browser-source test isolation so local `.env` activation does not change
     disabled-by-default policy expectations.
  3. [done] Implement UI JavaScript flow:
     search result -> explicit live check button -> grant -> idempotent observation -> result.
  4. [done] Update docs/status and run the quality gate.
- Files/modules:
  - `.env` (local ignored demo activation, no secrets)
  - `src/flight_hunter/api/web.py`
  - `tests/unit/api/test_web_ui.py`
  - `tests/unit/api/test_live_observations_api.py`
- Risks:
  - This is still the simple FastAPI-served beginner UI, not the final Next.js/PWA.
  - The live check uses `demo_browser` fake worker only.
  - Real browser/source integrations remain disabled until per-source permission and contracts.
- Verification:
  - RED: `uv run pytest tests\unit\api\test_web_ui.py tests\unit\api\test_live_observations_api.py -q`
    -> failed on missing `/api/v1/browser-sources` UI reference.
  - GREEN targeted: same command -> 4 passed.
  - `uv run pytest tests\unit --quiet` -> 115 passed.
  - `uv run ruff format --check .` -> 93 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 47 source files.
  - `uv run alembic upgrade head` -> exit 0.
  - Local `.env` now enables only the fake observer: `SCRAPING_OBSERVER_ENABLED=true`.

## Previous slice: Telegram live-check callback service

- Goal: add a Telegram callback service for cached alerts -> "check live" without storing grant
  tokens, provider secrets or signed URLs in callback data.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing tests for safe callback data, callback idempotency and live observation
     creation through `telegram_callback` grants.
  2. [done] Implement application service over `LiveObservationService`.
  3. [done] Document the slice and run the quality gate.
- Files/modules:
  - `src/flight_hunter/application/telegram_live_check.py`
  - `tests/unit/application/test_telegram_live_check.py`
- Risks:
  - This slice does not yet implement durable Telegram account linking.
  - Webhook delivery still returns local API status only; actual Telegram message sending remains pending.
- Verification:
  - RED: `uv run pytest tests\unit\application\test_telegram_live_check.py -q` -> failed with missing module.
  - GREEN targeted: same command -> 3 passed.
  - `uv run pytest tests\unit --quiet` -> 118 passed.
  - `uv run ruff format --check .` -> 95 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 48 source files.
  - `uv run alembic upgrade head` -> exit 0.

## Previous slice: Live observation persistence foundation

- Goal: add durable schema/repository foundation for live observation grants and normalized live
  observation results.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing persistence tests for user-scoped grants, one-time consume and
     user-scoped observation lookup.
  2. [done] Add Alembic migration for grants, observations and observation offers.
  3. [done] Implement repository mappings without storing raw HTML/screenshots or secrets.
  4. [done] Run quality gate and update status.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0003_live_observations.py`
  - `tests/unit/persistence/test_live_observation_repository.py`
- Risks:
  - API still uses in-memory live observation service in this slice.
  - Full durable service wiring and cleanup/retention job remain pending.
- Verification:
  - RED: `uv run pytest tests\unit\persistence\test_live_observation_repository.py tests\unit\persistence\test_alembic_upgrade.py -q`
    -> failed with missing `LiveObservationRepository`.
  - GREEN targeted: same command -> 3 passed.
  - `uv run pytest tests\unit --quiet` -> 120 passed.
  - `uv run ruff format --check .` -> 97 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 48 source files.
  - `uv run alembic upgrade head` -> upgraded through `0003_live_observations`.

## Previous slice: Durable live-observation API wiring

- Goal: wire live-observation API endpoints to SQL-backed grant/observation/idempotency storage
  instead of process-local memory.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing API tests proving observation result and idempotency survive a new app
     instance using the same database.
  2. [done] Add durable idempotency table and repository helpers.
  3. [done] Implement async durable live-observation service over the repository.
  4. [done] Wire API endpoints through per-request DB sessions.
  5. [done] Run quality gate and update status.
- Files/modules:
  - `src/flight_hunter/application/durable_live_observations.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0004_live_observation_idempotency.py`
  - `tests/unit/api/test_live_observations_api.py`
- Risks:
  - Cleanup/retention job remains pending.
  - The fake worker is still synchronous inside request handling for the demo flow.
- Verification:
  - RED: `uv run pytest tests\unit\api\test_live_observations_api.py -q` -> failed with
    persisted observation lookup returning 404 after new app instance.
  - GREEN targeted: same command -> 4 passed.
  - `uv run pytest tests\unit --quiet` -> 121 passed.
  - `uv run ruff format --check .` -> 99 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 49 source files.
  - `uv run alembic upgrade head` -> upgraded through `0004_live_observation_idempotency`.

## Previous slice: Live observation retention cleanup

- Goal: add a safe cleanup path for expired live-observation grants/results/idempotency so local
  demo state does not retain short-lived live-check data indefinitely.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing persistence/application tests for expired cleanup and active-result
     preservation.
  2. [done] Implement repository cleanup helpers that remove dependent rows in a safe order.
  3. [done] Add a thin application service for future worker/ops invocation.
  4. [done] Update ADR/docs and run the quality gate.
- Files/modules:
  - `src/flight_hunter/application/live_observation_cleanup.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `tests/unit/application/test_live_observation_cleanup.py`
  - `tests/unit/persistence/test_live_observation_repository.py`
- ADR:
  - `docs/adr/0018-live-observation-retention-cleanup.md`
- Risks:
  - This slice adds a callable cleanup service, not a scheduled production worker yet.
  - No provider/browser calls are made.
- Verification:
  - RED: `uv run pytest tests\unit\persistence\test_live_observation_repository.py tests\unit\application\test_live_observation_cleanup.py -q`
    -> failed with missing `flight_hunter.application.live_observation_cleanup`.
  - GREEN targeted: same command -> 4 passed.
  - `uv run pytest tests\unit --quiet` -> 123 passed.
  - `uv run ruff format --check .` -> 101 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 50 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: Live observation cleanup command

- Goal: expose the live-observation retention cleanup through the project command interface for
  local ops without adding background provider/browser execution.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing ops tests for dry-run/missing-database/successful cleanup output.
  2. [done] Implement a sanitized CLI over `LiveObservationCleanupService`.
  3. [done] Wire `pyproject.toml`, `Makefile`, and docs.
  4. [done] Run targeted and full quality gate.
- Files/modules:
  - `src/flight_hunter/ops/live_observation_cleanup.py`
  - `tests/unit/ops/test_live_observation_cleanup_cli.py`
  - `pyproject.toml`
  - `Makefile`
  - `README.md`
  - `docs/START_HERE_RU.md`
- ADR:
  - `docs/adr/0018-live-observation-retention-cleanup.md`
- Risks:
  - This remains an operator-triggered command, not an automatic scheduler.
  - The command must not print secrets, raw payloads or PII.
- Verification:
  - RED: `uv run pytest tests\unit\ops\test_live_observation_cleanup_cli.py -q` -> failed
    with missing `flight_hunter.ops.live_observation_cleanup`.
  - GREEN targeted: `uv run pytest tests\unit\ops\test_live_observation_cleanup_cli.py tests\unit\application\test_live_observation_cleanup.py -q` -> 3 passed.
  - Manual CLI missing-db check:
    `uv run flight-hunter-cleanup-live-observations --database-url sqlite+aiosqlite:///./does-not-exist-live-cleanup.db --dry-run`
    -> `database_missing`, no DB file created.
  - `uv run pytest tests\unit --quiet` -> 125 passed.
  - `uv run ruff format --check .` -> 103 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 51 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: Durable Telegram update dedupe

- Goal: make Telegram `update_id` dedupe survive app restarts by storing accepted update IDs in
  persistence.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing repository/API/migration tests for durable duplicate detection.
  2. [done] Add migration/model/repository for Telegram update IDs.
  3. [done] Wire webhook endpoint to SQL-backed dedupe after secret validation.
  4. [done] Update ADR/docs/status and run quality gate.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/api/app.py`
  - `migrations/versions/0005_telegram_update_dedupe.py`
  - `tests/unit/persistence/test_telegram_update_repository.py`
  - `tests/unit/api/test_telegram_api.py`
- ADR:
  - `docs/adr/0019-durable-telegram-update-dedupe.md`
- Risks:
  - This does not implement Telegram account linking or message delivery yet.
  - Webhook callback actions remain safely unprocessed until linking/ownership checks exist.
- Verification:
  - RED: `uv run pytest tests\unit\persistence\test_telegram_update_repository.py tests\unit\api\test_telegram_api.py tests\unit\persistence\test_alembic_upgrade.py -q`
    -> failed with missing `TelegramUpdateRepository`.
  - GREEN targeted: same command -> 6 passed.
  - `uv run pytest tests\unit --quiet` -> 127 passed.
  - `uv run ruff format --check .` -> 105 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 51 source files.
  - `uv run alembic upgrade head` -> upgraded through `0005_telegram_update_dedupe`.

## Previous slice: Scheduler provider registry fail-closed guard

- Goal: prevent future watch scheduler wiring from registering live/browser/user-action providers,
  even if a provider policy is accidentally misconfigured as background-capable.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing scheduler registry tests for cached acceptance and live/user-action
     denial.
  2. [done] Implement `SchedulerProviderRegistry` as a pre-planning allowlist for scheduler-safe
     provider kinds.
  3. [done] Update ADR/docs/status and run quality gate.
- Files/modules:
  - `src/flight_hunter/application/watch_scheduler.py`
  - `tests/unit/application/test_watch_scheduler.py`
- ADR:
  - `docs/adr/0020-scheduler-provider-registry-guard.md`
- Risks:
  - This is a registration guard; a full worker dependency graph is still pending.
- Verification:
  - RED: `uv run pytest tests\unit\application\test_watch_scheduler.py -q` -> failed with
    missing `SchedulerProviderRegistry`.
  - GREEN targeted: same command -> 7 passed.
  - `uv run pytest tests\unit --quiet` -> 130 passed.
  - `uv run ruff format --check .` -> 105 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 51 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: SearchIntent passenger mix and trip type

- Goal: extend the domain search intent with explicit passenger mix and trip type while preserving
  the existing `passengers` field used by API/providers.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing domain tests for legacy passenger compatibility, explicit
     adults/children/infants validation, and trip-type consistency.
  2. [done] Implement `PassengerMix` and `TripType` in the domain without changing provider
     traffic.
  3. [done] Update docs/status and run quality gate.
- Files/modules:
  - `src/flight_hunter/domain/offers.py`
  - `tests/unit/domain/test_search_intent.py`
- ADR:
  - `docs/adr/0021-search-intent-passenger-mix-and-trip-type.md`
- Risks:
  - API request shape remains backward-compatible in this slice; exposing separate child/infant
    fields in HTTP/UI remains pending.
- Verification:
  - RED: `uv run pytest tests\unit\domain\test_search_intent.py -q` -> failed with missing
    `PassengerMix`.
  - GREEN targeted: same command -> 4 passed.
  - `uv run pytest tests\unit --quiet` -> 134 passed.
  - `uv run ruff format --check .` -> 106 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 51 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: Aviasales Data exact-date query planner

- Goal: route Aviasales Data exact-date searches through an explicit planner and fail closed for
  passenger mixes whose pricing basis is not represented by the cached Data API adapter yet.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing provider tests for exact one-way/round-trip query planning and
     child/infant passenger mix denial without HTTP calls.
  2. [done] Implement `AviasalesDataQueryPlanner` and wire the adapter through it.
  3. [done] Update provider contract docs/status and run quality gate.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- ADR:
  - `docs/adr/0022-aviasales-data-exact-date-query-planner.md`
- Docs:
  - `docs/provider-contracts/aviasales-data.md`
- Risks:
  - Broader Data API endpoints such as grouped/latest/popular remain pending.
  - Child/infant pricing is intentionally not estimated from adult cached prices.
- Verification:
  - RED: `uv run pytest tests\unit\providers\aviasales_data\test_query_planner.py tests\unit\providers\aviasales_data\test_adapter.py -q`
    -> failed with missing `flight_hunter.providers.aviasales_data.query_planner`.
  - GREEN targeted: same command -> 6 passed.
  - `uv run pytest tests\unit --quiet` -> 138 passed.
  - `uv run ruff format --check .` -> 108 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 52 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: API passenger mix validation

- Goal: expose explicit `adults`/`children`/`infants`/`trip_type` in search request handling while
  keeping the existing `passengers` total backward-compatible.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing API/application tests for valid passenger mix propagation and 422 on
     total mismatch.
  2. [done] Add request validation and pass mix fields into `SearchIntent`.
  3. [done] Update docs/status and run quality gate.
- Files/modules:
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/application/search_service.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/application/test_search_service.py`
- ADR:
  - `docs/adr/0023-api-passenger-mix-validation.md`
- Risks:
  - The beginner web form still sends only total passengers; richer UI controls remain pending.
- Verification:
  - RED: `uv run pytest tests\unit\api\test_api_app.py tests\unit\application\test_search_service.py -q`
    -> failed because API ignored mismatched mix and `SearchRequest` did not accept `adults`.
  - GREEN targeted: same command -> 11 passed.
  - `uv run pytest tests\unit --quiet` -> 141 passed.
  - `uv run ruff format --check .` -> 108 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 52 source files.
  - `uv run alembic upgrade head` -> exit 0, current head already applied.

## Previous slice: Beginner UI clarity and AI assistant panel

- Goal: replace the confusing narrow demo-looking first screen with a clearer search workbench and
  visible AI assistant panel.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add UI regression checks for visible AI assistant and passenger mix labels.
  2. [done] Redesign the FastAPI-served page using the existing vanilla HTML/CSS/JS stack.
  3. [done] Wire visible AI assistant controls to `/api/v1/agent/presets` and
     `/api/v1/agent/plan`.
  4. [done] Restart the local server and verify the new page is being served.
- Files/modules:
  - `src/flight_hunter/api/web.py`
  - `tests/unit/api/test_web_ui.py`
- Risks:
  - This is still the simple FastAPI-served UI, not the final PWA/Next.js frontend.
  - The AI assistant uses deterministic local presets, not an external LLM chat.
- Verification:
  - Targeted: `uv run pytest tests\unit\api\test_web_ui.py tests\unit\api\test_agent_api.py tests\unit\api\test_api_app.py -q` -> 11 passed.
  - `uv run pytest tests\unit --quiet` -> 141 passed.
  - `uv run ruff format --check .` -> 108 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 52 source files.
  - Local server restarted on `http://127.0.0.1:8001/`; smoke-check found
    `ИИ-помощник`, `Взрослые`, and `/api/v1/agent/plan` in served HTML.

## Current slice: Agent chat and city search

- Goal: turn the visible assistant into a chat-first agent workflow that resolves city names to
  airport choices, runs safe cached search/date/nearby tools, creates watches only from explicit
  user intent, and keeps live checks gated behind user action.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add failing tests for OurAirports import/search, agent chat turns, Codex CLI output
     validation, audit persistence, API responses, and chat-first UI markers.
  2. [done] Add SQLite-compatible airport/import/audit tables, repositories, and an
     `flight-hunter-import-airports` command for local `airports.csv` files.
  3. [done] Implement deterministic `AgentChatService` with typed actions and optional
     `CodexCliAgentAdapter` behind feature flags.
  4. [done] Wire `/api/v1/agent/chat/turn`, `/api/v1/airports/search`, the FastAPI-served UI,
     docs, and command interface.
  5. [done] Run full quality gate and restart the local server.
- Files/modules:
  - `src/flight_hunter/agent/chat.py`
  - `src/flight_hunter/agent/codex_cli.py`
  - `src/flight_hunter/geo/ourairports_importer.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0006_airports_and_agent_audit.py`
  - `src/flight_hunter/ops/airport_import.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
- ADR:
  - `docs/adr/0024-agent-chat-city-search-and-codex-cli-bridge.md`
- Risks:
  - Codex CLI must remain optional and sandboxed; it is not a source of prices, routes, provider
    policy, or live availability.
  - Browser/live source selection remains limited to policy/admin-attested sources and cannot
    bypass CAPTCHA, login, geo, anti-bot, proxy, cookie, or access restrictions.
  - OurAirports data is Public Domain but not guaranteed accurate; UI/API must expose import
    provenance and should not imply transfer or airfare savings from geography alone.
- Verification:
  - RED: `uv run pytest tests\unit\geo\test_ourairports_importer.py tests\unit\persistence\test_airport_reference_repository.py tests\unit\agent\test_chat.py tests\unit\agent\test_codex_cli_adapter.py tests\unit\api\test_agent_api.py tests\unit\api\test_web_ui.py tests\unit\ops\test_airport_import_cli.py tests\unit\test_env_example.py -q`
    -> failed with missing `ourairports_importer`, `agent.chat`, `agent.codex_cli`,
    airport repository and airport import command.
  - GREEN targeted: same command -> 18 passed.
  - `uv run pytest tests\unit --quiet` -> 153 passed.
  - `uv run ruff format --check .` -> 118 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 56 source files.
  - `uv run alembic upgrade head` -> upgraded through `0006_airports_and_agent_audit`.
  - Targeted migration/API/UI regression:
    `uv run pytest tests\unit\persistence\test_alembic_upgrade.py tests\unit\api\test_agent_api.py tests\unit\api\test_web_ui.py -q`
    -> 9 passed.
  - Local server restarted on `http://127.0.0.1:8001/` with PID `31204`.
  - Browser smoke: submitted `WAW BCN 2026-10-12 2026-10-19 следи` in the chat UI; the page stayed on
    `/`, rendered airport choices, cached/date/nearby actions, `Watch создан`, and user-action-only
    live check; raw `grant_token` was not displayed.
  - Final gate after browser JS fix:
    - `uv run pytest tests\unit --quiet` -> 153 passed.
    - `uv run ruff format --check .` -> 118 files already formatted.
    - `uv run ruff check .` -> All checks passed.
    - `uv run mypy` -> Success: no issues found in 56 source files.
    - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: Provider source contract catalog

- Goal: make the source/provider layer visible and testable instead of looking like a set of
  disabled stubs.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Verify GitHub remote branch visibility and current provider/source code.
  2. [done] Add tests for source contract readiness, implemented Aviasales Data, provider-isolated
     Aviasales Search, and contract-only live/bookable providers.
  3. [done] Implement `SourceContractCatalog` and `GET /api/v1/source-contracts`.
  4. [done] Run full quality gate and push the follow-up commit.
- Files/modules:
  - `src/flight_hunter/application/source_contracts.py`
  - `src/flight_hunter/api/app.py`
  - `tests/unit/application/test_source_contracts.py`
  - `tests/unit/api/test_source_contracts_api.py`
  - `docs/adr/0025-provider-source-contract-catalog.md`
  - `README.md`
- ADR:
  - `docs/adr/0025-provider-source-contract-catalog.md`
- Risks:
  - This is a readiness/contract map, not new live provider traffic.
  - Skyscanner, Duffel and Aviasales Search remain intentionally unavailable until approved access,
    current docs verification, fixtures and adapters exist.
  - GitHub remote is populated and `origin/HEAD` points to `main`, but repository metadata such as
    description/topics is outside the local code commit.
- Verification:
  - GitHub remote check: `origin/HEAD` -> `refs/heads/main`; remote `main` at
    `ae2de8b94079f7b6d8fc8c1c03fff84ddf145043` before this slice.
  - Web check: `https://github.com/Kiwunaka/aviasales` renders repository files, README and
    `1 Commit`.
  - RED: `uv run pytest tests/unit/application/test_source_contracts.py
    tests/unit/api/test_source_contracts_api.py -q` -> failed with missing
    `flight_hunter.application.source_contracts`.
  - GREEN targeted: same command -> 6 passed.
  - `uv run pytest tests/unit --quiet` -> 168 passed.
  - `uv run ruff format --check .` -> 123 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 58 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: Git publication preparation

- Goal: prepare the existing workspace for safe Git upload without adding product behavior.
- Result: implemented for this repository-hygiene slice. The full product is not complete.
- Plan:
  1. [done] Re-read repository instructions, architecture docs, provider matrix, ADRs, tests,
     migrations, and current status.
  2. [done] Tighten git hygiene so local runtime artifacts and secrets stay out of the
     repository.
  3. [done] Run unit tests, formatter check, lint, typecheck, migration check, and a local
     secret-pattern scan.
  4. [done] Initialize Git, inspect the candidate file set, and create an initial commit if the
     quality gate is green.
- Files/modules:
  - `.gitattributes`
  - `.gitignore`
  - `IMPLEMENTATION_STATUS.md`
- ADR:
  - n/a; this is repository hygiene and release-prep only.
- Risks:
  - No Git remote is configured in this workspace yet.
  - CI is not configured because there is no `.github/workflows` directory in the current tree.
  - Local `.env` and `flight_hunter_dev.db` exist but must remain ignored.
- Verification:
  - `git init -b main` -> initialized local repository on `main`.
  - `git add --dry-run .` -> 161 project files would be added before adding `.gitattributes`;
    local `.env`, SQLite DB, venv,
    caches and runtime directories stayed ignored.
  - `.gitattributes` added to keep repository text files on LF and avoid Windows checkout churn.
  - `git check-ignore -v .env flight_hunter_dev.db .venv .playwright-mcp .run .pytest_cache
    .ruff_cache .mypy_cache .codex-runtime` -> all ignored by `.gitignore`.
  - Broad redacted keyword scan -> 370 documentation/config/code references to secret-related
    words; values were not printed and reviewed as variable names/placeholders/docs.
  - Strict key-format scan (`sk-*`, GitHub tokens, AWS keys, private key blocks, JWT-like tokens)
    -> 0 findings.
  - `uv run pytest tests/unit --quiet` -> 162 passed.
  - `uv run ruff format --check .` -> 120 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 57 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: OpenAI agent harness and cockpit UI

- Goal: make the chat assistant a policy-aware agent harness with an optional OpenAI Responses
  backend, keep deterministic fallback, and redesign the FastAPI UI as a clearer human-in-the-loop
  agent cockpit.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add tests for OpenAI Responses payload/schema validation and unsafe output rejection.
  2. [done] Add optional `OpenAIResponsesAgentAdapter` behind `AGENT_OPENAI_ENABLED` and
     `OPENAI_API_KEY` without provider secrets or live/browser execution.
  3. [done] Return agent runtime metadata from `/api/v1/agent/chat/turn`.
  4. [done] Redesign the served UI around `Agent cockpit`, runtime strip, decision rail, airport
     choices, and policy-gated action cards.
  5. [done] Run full quality gate and restart the local server.
- Files/modules:
  - `src/flight_hunter/agent/openai_responses.py`
  - `src/flight_hunter/agent/chat.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/config.py`
  - `tests/unit/agent/test_openai_responses_adapter.py`
  - `tests/unit/api/test_agent_api.py`
  - `tests/unit/api/test_web_ui.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0024-agent-chat-city-search-and-codex-cli-bridge.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Risks:
  - OpenAI, Codex CLI, and future Cloudflare Agents SDK runtimes remain optional orchestration
    layers only; they are not sources of prices, schedules, provider policy, booking links, or live
    availability.
  - Cloudflare Agents SDK is documented as a future-compatible runtime boundary; this slice keeps
    the production path on FastAPI.
- Verification:
  - Targeted:
    `uv run pytest tests\unit\agent\test_openai_responses_adapter.py tests\unit\agent\test_chat.py tests\unit\api\test_agent_api.py tests\unit\api\test_web_ui.py tests\unit\test_env_example.py -q`
    -> 20 passed.
  - `uv run pytest tests\unit --quiet` -> 162 passed.
  - `uv run ruff format --check .` -> 120 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 57 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - Local server restarted on `http://127.0.0.1:8001/`; current listening process PID `5400`.
  - Browser smoke on `http://127.0.0.1:8001/`: submitted
    `Хочу из спб улететь в Шанхай в октябре`; saw `Agent cockpit`,
    `deterministic_harness`, `policy_validated_tool_plan`, `user action only`, airport choices
    `LED`, `PVG`, `SHA`, date clarification for October, and no visible `grant_token`.
  - Follow-up UX fix for `Хочу из спб улететь в Шанхай в октябре`:
    - Added demo/reference support for `LED`, `PVG`, `SHA`, Russian city aliases, and month-only
      `date_hint` handling without guessing an exact flight date.
    - Incomplete chat turns now render `clarify_airport_choice` and `clarify_travel_dates` cards
      instead of a dead-end message.
    - The FastAPI UI clears stale destination/date fields when the agent has not selected them.
    - Provider rows now explain missing real API keys/access as setup state, not a broken search.
    - Browser smoke on `http://127.0.0.1:8001/` with PID `56392`: submitted the phrase above;
      saw `LED`, `PVG`, `SHA`, `Уточнить дату: октябрь`, no `grant_token`, no console errors.
      Screenshot capture was attempted twice but the Browser CDP screenshot command timed out.
    - `uv run pytest tests\unit --quiet` -> 157 passed.
    - `uv run ruff format --check .` -> 118 files already formatted.
    - `uv run ruff check .` -> All checks passed.
    - `uv run mypy` -> Success: no issues found in 56 source files.
    - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: Bundle search results and RU click-out links

- Goal: make search output match the monster-plan result taxonomy by separating cached/priced
  offers, external check links, browser-observed offers, deal candidates and freshness summary.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add domain/API/application tests for `SearchBundle`-style outputs and external links
     that are never treated as prices.
  2. [done] Add conservative RU click-out source specs and link builder for aggregators/carriers.
  3. [done] Wire search responses and the FastAPI-served UI into separate result sections.
  4. [done] Add safe env flags for personal observer/search helper tooling and configurable
     click-out source allowlists.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/domain/search_results.py`
  - `src/flight_hunter/domain/offers.py`
  - `src/flight_hunter/providers/ru_clickout`
  - `src/flight_hunter/application/search_service.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/config.py`
  - `.env.example`
  - `.gitignore`
- ADR/docs:
  - `docs/adr/0015-rub-clickout-price-observer.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/domain/test_search_results.py`
  - `tests/unit/providers/ru_clickout/test_link_builder.py`
  - `tests/unit/application/test_search_service.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/api/test_web_ui.py`
  - `tests/unit/test_config.py`
  - `tests/unit/test_env_example.py`
- Risks:
  - Personal Browser Observer production runtime, parser pipeline, durable job worker and
    screenshots/DOM artifact retention are not implemented yet.
  - RU click-out links are external check links only; they intentionally do not contain fabricated
    prices, availability, booking URLs or precise deeplinks.
  - Aviasales Data broader endpoints and real deal feed ingestion remain future slices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/domain/test_search_results.py tests/unit/providers/ru_clickout/test_link_builder.py tests/unit/application/test_search_service.py tests/unit/api/test_api_app.py tests/unit/api/test_web_ui.py -q`
    -> 20 passed before env/config follow-up.
  - Targeted after env/config follow-up:
    `uv run pytest tests/unit/domain/test_search_results.py tests/unit/providers/ru_clickout/test_link_builder.py tests/unit/application/test_search_service.py tests/unit/api/test_api_app.py tests/unit/api/test_web_ui.py tests/unit/test_config.py tests/unit/test_env_example.py -q`
    -> 25 passed.
  - `uv run pytest tests/unit --quiet` -> 178 passed.
  - `uv run ruff format --check .` -> 129 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 62 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: Sanitized browser HTML offer extractor

- Goal: add the first offline parser pipeline piece for Personal Browser Observer results without
  doing browser automation, network calls or scraping bypasses.
- Result: implemented for this slice. The full product is not complete.
- Plan:
  1. [done] Add sanitized Tutu-style fixture with an explicit offer-card marker and a nearby
     non-ticket price.
  2. [done] Add `DomSnapshot`, `PriceCandidate`, `BrowserExtractionResult` and
     `GenericRuHtmlOfferExtractor`.
  3. [done] Parse only explicit `data-flight-offer`/`data-price` card context into
     `BrowserObservedOffer` with confidence and parser warnings.
  4. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/browser/__init__.py`
  - `src/flight_hunter/browser/html_extractor.py`
  - `tests/fixtures/browser/tutu/search_result_sanitized.html`
  - `tests/unit/browser/test_html_offer_extractor.py`
- ADR/docs:
  - `docs/adr/0015-rub-clickout-price-observer.md`
  - `README.md`
- Risks:
  - This is fixture-backed DOM extraction only; it does not include Playwright navigation,
    persistent browser profiles, Scrapling runtime integration, Crawl4AI extraction, screenshots or
    durable observer jobs.
  - The parser intentionally ignores prices outside explicit offer-card context to reduce false
    positives.
- Verification:
  - Targeted: `uv run pytest tests/unit/browser/test_html_offer_extractor.py -q` -> 3 passed.
  - `uv run pytest tests/unit --quiet` -> 181 passed.
  - `uv run ruff format --check .` -> 132 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 64 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.

## Current slice: Personal observer runtime and persisted browser observations

- Goal: turn the offline parser into a safe local Personal Browser Observer path with optional
  Playwright/Scrapling/Crawl4AI dependencies, a CLI, normalized persistence and search API surfacing
  for short-lived browser observations.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Pin the project to Python 3.13 and install optional `scraping`/`crawler` dependency
     groups with Playwright Chromium.
  2. [done] Add `ScraplingRuHtmlOfferExtractor` as the Scrapling-backed parser wrapper over the
     strict fixture-safe extractor.
  3. [done] Add `PersonalObserverRunner` and `flight-hunter-observe` with fixture mode, live
     user-action/source/host gates and sanitized JSON output.
  4. [done] Persist normalized `BrowserObservedOffer` rows with household/user/search scoping,
     expiry and no raw HTML payload storage.
  5. [done] Surface recent user-scoped browser observations in `POST /api/v1/searches`.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `.python-version`
  - `pyproject.toml`
  - `uv.lock`
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `src/flight_hunter/providers/personal_observer/cli.py`
  - `migrations/versions/0007_browser_observed_offers.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/search_service.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0015-rub-clickout-price-observer.md`
  - `docs/adr/0026-python313-personal-observer-runtime.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/browser/test_scrapling_offer_extractor.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/providers/personal_observer/test_cli.py`
  - `tests/unit/persistence/test_browser_observed_offer_repository.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - Superseded by later worker-loop and deal-discovery slices: the CLI/runtime now has DB-backed
    worker polling and deal extraction/persistence, but production supervision remains future work.
  - Browser-observed offers are short-lived observations, not booking guarantees.
- Verification:
  - Targeted before final docs:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/browser/test_scrapling_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_cli.py tests/unit/persistence/test_browser_observed_offer_repository.py tests/unit/api/test_api_app.py -q`
    -> 21 passed, 1 warning.
  - `uv run ruff format .` -> 1 file reformatted, 139 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 192 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 140 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run python --version` -> Python 3.13.11.
  - `uv run flight-hunter-observe --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20 --fixture-html tests/fixtures/browser/tutu/search_result_sanitized.html`
    -> 1 browser_observed offer, `persisted_count=0`, no network call.
  - `uv run mypy` -> Success: no issues found in 67 source files.
  - `uv run alembic upgrade head` -> applied `0007_browser_observed_offers` on local SQLite.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `git diff --check` -> passed.

## Current slice: Durable personal observation job queue

- Goal: add a durable Personal Browser Observer job path so API requests enqueue user-action jobs
  and a separate worker CLI executes browser/fixture observation and persists normalized offers.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `browser_observation_jobs` table and Alembic migration.
  2. [done] Add repository methods for idempotent job creation, tenant-scoped lookup and status
     transitions.
  3. [done] Add `PersonalObservationService` with grant validation, idempotent enqueue, runner
     protocol and normalized offer persistence.
  4. [done] Add `POST /api/v1/personal-observations/grants`,
     `POST /api/v1/personal-observations` and `GET /api/v1/personal-observations/{id}`.
  5. [done] Add `flight-hunter-run-personal-observation` worker CLI for queued jobs.
  6. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/providers/personal_observer/adapter.py`
  - `src/flight_hunter/providers/personal_observer/worker_cli.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0008_browser_observation_jobs.py`
  - `src/flight_hunter/api/app.py`
  - `pyproject.toml`
- ADR/docs:
  - `docs/adr/0015-rub-clickout-price-observer.md`
  - `docs/adr/0027-durable-personal-observation-jobs.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/providers/personal_observer/test_worker_cli.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - This adds a worker CLI, not a long-running daemon/supervisor.
  - The web UI still does not expose the real personal observer job flow.
  - Crawl4AI/SearXNG deal discovery remains a future slice.
  - Jobs are user-action durable work; the scheduler still must not create or run browser
    observations as background discovery.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/application/test_personal_observations.py tests/unit/providers/personal_observer/test_worker_cli.py tests/unit/api/test_api_app.py tests/unit/persistence/test_alembic_upgrade.py -q`
    -> 15 passed after TTL assertion fix.
  - `uv run ruff format .` -> 147 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 198 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 147 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 70 source files.
  - `uv run alembic upgrade head` -> applied `0008_browser_observation_jobs` on local SQLite.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.

## Current slice: Durable cached watch scan worker

- Goal: connect watches to a durable worker scan path for scheduler-approved cached/background
  providers, with append-only price history and retry-safe alert dedupe.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Extend watch persistence with passenger/currency/schedule metadata and add
     `watch_scan_jobs`.
  2. [done] Add `WatchScanService` that uses `WatchSchedulerPlanner` before any provider call.
  3. [done] Wire `flight-hunter-worker` to enqueue/process due watch scans in one-pass and loop
     modes.
  4. [done] Persist deterministic snapshots and alert dedupe so retries do not duplicate partial
     success.
  5. [done] Update docs/ADR/env and run targeted quality gates.
- Files/modules:
  - `src/flight_hunter/application/watch_scans.py`
  - `src/flight_hunter/application/watch_service.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0012_watch_scan_jobs.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0033-durable-watch-scan-worker.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_watch_scans.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/persistence/test_household_watch_repository.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/api/test_watch_api.py`
- Risks:
  - Superseded by the worker claim lease slice: watch scan jobs are now claimed with conditional
    DB updates before execution.
  - Superseded by the Telegram linking/outbox slice: alert dedupe now feeds durable Telegram
    notification rows.
  - Real Aviasales Data calls still require explicit env credentials and remain cached, not live.
  - Fake provider is used by the worker only as a no-credentials local demo fallback.
- Verification:
  - Targeted:
    `uv run pytest tests\unit\application\test_watch_scans.py tests\unit\ops\test_worker_command.py tests\unit\persistence\test_household_watch_repository.py tests\unit\persistence\test_price_history_and_alert_dedupe.py tests\unit\api\test_watch_api.py tests\unit\persistence\test_alembic_upgrade.py --quiet`
    -> 15 passed.
  - Targeted format:
    `uv run ruff format --check src\flight_hunter\application\watch_scans.py src\flight_hunter\ops\worker.py src\flight_hunter\persistence\repositories.py src\flight_hunter\persistence\models.py tests\unit\application\test_watch_scans.py tests\unit\ops\test_worker_command.py tests\unit\persistence\test_household_watch_repository.py`
    -> 7 files already formatted.
  - Targeted lint:
    `uv run ruff check src\flight_hunter\application\watch_scans.py src\flight_hunter\ops\worker.py src\flight_hunter\persistence\repositories.py src\flight_hunter\persistence\models.py tests\unit\application\test_watch_scans.py tests\unit\ops\test_worker_command.py tests\unit\persistence\test_household_watch_repository.py`
    -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 81 source files.
  - `uv run pytest tests\unit --quiet` -> 231 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 173 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run alembic upgrade head` -> applied through `0012_watch_scan_jobs`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Telegram linking and alert outbox

- Goal: add a retry-safe Telegram delivery foundation for price-drop alerts without using Telegram
  username as an account key and without making live Bot API calls in tests.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add one-time `telegram_link_codes`, durable `telegram_accounts` and
     `telegram_notification_outbox`.
  2. [done] Add `TelegramLinkService` and `TelegramNotificationService` with quiet-hours deferral.
  3. [done] Add `TelegramBotApiTransport` behind `TELEGRAM_ENABLED` + `TELEGRAM_BOT_TOKEN`.
  4. [done] Expose `POST /api/v1/telegram/link-code` and consume `/link CODE` through the existing
     webhook update-dedupe path.
  5. [done] Wire watch-scan price alerts to enqueue Telegram outbox rows only after alert dedupe is
     recorded.
- Files/modules:
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/application/watch_scans.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/ops/worker.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `migrations/versions/0013_telegram_linking_outbox.py`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0034-telegram-linking-and-outbox.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_telegram_notifications.py`
  - `tests/unit/api/test_telegram_api.py`
  - `tests/unit/application/test_watch_scans.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - Full Telegram command UX and long-detail web deep links remain future slices.
  - Actual send attempts require `TELEGRAM_ENABLED=true` and `TELEGRAM_BOT_TOKEN`; tests use fake
    transports and do not call Telegram live.
  - Outbox rows for users without a Telegram link are blocked until a future requeue/unblock flow.
- Verification:
  - Targeted:
    `uv run pytest tests\unit\application\test_telegram_notifications.py tests\unit\application\test_watch_scans.py tests\unit\api\test_telegram_api.py tests\unit\ops\test_worker_command.py tests\unit\persistence\test_alembic_upgrade.py --quiet`
    -> 17 passed, existing aiosqlite thread warnings in targeted API test.
  - `uv run pytest tests\unit --quiet` -> 236 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 176 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 82 source files.
  - `uv run alembic upgrade head` -> applied through `0013_telegram_linking_outbox`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Worker claim leases

- Goal: harden the DB-backed worker queues so parallel worker processes claim browser jobs, watch
  scan jobs and Telegram notifications before executing side effects.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add lease columns for browser observation jobs and Telegram notification outbox rows.
  2. [done] Add conditional repository claim methods for browser, watch scan and Telegram queues.
  3. [done] Move worker/service execution paths to process claimed rows only.
  4. [done] Preserve retry accounting: browser/watch attempts increment on claim; Telegram attempts
     increment only on send failure.
  5. [done] Add regression tests for claim-once behavior, quiet-hours lease release and migration
     columns.
- Files/modules:
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/application/watch_scans.py`
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/ops/worker.py`
  - `migrations/versions/0014_worker_lease_columns.py`
- ADR/docs:
  - `docs/adr/0035-worker-claim-leases.md`
  - `docs/adr/0033-durable-watch-scan-worker.md`
  - `docs/adr/0034-telegram-linking-and-outbox.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/persistence/test_watch_scan_job_repository.py`
  - `tests/unit/application/test_telegram_notifications.py`
  - `tests/unit/application/test_watch_scans.py`
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - Superseded by the stale-lock recovery slice: stale `running`/`sending` rows are now recovered
    before worker claims new work.
  - This is still a relational DB queue. Future production hardening can add external supervisor
    controls, alerts and deeper dashboard metrics.
  - Provider policies are unchanged: worker claims never create new browser/live work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/persistence/test_watch_scan_job_repository.py tests/unit/application/test_telegram_notifications.py tests/unit/application/test_watch_scans.py tests/unit/application/test_personal_observations.py tests/unit/ops/test_worker_command.py --quiet`
    -> 21 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/persistence/repositories.py src/flight_hunter/application/personal_observations.py src/flight_hunter/application/watch_scans.py src/flight_hunter/application/telegram_notifications.py src/flight_hunter/ops/worker.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/persistence/test_watch_scan_job_repository.py tests/unit/application/test_telegram_notifications.py tests/unit/persistence/test_alembic_upgrade.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/persistence/repositories.py src/flight_hunter/application/personal_observations.py src/flight_hunter/application/watch_scans.py src/flight_hunter/application/telegram_notifications.py src/flight_hunter/ops/worker.py`
    -> Success: no issues found in 5 source files.
  - `uv run pytest tests/unit --quiet` -> 239 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 178 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 82 source files.
  - `uv run alembic upgrade head` -> applied through `0014_worker_lease_columns`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `docker compose config` -> passed.
  - `make test-integration` / `make test-e2e` -> not runnable in this Windows shell because `make`
    is not installed.
  - `uv run pytest tests/integration --quiet` and `uv run pytest tests/e2e --quiet` -> suites are
    absent (`file or directory not found`), no integration/e2e tests collected.

## Current slice: Source smoke and deal discovery health

- Goal: add safe operational readiness checks for optional SearXNG/Crawl4AI deal-discovery sources
  without introducing live calls in CI or treating feed text as confirmed prices.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `flight-hunter-source-smoke` with summary-only JSON output.
  2. [done] Support `aviasales_data`, `searxng` and `crawl4ai` source names.
  3. [done] Keep disabled/missing-config states explicit and non-zero instead of fake success.
  4. [done] Add optional SearXNG `deal-discovery` compose profile and command-surface target.
  5. [done] Add SearXNG/Crawl4AI contract notes and ADR.
- Files/modules:
  - `src/flight_hunter/ops/source_smoke.py`
  - `pyproject.toml`
  - `Makefile`
  - `compose.yaml`
  - `.env.example`
- ADR/docs:
  - `docs/adr/0036-source-smoke-and-deal-discovery-health.md`
  - `docs/provider-contracts/searxng.md`
  - `docs/provider-contracts/crawl4ai.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/ops/test_source_smoke.py`
  - `tests/unit/ops/test_makefile_commands.py`
- Risks:
  - The compose profile uses `SEARXNG_IMAGE` with a default image for local experiments; production
    deployments should pin the image before use.
  - Crawl4AI live smoke requires the optional `crawler` dependency group and an explicit URL.
  - Source smoke checks readiness only; it does not create `DealCandidate` rows.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_source_smoke.py tests/unit/ops/test_makefile_commands.py tests/unit/deals --quiet`
    -> 10 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/ops/source_smoke.py tests/unit/ops/test_source_smoke.py tests/unit/ops/test_makefile_commands.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/ops/source_smoke.py`
    -> Success: no issues found in 1 source file.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `uv run pytest tests/unit --quiet` -> 244 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 180 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `docker compose config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Worker stale-lock recovery

- Goal: recover crashed-worker leases so DB-backed browser/watch/Telegram queues do not remain
  permanently stuck in `running` or `sending`.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add repository recovery for stale browser `running` jobs.
  2. [done] Add repository recovery for stale watch scan `running` jobs with deadline/max-attempt
     handling.
  3. [done] Add Telegram outbox recovery for stale `sending` rows without incrementing attempts.
  4. [done] Run recovery at the start of each worker pass before new claims/delivery.
  5. [done] Expose recovery counters in worker JSON output.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/ops/worker.py`
- ADR/docs:
  - `docs/adr/0035-worker-claim-leases.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/persistence/test_watch_scan_job_repository.py`
  - `tests/unit/application/test_telegram_notifications.py`
  - `tests/unit/ops/test_worker_command.py`
- Risks:
  - Recovery is driven by worker passes; an external supervisor still needs to keep a worker
    process running in production.
  - Dashboard/metrics for stale-lock recovery counts remain future operations work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/persistence/test_watch_scan_job_repository.py tests/unit/application/test_telegram_notifications.py tests/unit/ops/test_worker_command.py --quiet`
    -> 18 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/persistence/repositories.py src/flight_hunter/ops/worker.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/persistence/test_watch_scan_job_repository.py tests/unit/application/test_telegram_notifications.py tests/unit/ops/test_worker_command.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/persistence/repositories.py src/flight_hunter/ops/worker.py src/flight_hunter/application/telegram_notifications.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 248 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 180 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Watch actions and history API

- Goal: expose household-isolated watch detail, pause/resume actions and append-only price history.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add repository/service methods for pause/resume.
  2. [done] Add `GET /api/v1/watches/{watch_id}`.
  3. [done] Add `POST /api/v1/watches/{watch_id}/pause` and `/resume`.
  4. [done] Add `GET /api/v1/watches/{watch_id}/history` from `price_snapshots`.
  5. [done] Keep cross-household access hidden behind `watch_not_found`.
- Files/modules:
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/application/watch_service.py`
  - `src/flight_hunter/persistence/repositories.py`
- ADR/docs:
  - `docs/adr/0037-watch-actions-and-history-api.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/api/test_watch_api.py`
  - `tests/unit/persistence/test_household_watch_repository.py`
- Risks:
  - Superseded by the following versioned lifecycle slice for PATCH/archive/delete.
  - Web UI watch detail/history chart is still not a full dedicated screen.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/api/test_watch_api.py tests/unit/persistence/test_household_watch_repository.py tests/unit/application/test_watch_scans.py --quiet`
    -> 11 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/api/app.py src/flight_hunter/application/watch_service.py src/flight_hunter/persistence/repositories.py tests/unit/api/test_watch_api.py tests/unit/persistence/test_household_watch_repository.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/api/app.py src/flight_hunter/application/watch_service.py src/flight_hunter/persistence/repositories.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 251 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 180 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Versioned watch lifecycle API

- Goal: finish the core Phase 9 watch CRUD/versioning lifecycle so clients can edit, archive and
  delete watches without stale overwrites, while keeping scheduler and history safe.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `version`, `updated_at`, archive and soft-delete metadata to `watches`.
  2. [done] Add household-scoped `audit_events` for user/API lifecycle actions.
  3. [done] Add repository/service optimistic update, archive and delete operations.
  4. [done] Add `PATCH /api/v1/watches/{watch_id}`,
     `POST /api/v1/watches/{watch_id}/archive` and `DELETE /api/v1/watches/{watch_id}`.
  5. [done] Exclude archived/deleted watches from list/detail/history and due scheduler queries.
- Files/modules:
  - `migrations/versions/0015_watch_lifecycle_audit.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/watch_service.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0038-versioned-watch-lifecycle.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_household_watch_repository.py`
  - `tests/unit/api/test_watch_api.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
  - `tests/unit/agent/test_chat.py`
- Risks:
  - Dedicated web watch detail/history UI is still pending.
  - Telegram `/watches` and pause/resume callbacks can now build on this API but are not included
    in this slice.
  - Audit rows are persisted, but there is not yet an admin audit screen.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_household_watch_repository.py tests/unit/api/test_watch_api.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 15 passed.
  - `uv run pytest tests/unit --quiet` -> 257 passed, 1 `lxml` deprecation warning.
  - `uv run ruff format --check .` -> 181 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> upgraded local SQLite through
    `0015_watch_lifecycle_audit`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Telegram `/watches` command outbox

- Goal: start Telegram watch management with a safe linked-user `/watches` command that does not
  trust usernames, does not call providers and does not expose cross-household data.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add Telegram account lookup by durable `telegram_user_id`.
  2. [done] Add `TelegramWatchCommandService` to render household-scoped watch lists.
  3. [done] Enqueue `/watches` replies as `command_reply` rows in Telegram outbox.
  4. [done] Wire `/watches` into the secret-protected webhook after durable `update_id` dedupe.
  5. [done] Keep unlinked Telegram users silent and without outbox rows.
- Files/modules:
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/persistence/repositories.py`
- ADR/docs:
  - `docs/adr/0039-telegram-watch-command-outbox.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_telegram_watch_commands.py`
  - `tests/unit/api/test_telegram_api.py`
  - `tests/unit/application/test_telegram_notifications.py`
- Risks:
  - Inline keyboards and callback ownership checks are still pending.
  - `/pause` and `/resume` Telegram commands are not included in this slice.
  - Telegram command replies are plain text; richer buttons/deep links remain follow-up work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py tests/unit/application/test_telegram_notifications.py --quiet`
    -> 14 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/app.py src/flight_hunter/persistence/repositories.py tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py tests/unit/application/test_telegram_notifications.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/app.py src/flight_hunter/persistence/repositories.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 261 passed, 4 warnings
    (three existing `aiosqlite` TestClient thread warnings and one `lxml` deprecation warning).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified through
    `0015_watch_lifecycle_audit`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Telegram watch pause/resume callbacks

- Goal: let linked Telegram users pause/resume their own watches from inline callbacks while
  preserving household isolation, callback dedupe and optimistic version checks.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Define compact callback data `fh:w:p:<watch_uuid>:<version>` and
     `fh:w:r:<watch_uuid>:<version>`.
  2. [done] Add Pause/Resume inline button payloads to `/watches` command replies.
  3. [done] Resolve callback ownership through linked `telegram_user_id`, never username.
  4. [done] Apply pause/resume through versioned watch updates and reject stale callbacks.
  5. [done] Enqueue callback acknowledgements as durable outbox rows.
- Files/modules:
  - `src/flight_hunter/application/telegram_notifications.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/persistence/repositories.py`
- ADR/docs:
  - `docs/adr/0040-telegram-watch-callback-actions.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/application/test_telegram_watch_commands.py`
  - `tests/unit/api/test_telegram_api.py`
  - `tests/unit/application/test_telegram_notifications.py`
- Risks:
  - Superseded by the Telegram callback answer transport slice: callbacks now respond through
    durable `callback_ack` rows and Bot API `answerCallbackQuery`.
  - Text `/pause` and `/resume` commands remain pending.
  - Live refresh and booking callbacks remain policy-gated future work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py tests/unit/application/test_telegram_notifications.py --quiet`
    -> 18 passed.
  - Targeted lint:
    `uv run ruff check src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/app.py src/flight_hunter/persistence/repositories.py tests/unit/application/test_telegram_watch_commands.py tests/unit/api/test_telegram_api.py tests/unit/application/test_telegram_notifications.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src/flight_hunter/application/telegram_notifications.py src/flight_hunter/api/app.py src/flight_hunter/persistence/repositories.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 265 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified through
    `0015_watch_lifecycle_audit`.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data week-matrix cached radar

- Goal: add `/v2/prices/week-matrix` as an explicit Aviasales Data cached flexible-date radar
  endpoint without changing exact search behavior or making live-price claims.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Add `WeekMatrixQuery` and `/v2/prices/week-matrix` client support.
  3. [done] Parse endpoint-specific `value`, `depart_date`, `return_date` and `actual` fields.
  4. [done] Filter `actual=false` rows and avoid inventing booking/search links.
  5. [done] Add explicit planner/adapter method and keep default exact search on `prices_for_dates`.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0041-aviasales-data-week-matrix.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - Week-matrix remains cached/indicative data; UI/Telegram must still require external
    confirmation.
  - Month matrix, nearest-places matrix, price-range and popular endpoints remain future explicit
    cached-radar slices.
  - Existing `get_latest_prices` parser should be hardened with endpoint-specific fixtures before
    deeper workflow integration.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py -q`
    -> 22 passed.
  - Targeted lint:
    `uv run ruff check src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\query_planner.py src\flight_hunter\providers\aviasales_data\adapter.py tests\unit\providers\aviasales_data\test_client.py tests\unit\providers\aviasales_data\test_query_planner.py tests\unit\providers\aviasales_data\test_adapter.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\query_planner.py src\flight_hunter\providers\aviasales_data\adapter.py src\flight_hunter\application\source_contracts.py`
    -> Success: no issues found in 4 source files.
  - `uv run pytest tests/unit --quiet` -> 270 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Tutu source-specific observer diagnostics

- Goal: make Personal Browser Observer use a source-specific Tutu parser on sanitized fixtures,
  with typed diagnostics for selector drift and source challenges instead of a generic parser-only
  path.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add sanitized Tutu-like ticket fixtures without `data-flight-offer` generic markers.
  2. [done] Add `TutuRuHtmlOfferExtractor` selected by `RuAggregatorSpec.parser_id == "tutu"`.
  3. [done] Parse route/date/price/airline/stops/baggage from source-specific ticket-card markup.
  4. [done] Surface `selector_drift` and `source_challenge` diagnostics without raw HTML
     persistence.
  5. [done] Update CLI/worker examples and tests to use the source-specific Tutu fixture.
- Files/modules:
  - `src/flight_hunter/browser/html_extractor.py`
  - `src/flight_hunter/browser/__init__.py`
  - `src/flight_hunter/providers/personal_observer/runner.py`
  - `README.md`
  - `docs/START_HERE_RU.md`
- ADR/docs:
  - `docs/adr/0042-tutu-source-specific-observer-parser.md`
  - `docs/provider-contracts/tutu-browser-observer.md`
- Tests/fixtures added/updated:
  - `tests/fixtures/browser/tutu/search_result_source_specific.html`
  - `tests/fixtures/browser/tutu/search_result_source_specific_no_cards.html`
  - `tests/fixtures/browser/tutu/search_result_source_specific_challenge.html`
  - `tests/unit/browser/test_html_offer_extractor.py`
  - `tests/unit/providers/personal_observer/test_runner.py`
  - `tests/unit/providers/personal_observer/test_cli.py`
  - `tests/unit/providers/personal_observer/test_worker_cli.py`
  - `tests/unit/ops/test_worker_command.py`
- Risks:
  - This is still sanitized-fixture coverage, not approval to crawl live Tutu search/offers pages.
  - Live observation remains user-action-only and disabled by default; watch scans must not launch
    browser observations.
  - Yandex Travel, OneTwoTrip and carrier parser contracts remain future slices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/browser/test_scrapling_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_cli.py tests/unit/providers/personal_observer/test_worker_cli.py tests/unit/ops/test_worker_command.py -q`
    -> 21 passed, 1 warning.
  - Post-format targeted:
    `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/providers/personal_observer/test_cli.py tests/unit/providers/personal_observer/test_worker_cli.py tests/unit/ops/test_worker_command.py -q`
    -> 20 passed.
  - `uv run pytest tests/unit --quiet` -> 274 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format src\flight_hunter\browser\html_extractor.py` -> 1 file reformatted.
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data latest prices contract hardening

- Goal: make `/v3/get_latest_prices` parse endpoint-specific cached-radar fields instead of relying
  on the `prices_for_dates` item shape.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add docs-style latest fixture coverage for `value`, `depart_date`, `return_date`,
     `found_at` and `actual`.
  2. [done] Filter `actual=false` rows before mapping to offers.
  3. [done] Store parsed provider `found_at` on normalized Aviasales items.
  4. [done] Use provider `found_at` as `FlightOffer.observed_at` when present.
  5. [done] Preserve legacy `price`/`departure_at` fixture compatibility and cached semantics.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0043-aviasales-data-latest-contract-hardening.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - Rate-limit header metadata and endpoint-specific cache persistence remain future hardening work.
  - Latest prices remain cached/indicative and must never be shown as live availability.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py -q`
    -> 24 passed.
  - Targeted lint:
    `uv run ruff check src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\adapter.py tests\unit\providers\aviasales_data\test_client.py tests\unit\providers\aviasales_data\test_adapter.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\adapter.py`
    -> Success: no issues found in 2 source files.
  - `uv run pytest tests/unit --quiet` -> 276 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data rate-limit metadata

- Goal: parse Travelpayouts `X-Rate-Limit-*` headers into sanitized metadata and expose it through
  local smoke summaries without leaking raw headers, tokens, URLs or payloads.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Restore strict `prices_for_dates` parsing so latest-shaped payloads do not silently
     pass through the exact-date endpoint parser.
  2. [done] Add `AviasalesDataRateLimit` metadata to successful responses.
  3. [done] Attach the same metadata to 429 `AviasalesDataRateLimited` exceptions.
  4. [done] Print only sanitized quota counters in `travelpayouts-smoke` and
     `flight-hunter-source-smoke`.
  5. [done] Update provider contract/source catalog invariants and ADR.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/smoke.py`
  - `src/flight_hunter/ops/source_smoke.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0044-aviasales-data-rate-limit-metadata.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_smoke.py`
  - `tests/unit/ops/test_source_smoke.py`
- Risks:
  - This exposes provider quota metadata; it does not yet implement adaptive worker backoff from
    quota headers.
  - Internal low RPM policy remains the primary guard; provider headers are operator/source-health
    feedback for now.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/providers/aviasales_data/test_smoke.py tests/unit/ops/test_source_smoke.py -q`
    -> 28 passed.
  - Targeted lint:
    `uv run ruff check src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\smoke.py src\flight_hunter\ops\source_smoke.py tests\unit\providers\aviasales_data\test_client.py tests\unit\providers\aviasales_data\test_smoke.py tests\unit\ops\test_source_smoke.py`
    -> All checks passed.
  - Targeted typecheck:
    `uv run mypy src\flight_hunter\providers\aviasales_data\client.py src\flight_hunter\providers\aviasales_data\smoke.py src\flight_hunter\ops\source_smoke.py`
    -> Success: no issues found in 3 source files.
  - `uv run pytest tests/unit --quiet` -> 278 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit counters `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`, rate-limit counters `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data month-matrix cached radar

- Goal: add `/v2/prices/month-matrix` as an explicit month-level Aviasales Data cached flexible-date
  radar endpoint, preserving cached semantics and not changing exact search behavior.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `MonthMatrixQuery` and `/v2/prices/month-matrix` client support.
  2. [done] Send token only through `X-Access-Token` and keep safe query params.
  3. [done] Parse shared matrix rows with `value`, `depart_date`, `return_date`, `found_at` and
     `actual`.
  4. [done] Filter `actual=false` rows and avoid inventing booking/search links.
  5. [done] Add explicit planner/adapter method with conservative round-trip duration weeks.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0045-aviasales-data-month-matrix.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - Month matrix remains cached/indicative data and requires external confirmation.
  - Nearest-places matrix, price-range and popular endpoints remain future explicit cached-radar
    slices.
  - Flexible-date UI still needs to consume these radar methods directly.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/providers/aviasales_data/test_smoke.py -q`
    -> 33 passed.
  - Post-format targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py -q`
    -> 30 passed.
  - `uv run pytest tests/unit --quiet` -> 282 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format src\flight_hunter\providers\aviasales_data\query_planner.py` ->
    1 file reformatted.
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit counters `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected local no-token
    result: `ok=false`, `code=credentials_missing`, rate-limit counters `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected disabled result:
    `ok=false`, `code=searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` ->
    expected disabled result: `ok=false`, `code=crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.
  - `git diff --check` -> passed.

## Current slice: command surface and local compose stack

- Goal: make the project command surface match AGENTS.md and add a working local compose path for
  the API/worker stack.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Move SQLite async driver `aiosqlite` into runtime dependencies.
  2. [done] Add `Dockerfile`, `.dockerignore` and `compose.yaml`.
  3. [done] Add Make targets for integration/e2e/security/seed-demo/compose-up/compose-down.
  4. [done] Add deterministic `flight-hunter-seed-demo`.
  5. [done] Add high-confidence local `flight-hunter-security-scan`.
- Files/modules:
  - `Dockerfile`
  - `compose.yaml`
  - `.dockerignore`
  - `Makefile`
  - `pyproject.toml`
  - `uv.lock`
  - `src/flight_hunter/ops/seed_demo.py`
  - `src/flight_hunter/ops/security_scan.py`
- ADR/docs:
  - `docs/adr/0032-command-surface-and-compose.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/ops/test_makefile_commands.py`
  - `tests/unit/ops/test_seed_demo.py`
  - `tests/unit/ops/test_security_scan.py`
- Risks:
  - Compose is a local SQLite self-hosted stack, not final Postgres/Redis production topology.
  - Integration/E2E Make targets are present and honest, but dedicated suites are still future work.
  - Security scan is a local secret scan, not full dependency/SAST coverage.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/ops/test_seed_demo.py tests/unit/ops/test_security_scan.py tests/unit/ops/test_makefile_commands.py --quiet`
    -> 4 passed.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - Integration/E2E target equivalents -> reported absent suites cleanly.
  - `docker compose config` -> passed.
  - `docker compose build api` -> not executed because Docker Desktop engine is not running in
    this environment (`dockerDesktopLinuxEngine` pipe missing).
  - `uv run ruff format .` -> 170 files left unchanged.
  - `uv run ruff check .` -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 226 passed, 5 warnings
    (existing `aiosqlite` thread warnings and one `lxml` deprecation warning from Scrapling).
  - `uv run ruff format --check .` -> 170 files already formatted.
  - `uv run mypy` -> Success: no issues found in 80 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data nearest-places cached radar

- Goal: add the official cached Aviasales Data nearby-place matrix endpoint without live claims,
  hidden booking links or token leakage.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Add `NearestPlacesMatrixQuery` and `/v2/prices/nearest-places-matrix` client support.
  3. [done] Add explicit planner and adapter methods for cached nearby-place radar.
  4. [done] Mark Aviasales Data as supporting nearby cached radar while documenting that this is
     not live nearby-airport inventory.
  5. [done] Run the full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
  - `src/flight_hunter/application/provider_registry.py`
  - `src/flight_hunter/application/source_contracts.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0046-aviasales-data-nearest-places-matrix.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
  - `tests/unit/application/test_source_contracts.py`
- Risks:
  - `nearest-places-matrix` is cached Aviasales Data, not live availability.
  - The endpoint returns nearby-place hints only; dedicated UI/API presentation remains future work.
  - Price-range/popular Aviasales Data endpoints remain explicit follow-up work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py tests/unit/application/test_source_contracts.py -q`
    -> 39 passed.
  - `uv run pytest tests/unit --quiet` -> 286 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format src/flight_hunter/application/provider_registry.py` -> 1 file
    reformatted.
  - `uv run ruff format --check .` -> 182 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 83 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run flight-hunter-security-scan` -> `ok=true`, `finding_count=0`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source aviasales_data` -> expected
    `credentials_missing`, rate-limit fields `null`.
  - `uv run flight-hunter-source-smoke --source searxng` -> expected `searxng_disabled`.
  - `uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/` -> expected
    `crawl4ai_disabled`.
  - `docker compose --profile deal-discovery config` -> passed.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Aviasales Data latest cached radar

- Goal: add another official cached Aviasales Data endpoint beyond exact search/grouped radar while
  keeping it explicit and non-live.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Add `LatestPricesQuery` and `/aviasales/v3/get_latest_prices` client support.
  3. [done] Add explicit latest prices planner and adapter method.
  4. [done] Keep default exact search path on `prices_for_dates`; latest prices are cached radar.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0031-aviasales-data-latest-prices.md`
  - `README.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - `get_latest_prices` is cached Aviasales Data, not live availability.
  - Popular endpoints remain future work.
  - Flexible matrix/deal UI is not yet wired to latest prices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py --quiet`
    -> 17 passed.
  - `uv run ruff format .` -> 165 files left unchanged.
  - `uv run ruff check .` -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 222 passed, 4 warnings
    (existing `aiosqlite` thread warnings in watch API test and one `lxml` deprecation warning
    from Scrapling dependency).
  - `uv run ruff format --check .` -> 165 files already formatted.
  - `uv run mypy` -> Success: no issues found in 78 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: durable browser observation worker loop

- Goal: move `flight-hunter-worker` from one-pass only to a local DB-backed polling worker with
  durable attempts and retry scheduling for already queued user-action browser jobs.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add retry metadata to `browser_observation_jobs`.
  2. [done] Filter queue polling by `next_retry_at` and existing `expires_at` deadline.
  3. [done] Increment attempts when a job starts.
  4. [done] Schedule retries only for transient `timed_out` and `source_unavailable` runner
     statuses.
  5. [done] Add expired live observation cleanup to the worker, with `--skip-live-cleanup`.
  6. [done] Record append-only `source_health_events` for each processed browser observation job.
  7. [done] Add `flight-hunter-worker --loop`, idle sleep, stop-after-iterations and retry CLI
     options.
  8. [done] Keep worker policy-safe: it processes only already queued jobs and does not create
     provider/browser discovery itself.
- Files/modules:
  - `migrations/versions/0011_source_health_events.py`
  - `migrations/versions/0010_browser_observation_job_retries.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/personal_observations.py`
  - `src/flight_hunter/ops/worker.py`
- ADR/docs:
  - `docs/adr/0030-browser-observation-worker-loop.md`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/application/test_personal_observations.py`
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/persistence/test_source_health_event_repository.py`
  - `tests/unit/ops/test_worker_command.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - Superseded by later slices: browser jobs are now claimed with conditional DB leases, and the
    worker also processes cached watch scans.
  - Source health events currently cover browser observation jobs, not every provider/admin check.
  - Production supervisor/Docker orchestration remains future work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_personal_observations.py tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/ops/test_worker_command.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 10 passed.
  - Source-health targeted:
    `uv run pytest tests/unit/ops/test_worker_command.py tests/unit/persistence/test_source_health_event_repository.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 5 passed.
  - Follow-up cleanup integration targeted:
    `uv run pytest tests/unit/ops/test_worker_command.py tests/unit/application/test_personal_observations.py tests/unit/persistence/test_browser_observation_job_repository.py --quiet`
    -> 10 passed.
  - `uv run ruff format .` -> 165 files left unchanged.
  - `uv run ruff check .` -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 218 passed, 4 warnings
    (existing `aiosqlite` thread warnings in watch API test and one `lxml` deprecation warning
    from Scrapling dependency).
  - `uv run ruff format --check .` -> 165 files already formatted.
  - `uv run mypy` -> Success: no issues found in 78 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified after
    `0011_source_health_events`.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: durable deal candidate persistence

- Goal: make manual deal discovery durable enough to reappear in search results without treating it
  as confirmed price or availability.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add `deal_candidates` table and Alembic migration.
  2. [done] Add `DealCandidateRepository` with household/user/search scoping and TTL filtering.
  3. [done] Persist candidates from `POST /api/v1/deals/discover` only when valid auth context and
     `search_id` are present.
  4. [done] Return scoped unexpired candidates from `POST /api/v1/searches` under
     `deal_candidates`, never under `offers` or `priced_offers`.
  5. [done] Wire web deal discovery button to pass demo household/user headers and current
     `search_id`.
- Files/modules:
  - `migrations/versions/0009_deal_candidates.py`
  - `src/flight_hunter/persistence/models.py`
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/application/search_service.py`
  - `src/flight_hunter/api/app.py`
  - `src/flight_hunter/api/web.py`
  - `src/flight_hunter/config.py`
- ADR/docs:
  - `docs/adr/0029-deal-discovery-candidates.md`
  - `.env.example`
  - `README.md`
  - `docs/START_HERE_RU.md`
- Tests added/updated:
  - `tests/unit/persistence/test_deal_candidate_repository.py`
  - `tests/unit/api/test_api_app.py`
  - `tests/unit/application/test_search_service.py`
  - `tests/unit/persistence/test_alembic_upgrade.py`
- Risks:
  - Deal candidates are manual hints, not prices, and require external/user verification.
  - SearXNG/Crawl4AI production deployment and health checks remain future work.
  - Long-running worker daemon remains future work.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/application/test_search_service.py tests/unit/api/test_api_app.py tests/unit/persistence/test_deal_candidate_repository.py tests/unit/persistence/test_alembic_upgrade.py --quiet`
    -> 20 passed.
  - `uv run ruff format .` -> 162 files left unchanged.
  - `uv run ruff check .` -> All checks passed.
  - `uv run pytest tests/unit --quiet` -> 213 passed, 4 warnings
    (three `aiosqlite` thread warnings in existing watch API test and one `lxml` deprecation
    warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 162 files already formatted.
  - `uv run mypy` -> Success: no issues found in 78 source files.
  - `uv run alembic upgrade head` -> applied `0009_deal_candidates` on local SQLite.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Local worker command for queued browser jobs

- Goal: add a single entrypoint `flight-hunter-worker` that processes already-queued personal
  observation jobs without creating background browser discovery.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add repository polling for unexpired queued browser observation jobs.
  2. [done] Add `flight-hunter-worker` one-pass command using `PersonalObservationService`.
  3. [done] Add fixture-safe worker command test.
  4. [done] Run full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/persistence/repositories.py`
  - `src/flight_hunter/ops/worker.py`
  - `pyproject.toml`
  - `README.md`
- Tests added/updated:
  - `tests/unit/persistence/test_browser_observation_job_repository.py`
  - `tests/unit/ops/test_worker_command.py`
- Risks:
  - Superseded by later worker-loop and worker-claim-leases slices: the command now supports
    polling loop modes and conditional DB claims, but not production supervision.
  - It processes user-action-created browser jobs only; it does not create background browser
    discovery.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/persistence/test_browser_observation_job_repository.py tests/unit/ops/test_worker_command.py tests/unit/providers/personal_observer/test_worker_cli.py -q`
    -> 4 passed.
  - `uv run ruff format .` -> 160 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 210 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 160 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 78 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.
  - `rg -n "pass$|TODO|NotImplementedError" src` -> no matches.

## Current slice: Web UI manual observer and deal actions

- Goal: expose the newly implemented durable personal observation queue and manual deal discovery
  through the beginner web UI without running browser work inside API requests.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Add route-level controls for "Считать из браузера" and "Найти акции".
  2. [done] Wire personal observation grant/job enqueue with tenant headers and idempotency.
  3. [done] Render queued worker CLI instruction and deal discovery disabled/candidate states.
  4. [done] Run full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/api/web.py`
  - `tests/unit/api/test_web_ui.py`
  - `README.md`
- Risks:
  - The UI queues jobs; the actual browser run still happens through worker CLI.
  - Deal discovery remains disabled unless SearXNG/Crawl4AI settings are enabled.
- Verification:
  - Targeted: `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_api_app.py -q`
    -> 12 passed.
  - `uv run ruff format .` -> 158 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 208 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 158 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 77 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.

## Current slice: Deal discovery candidate foundation

- Goal: add a safe SearXNG/Crawl4AI-backed deal discovery foundation that creates manual
  `DealCandidate` hints without treating feed text as confirmed price or availability.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check SearXNG Search API and Crawl4AI references on 2026-06-29.
  2. [done] Add `src/flight_hunter/deals` query builder, SearXNG client, Crawl4AI markdown boundary,
     extractor and service.
  3. [done] Add sanitized markdown fixture and tests with no live SearXNG/Crawl4AI calls.
  4. [done] Add `POST /api/v1/deals/discover`, disabled by default unless SearXNG/Crawl4AI are
     enabled or a test service is injected.
  5. [done] Run full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/deals/models.py`
  - `src/flight_hunter/deals/query_builder.py`
  - `src/flight_hunter/deals/searxng_client.py`
  - `src/flight_hunter/deals/crawl4ai_client.py`
  - `src/flight_hunter/deals/extractor.py`
  - `src/flight_hunter/deals/service.py`
  - `src/flight_hunter/api/app.py`
- ADR/docs:
  - `docs/adr/0029-deal-discovery-candidates.md`
  - `README.md`
- Tests added/updated:
  - `tests/fixtures/crawl4ai/deal_page_markdown.md`
  - `tests/unit/deals/test_query_builder.py`
  - `tests/unit/deals/test_searxng_client.py`
  - `tests/unit/deals/test_extractor.py`
  - `tests/unit/deals/test_service.py`
  - `tests/unit/api/test_api_app.py`
- Risks:
  - Deal discovery is not wired into the web UI yet.
  - SearXNG/Crawl4AI production deployment and health checks remain future work.
  - Candidates intentionally require manual verification and are never merged into priced ranking.
- Verification:
  - Targeted: `uv run pytest tests/unit/deals -q` -> 4 passed.
  - Targeted API follow-up: `uv run pytest tests/unit/api/test_api_app.py tests/unit/deals -q`
    -> 15 passed.
  - `uv run ruff format .` -> 1 file reformatted, 157 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 208 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 158 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 77 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.

## Current slice: Aviasales Data grouped cached radar

- Goal: add at least one broader Aviasales Data endpoint beyond `prices_for_dates` while preserving
  cached semantics, token safety and no live CI calls.
- Result: implemented for this slice. The full monster plan is not complete.
- Plan:
  1. [done] Re-check official Travelpayouts Aviasales Data/rate-limit docs on 2026-06-29.
  2. [done] Add `GroupedPricesQuery` and `/aviasales/v3/grouped_prices` client support.
  3. [done] Add explicit grouped prices planner and adapter method.
  4. [done] Keep exact search path on `prices_for_dates`; grouped prices are an explicit cached
     radar call for future matrix/deal workflows.
  5. [done] Run full quality gate and record final command output.
- Files/modules:
  - `src/flight_hunter/providers/aviasales_data/client.py`
  - `src/flight_hunter/providers/aviasales_data/query_planner.py`
  - `src/flight_hunter/providers/aviasales_data/adapter.py`
- ADR/docs:
  - `docs/provider-contracts/aviasales-data.md`
  - `docs/adr/0028-aviasales-data-grouped-prices.md`
- Tests added/updated:
  - `tests/unit/providers/aviasales_data/test_client.py`
  - `tests/unit/providers/aviasales_data/test_query_planner.py`
  - `tests/unit/providers/aviasales_data/test_adapter.py`
- Risks:
  - `grouped_prices` is cached Aviasales Data, not live availability.
  - Latest/popular endpoints remain future work.
  - Flexible matrix UI is not yet wired to grouped prices.
- Verification:
  - Targeted:
    `uv run pytest tests/unit/providers/aviasales_data/test_client.py tests/unit/providers/aviasales_data/test_query_planner.py tests/unit/providers/aviasales_data/test_adapter.py -q`
    -> 13 passed.
  - `uv run ruff format .` -> 147 files left unchanged.
  - `uv run pytest tests/unit --quiet` -> 202 passed, 1 warning
    (`lxml` deprecation warning from Scrapling dependency).
  - `uv run ruff format --check .` -> 147 files already formatted.
  - `uv run ruff check .` -> All checks passed.
  - `uv run mypy` -> Success: no issues found in 70 source files.
  - `uv run alembic upgrade head` -> current SQLite migration head verified.
  - `uv run travelpayouts-smoke` -> expected local no-token result:
    `ok=false`, `code=credentials_missing`, `item_count=0`.
  - `uv run playwright install chromium` -> completed successfully.
  - `uv run python --version` -> Python 3.13.11.
  - `git diff --check` -> passed.
