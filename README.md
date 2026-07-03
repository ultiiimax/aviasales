# Flight Hunter

Семейный self-hosted поиск и отслеживание авиабилетов.

Главное: проект не обещает “живые” цены там, где источник даёт только кэш. Он честно показывает источник, свежесть и ограничения.

## Начать отсюда

Если вы не разработчик или просто хотите без лишней магии, откройте:

**[docs/START_HERE_RU.md](docs/START_HERE_RU.md)**

Там коротко:

- что уже можно запустить;
- какие команды копировать;
- что мне нужно от вас;
- где взять Telegram bot token и Travelpayouts token;
- что можно не трогать прямо сейчас.

## Что уже работает

Сейчас реализована backend-demo основа и простой web-экран без внешних ключей:

- web-страница `GET /` с chat-first агентом, формой поиска, источниками и результатами;
- installable PWA shell: `/manifest.webmanifest`, `/pwa-icon.svg` and `/service-worker.js`
  cache only the app shell and explicitly bypass `/api/` so prices/observations are never shown
  from offline cache as fresh data;
- provider policy guard;
- SearchIntent/API model with explicit passenger mix and trip type validation;
- demo search через `FakeFlightProvider`;
- Aviasales Data adapter, включаемый через `.env`, с cached `prices_for_dates`,
  `search_by_price_range`, `grouped_prices`, `get_latest_prices`, `week-matrix`, `month-matrix`
  и `nearest-places-matrix`;
- список providers и причины, почему реальные sources выключены;
- source contract catalog `GET /api/v1/source-contracts`: показывает readiness каждого источника
  (`implemented`, `policy_skeleton`, `contract_only`), env flags, adapter module, policy
  invariants и blocked reasons без раскрытия secrets;
- airport autocomplete, city-name search и nearby airports: demo-набор работает сразу,
  SQLite-compatible OurAirports import доступен через локальный CSV;
- flexible date matrix planning, with optional Aviasales Data `week-matrix` cached price overlay
  when route fields and credentials are present;
- cached radar API for Aviasales Data `search_by_price_range`, `grouped_prices`,
  `get_latest_prices`, `month-matrix` and `nearest-places-matrix`, kept separate from ranked
  exact-date search and labelled as cached confirmation-required data;
- cached radar also exposes explicit `popular_directions` hints backed by
  `/aviasales/v3/get_popular_directions`; these remain cached and outside exact-date ranking;
- cached radar exposes explicit `special_offers` hints backed by
  `/aviasales/v3/get_special_offers`; these are abnormal-price cached hints, not guaranteed
  availability or booking links;
- authenticated cached radar requests can explicitly persist Aviasales Data cached rows as
  low-confidence manual-verification `DealCandidate` seeds for the same household/user/search,
  without exposing provider signed links or adding them to priced-offer ranking;
- Aviasales Data cached prices are exposed with `price_basis=provider_single_adult_ticket`; the
  adapter does not multiply cached provider prices for multi-passenger totals and returns an
  explicit unsupported-passenger denial before provider lookup for `passengers != 1`;
- web workbench exposes a separate Cached radar action and result section for `price_range`,
  `grouped_prices`, `latest_prices`, `month_matrix`, `nearest_places_matrix` and
  `popular_directions` / `special_offers` cached hints;
- ранжирование mergeable результатов с видимыми caveats;
- alert hysteresis/dedupe logic;
- Telegram webhook security foundation: secret header and durable `update_id` dedupe;
- Telegram linking/outbox foundation: web API issues one-time link codes, `/link CODE` is consumed
  through the secret-protected webhook, price-drop alerts enqueue durable notification rows, and
  worker delivery claims rows before sending and respects quiet hours and retry state;
- Telegram watch command slice: linked users can send `/watches`; the webhook resolves ownership by
  Telegram user id and enqueues a durable household-scoped watch list reply without provider calls;
- Telegram watch callbacks: `/watches` replies include Pause/Resume/Check inline button payloads;
  callback handling checks linked ownership plus watch version before mutating local watch state or
  queuing a manual personal browser observation job. The Check callback issues a one-time
  `telegram_callback` grant and creates a durable job; it does not run browser automation inside the
  webhook. Callback acknowledgement rows are delivered with Telegram `answerCallbackQuery` and do
  not store raw callback data;
- первый слой базы: Alembic migrations, household-isolated watches, price history и alert dedupe;
- Watch API: create/list/detail, versioned PATCH, pause/resume, archive/soft-delete and append-only
  history with household isolation through temporary headers;
- web watch control center: the primary workbench can create a watch from the current route, list
  household watches, pause/resume, inspect append-only history and archive/delete with
  `expected_version` without triggering provider/browser work inside the page;
- invitation/session auth foundation: bootstrap invitation creation is gated by
  `AUTH_BOOTSTRAP_TOKEN`, accepted invitations create bearer sessions stored hash-only in the DB,
  and core household/user APIs accept `Authorization: Bearer ...`; temporary
  `X-Flight-Hunter-*` demo headers remain only while `AUTH_ALLOW_LEGACY_HEADERS=true`, and the web
  UI can accept an invitation code and reuse the bearer session for auth-aware actions;
- admin provider/source health endpoints без раскрытия secrets и без live checks на GET; the web
  workbench also renders a read-only Health panel with provider readiness and source event status;
- household admin audit endpoint and web Audit panel: authenticated households can read their own
  newest-first lifecycle audit events through paged `GET /api/v1/admin/audit-events`; events
  remain household-scoped and append-only;
- privacy export endpoint: `POST /api/v1/privacy/export` returns a bounded JSON archive with
  retained household watches/audit events plus the requesting user's manual confirmations,
  browser-observed offers and deal candidates; it includes archived/deleted watch metadata, reports
  per-collection truncation and omits provider secrets, raw payloads, `raw_ref`, idempotency keys,
  session tokens, Telegram payload JSON and worker queue payloads;
- account deactivation endpoint: `DELETE /api/v1/account` requires a bearer session, rejects
  legacy demo headers, revokes current user sessions/membership/Telegram link, soft-deletes owned
  active watches and records append-only audit events while retaining audit, price history and
  observation records;
- agent chat API: typed turn endpoint, airport choices, safe action cards, watch creation only
  after explicit "следи/мониторь/уведомляй" wording, and audit without raw chat storage;
- optional Codex CLI intent bridge skeleton: выключен по умолчанию, sandbox/read-only/schema-gated,
  не является источником цен, рейсов или provider policy;
- optional OpenAI Responses agent backend: выключен по умолчанию, включается только через
  `AGENT_OPENAI_ENABLED=true` + `OPENAI_API_KEY`, возвращает typed intent draft/schema output,
  не получает provider secrets и не выполняет live/browser calls;
- agent presets API: безопасные сценарии "когда покупать", даты +/- 3 дня,
  аэропорты рядом, hidden-city, split ticket, error fare и валюта/страна сайта;
- live refresh gate: будущие live-проверки не чаще одного раза в 10 минут и только
  после явного действия пользователя;
- live observation control plane: каталог browser sources, одноразовые grants,
  idempotent create endpoint и fake worker без внешних live-вызовов;
- durable live observation storage and retention cleanup for short-lived grants/results/idempotency;
- price source catalog: RUB-first источники без брони в приложении, с покупкой
  через внешний click-out;
- carrier confirmation links now include Aeroflot, Pobeda, S7, Ural Airlines, Nordwind,
  Red Wings, Smartavia, Azimuth, Utair, Rossiya, Turkish Airlines, Air Serbia, Pegasus,
  Uzbekistan Airways, Emirates, Qatar Airways, Etihad and flydubai; all are manual external
  confirmation links, not known-price offers;
- search response bundle: `priced_offers`, `external_links`, `browser_observed_offers`,
  `deal_candidates` и `freshness_summary` разделяют кэшированные цены, внешние ссылки для
  проверки и будущие наблюдения из браузера;
- priced offer responses include a deterministic `risk` object with `level`, `flags` and
  `explanations` for cached/stale freshness, live-confirmation requirements, unknown baggage and
  provider single-adult price-basis assumptions; this does not generate split-ticket or
  self-transfer candidates;
- manual price confirmation ledger: authenticated users can append scoped confirmations for cached
  offers, external links, browser observations, deal candidates or carrier links through
  `POST /api/v1/manual-price-confirmations` and read their own history through
  `GET /api/v1/manual-price-confirmations`; these records never overwrite provider facts;
- web UI exposes manual confirmation actions on cached prices, external links, browser observations
  and deal candidates, then shows the recent scoped confirmation history separately from provider
  prices;
- web UI показывает отдельные секции "Цены из кэша", "Ссылки для проверки" и
  "Свежие наблюдения из браузера", не смешивая внешние ссылки с найденными билетами;
- web UI умеет вручную поставить Personal Browser Observer job в очередь и запустить deal
  discovery, показывая disabled/error states без скрытых browser/live calls;
- fixture-based browser HTML extractor: sanitized DOM fixtures can be parsed into
  `BrowserObservedOffer` with confidence/warnings, without network calls or stealth scraping;
- Tutu source-specific observer parser: sanitized Tutu-like ticket fixtures are parsed without
  generic fixture markers and report `selector_drift` / `source_challenge` diagnostics;
- Personal Browser Observer now uses a parser pipeline: source-specific DOM parser, optional
  Scrapling parser, generic offer-card parser, rejected visible-text price hints and optional
  injected Crawl4AI markdown hint diagnostics. Only structured offer-card matches become
  `browser_observed` offers;
- Personal Browser Observer CLI: `flight-hunter-observe` can run a user-action gated local
  Playwright observer or parse a fixture, normalize visible offer cards, and optionally persist
  short-lived `browser_observed` results scoped by household/user/search;
- Personal Browser Observer runtime keeps persistent browser profiles and optional diagnostic
  artifacts in separate roots (`PERSONAL_OBSERVER_PROFILE_ROOT` and
  `PERSONAL_OBSERVER_ARTIFACT_ROOT`), validates redirect hosts by hostname, protects each source
  profile with a local lock/stale-lock policy and closes Playwright contexts on navigation
  failures; navigation timeout, optional ready selector/network-idle wait and visible-mode manual
  checkpoint are env-tunable; when diagnostic artifacts are enabled it also writes a small runtime
  JSON manifest with redacted final URL, snapshot hashes and artifact paths, but no raw DOM,
  cookies, query strings or page title text;
- local browser runtime smoke `flight-hunter-browser-smoke` verifies Playwright Chromium with a
  headless persistent context and local HTML only, without visiting live travel sites;
- fixture-only parser CLI `flight-hunter-parse-fixture` and `make parse-fixture` parse sanitized
  observer HTML fixtures through the production parser pipeline without live browser work or
  persistence, with optional explicit `--crawl4ai-markdown-fixture` diagnostic input;
- DOM sanitizer CLI: `flight-hunter-sanitize-html` and `make sanitize-html` turn local raw browser
  DOM captures into diagnostic fixtures by removing active code, secret-like attributes, query
  strings and obvious PII before anything is committed or shared;
- durable personal observation queue: `/api/v1/personal-observations/grants`,
  `/api/v1/personal-observations`, `/api/v1/personal-observations/{id}/confirm`,
  `/api/v1/personal-observations/{id}/mark-stale`,
  `/api/v1/personal-observations/{id}/resume` and
  `/api/v1/personal-observations/{id}/abort`;
  `flight-hunter-run-personal-observation` enqueue/execute user-action browser jobs and append
  scoped manual confirmation/stale ledger rows without running browser work inside API requests;
  expired direct-run or already-claimed worker jobs are marked `expired` before browser launch or
  before result persistence and never persist offers;
- personal observation status now exposes operator-visible runtime phases such as
  `opening_browser`, `waiting_for_user`, `capturing_dom` and `parsing`; during
  `waiting_for_user`, the authenticated household/user can request durable resume or abort, and the
  worker treats phase jobs as active leases for concurrency and stale recovery;
- browser source parser test API: `POST /api/v1/browser-sources/{source_id}/test-parser` accepts
  sanitized HTML from an authenticated operator, returns structured parser diagnostics and snapshot
  hashes, and does not echo or persist raw HTML;
- browser source catalog now exposes personal observer sources such as Tutu, Yandex Travel and
  OneTwoTrip from local config; they remain user-action-only and never background-scheduler
  sources;
- local worker command: `flight-hunter-worker` processes already-queued personal observation jobs
  without creating background browser discovery; it supports one-pass and polling `--loop` modes
  with durable attempts, conditional DB claim leases, configured browser concurrency/min-gap
  guards, retry scheduling, role-scoped lanes (`--role browser`, `--role watch`, `--role deal`,
  `--role telegram`, `--role maintenance`), expired live-observation cleanup, source health
  events, retryable local Playwright runtime-unavailable handling and SIGINT/SIGTERM-aware
  graceful shutdown between worker passes;
- worker heartbeat read model: `flight-hunter-worker` upserts `worker_heartbeats` before and after
  passes, and `GET /api/v1/admin/workers/health` plus the web Health panel show durable worker
  status/effective stale state, active job kind/id and per-lane counters without scraping logs or
  running live provider checks;
- worker supervisor healthcheck: `flight-hunter-worker-healthcheck` reads durable heartbeat/queue
  state for a role lane and exits non-zero for missing, stale, failed or critical-alert workers
  without making provider calls;
- worker drain control: authenticated operators can pause/resume new worker claims through
  `PATCH /api/v1/admin/workers/control` or the web Health panel; queued work is not deleted or
  failed, and maintenance cleanup can still run while drained;
- worker queue health dashboard: the same admin health response and web Health panel show read-only
  browser/watch/deal/Telegram backlog, delayed retry, stale lock and expired/deadline aggregates;
- worker health alert snapshot: `GET /api/v1/admin/workers/health` and the web Health panel expose
  derived `worker_stale`, `queue_stale_lock`, `queue_deadline_risk` and `queue_backlog` alerts for
  external supervisors without scraping logs;
- structured observability logs: the `flight_hunter.observability` logger emits compact JSON
  events for `search_started`, Aviasales Data `provider_call`, personal browser observation start,
  parser extraction results and Telegram `alert_sent` without tokens, raw payloads, full URLs,
  Telegram chat ids or message text;
- application Prometheus metrics: `GET /api/v1/metrics` exposes the plan-required
  `flight_hunter_provider_requests_total`, `flight_hunter_provider_errors_total`,
  `flight_hunter_browser_observation_jobs_total`, `flight_hunter_parser_offers_extracted_total`,
  `flight_hunter_search_duration_seconds` and `flight_hunter_alerts_sent_total` from the same safe
  events, using only low-cardinality labels;
- durable watch scan worker: `flight-hunter-worker` also enqueues due `watch_scan_jobs`, calls only
  scheduler-approved cached/background providers, persists append-only price snapshots, records
  source health events, claims jobs before execution and suppresses duplicate price-drop alerts on
  retry;
- no-credentials integration acceptance harness covers invitation auth, demo search, watch scan,
  price history, Telegram link/outbox alert dedupe and household isolation on a file-backed SQLite
  stack;
- optional scraping/crawler dependency groups: Playwright/Scrapling are available for the personal
  observer path, and Crawl4AI is installed behind config for later deal-page extraction work;
- durable deal discovery foundation: SearXNG JSON results and Crawl4AI markdown fixtures can be
  converted into manual-verification `DealCandidate` hints through `/api/v1/deals/discover`,
  persisted by household/user/search with TTL, and returned in search responses without being
  ranked as confirmed prices; deal-page URLs pass a public-http SSRF guard before markdown fetches,
  can be restricted further with `DEAL_DISCOVERY_ALLOWED_HOSTS`, duplicate tracking URLs are
  deduped before Crawl4AI fetches, a bounded multi-query SearXNG
  strategy tries route sale/promo/error-fare variants before giving up, source health events are
  recorded on success/failure, SearXNG transport/rate-limit/invalid-JSON failures are typed
  without echoing raw payload text, individual Crawl4AI page-fetch failures do not discard
  candidates extracted from other pages, `GET /api/v1/source-contracts` and paged
  `GET /api/v1/admin/sources/health` expose SearXNG/Crawl4AI/deal discovery as disabled-by-default
  candidate-only sources, candidates carry explicit `expires_at` lifecycle data in API/UI and the
  worker cleanup pass removes expired candidates, `/api/v1/deals/discovery-jobs` provides a
  durable authenticated enqueue/status path with scoped idempotency, `flight-hunter-worker` claims
  those queued jobs with retries/source health events, SearXNG title/content remain URL-discovery
  metadata only while price/route/date confidence evidence comes from page markdown, and
  `flight-hunter-source-smoke` checks optional source readiness with summary-only output;
- Crawl4AI markdown extraction supports explicit `CRAWL4AI_MODE=library` or self-hosted
  `CRAWL4AI_MODE=server` via `POST /md`; both remain disabled unless `CRAWL4AI_ENABLED=true`, and
  extracted markdown is treated as untrusted deal-page text rather than price truth. Personal
  Browser Observer can use the same client for diagnostic markdown hints only after a visible
  user-action observation has captured a final URL; local fixture parsing remains network-free;
- scraping observer policy: рискованный future-режим выключен по умолчанию и
  запрещает CAPTCHA/stealth/proxy/cookie обходы;
- Aviasales Search API и MCP policy skeletons: выключены по умолчанию, требуют
  user-action policy и typed validation перед будущими интеграциями;
- unit tests, lint и typecheck.

## Быстрый запуск demo API

Нужно только `uv`.

```powershell
uv sync --group dev
uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8000
```

Для локального Personal Browser Observer и будущих crawler-срезов установите опциональные группы и
браузер Playwright:

```powershell
uv sync --group dev --group scraping --group crawler
uv run playwright install chromium
uv run flight-hunter-browser-smoke
```

Откройте:

- http://127.0.0.1:8000/
- http://127.0.0.1:8000/healthz
- http://127.0.0.1:8000/docs

## Проверка проекта

```powershell
uv run pytest tests/unit
uv run pytest tests/integration
uv run ruff format --check .
uv run ruff check .
uv run mypy
```

Единый интерфейс команд:

```powershell
make bootstrap
make test
make lint
make typecheck
make migrate
make seed-demo
make security
make source-smoke SOURCE=searxng
make browser-smoke
```

Локальный Docker Compose stack:

```powershell
make compose-up
make compose-worker-up
make compose-deals-config
make compose-deals-up
make compose-down
```

`compose-up` поднимает API с SQLite volume. `compose-worker-up` добавляет worker profile.
`compose-deals-up` adds the optional internal-only SearXNG + Crawl4AI profile for local deal
discovery experiments, using pinned image tags from `.env.example`. In this compose profile,
`CRAWL4AI_MODE` defaults to `server` so the API/worker use the internal Crawl4AI service.
`compose-deals-config` renders the effective compose file for deployment review without starting
containers.

Применить текущие миграции к локальной demo SQLite базе:

```powershell
uv run alembic upgrade head
```

Проверить Travelpayouts/Aviasales Data token одним безопасным cached-запросом:

```powershell
uv run travelpayouts-smoke
```

Команда печатает только summary, без token, booking links и raw payload.

Проверить optional discovery sources без raw payload:

```powershell
uv run flight-hunter-source-smoke --source aviasales_data
uv run flight-hunter-source-smoke --source searxng
uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/
```

Без включённых env flags `searxng` и `crawl4ai` честно вернут disabled-состояние.

Сделать backup/restore локальной demo SQLite базы:

```powershell
uv run flight-hunter-backup
uv run flight-hunter-backup-verify .\backups\ИМЯ_BACKUP.db
uv run flight-hunter-restore .\backups\ИМЯ_BACKUP.db
uv run flight-hunter-cleanup-live-observations --dry-run
```

Backup writes a `.manifest.json` sidecar with SHA-256 and size. `flight-hunter-restore` verifies
the manifest first when it exists and refuses corrupted backups.

Импортировать локальный OurAirports `airports.csv` в demo SQLite:

```powershell
uv run flight-hunter-import-airports --airports-csv .\data\airports.csv
```

Проверить parser/observer на sanitized fixture без сети:

```powershell
uv run flight-hunter-observe --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20 --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
uv run flight-hunter-parse-fixture tests/fixtures/browser/tutu/search_result_source_specific.html --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20
uv run flight-hunter-parse-fixture tests/fixtures/browser/tutu/search_result_source_specific.html --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20 --crawl4ai-markdown-fixture tests/fixtures/crawl4ai/browser_observer_markdown_hint.md
```

Sanitize a local raw browser DOM capture before keeping it as a diagnostic fixture:

```powershell
uv run flight-hunter-redact-url --url "https://example.com/path?token=SECRET"
uv run flight-hunter-sanitize-html --input .local/raw.html --output tests/fixtures/browser/tutu/minimal.html
```

Выполнить уже поставленный durable personal observation job:

```powershell
uv run flight-hunter-run-personal-observation --job-id JOB_UUID --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

Обработать queued browser jobs одним локальным worker pass:

```powershell
uv run flight-hunter-worker --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

The same worker pass also processes due watch scans when `WATCH_SCAN_ENABLED=true` and queued
deal-discovery jobs when SearXNG/Crawl4AI are enabled and a user has already enqueued a job. With
Travelpayouts credentials watch scans use Aviasales Data; without them they fall back to the
deterministic demo provider for local demo mode.
Stale `running`/`sending` worker leases are recovered before each pass; tune the window with
`--stale-lock-seconds`.

For supervised deployments, split lanes into separate processes while keeping the same DB-backed
claims and policy gates:

```powershell
uv run flight-hunter-worker --role browser --loop --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
uv run flight-hunter-worker --role watch --loop
uv run flight-hunter-worker --role deal --loop
uv run flight-hunter-worker --role telegram --loop
uv run flight-hunter-worker --role maintenance --loop
```

Multiple roles can be combined with repeatable `--role` or comma-separated `--roles`. The admin
worker health API and web Health panel show `current_job_kind`/`current_job_id` while a claimed item
is running. The same Health panel can pause new worker claims for a maintenance window and resume
them afterward; this does not stop an external worker process or delete queued work.
For Linux self-hosting, systemd templates live in `deploy/systemd/` and the install/upgrade steps
are documented in `docs/runbooks/systemd-worker-supervision.md`.

Запустить локальный polling worker loop:

```powershell
uv run flight-hunter-worker --loop --idle-sleep-seconds 5 --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

Последний проверенный результат:

```text
458 passed, 2 warnings (existing lxml deprecation and aiosqlite cleanup warnings)
integration tests passed: 1 passed
ruff format/check passed; 223 files already formatted
mypy passed for 94 source files
alembic upgrade head passed
flight-hunter-security-scan passed with finding_count=0
flight-hunter-browser-smoke passed with code=ok
git diff --check and src TODO/pass/NotImplementedError scan passed
docker compose --profile deal-discovery config passed
SearXNG typed transport/rate-limit/invalid-JSON errors covered by tests
deal discovery partial page success covered by tests
personal observation claimed expiry guard covered by tests
Personal Observer Playwright-unavailable retry covered by tests
Aviasales Data cached deal seeds covered by tests
Personal Observer Crawl4AI diagnostic bridge covered by tests
deal discovery compose server-mode default covered by tests
systemd worker supervision templates covered by tests
worker health alert snapshot covered by tests
personal observation expired direct-run guard covered by tests
Aviasales Data price-basis guard covered by tests
Aviasales Data contract hardening covered by tests
personal observation, watch scan, deal discovery and Telegram delivery worker paths covered by tests
deal discovery markdown-only evidence guard covered by tests
Personal Observer explicit Crawl4AI markdown input covered by tests
worker queue health dashboard covered by tests
worker role lanes and active job heartbeats covered by tests
worker drain control plane covered by tests
personal observer profile lock/stale-lock runtime covered by tests
Aviasales Data popular_directions cached radar covered by tests
Aviasales Data special_offers cached radar covered by tests
Browser Crawl4AI markdown hint hook covered by tests
travelpayouts-smoke returned credentials_missing without token
flight-hunter-source-smoke returned aviasales_data credentials_missing and searxng_disabled/crawl4ai_disabled without optional env flags
```

## Что пока не готово

Note: a local DB-backed worker now exists for queued browser jobs, cached watch scans and Telegram
notification delivery, with conditional claim leases, role lanes, active job heartbeats and durable
drain control, systemd templates, read-only worker health alerts and paged worker/admin health
windows. Remaining worker work is network-layer egress hardening;
Prometheus-style worker metrics are available at `GET /api/v1/admin/workers/metrics`.

Есть installable PWA shell без API-cache и stale-lock monitoring в Health panel, но пока нет полноценного offline/Next.js UI, production-grade worker supervisor и большинства live/bookable provider adapters.
Реализован первый реальный provider adapter: Aviasales Data API, с cached-семантикой и выключением по умолчанию.
Остальные источники теперь явно отражены в source contract catalog как `policy_skeleton` или
`contract_only`, а не замаскированы под рабочие интеграции.

`GET /api/v1/source-contracts` also exposes secret-free `egress_policy` metadata for each source.

Flight Hunter по умолчанию не делает скрытый массовый scraping и не использует CAPTCHA bypass,
stealth, fingerprint spoofing, rotating proxies, чужие cookies или login-required страницы.
Fetched deal URLs now reject localhost/internal hosts, private/link-local IP literals, IPv6 zone ids
and legacy IPv4 aliases before Crawl4AI/SearXNG-derived page fetches. Operators can additionally
set `DEAL_DISCOVERY_ALLOWED_HOSTS` to exact hosts or wildcard subdomains such as
`*.example.com`; broader network-layer egress controls remain future operations hardening.
Personal Browser Observer уже имеет локальный CLI/runtime для user-action сценария, отдельный
Playwright profile, fixture parsing, durable job API/worker CLI и persistence короткоживущих
browser observations. Deal discovery foundation уже есть как service/client/extractor/API/UI слой
with durable scoped candidate persistence, source smoke checks and an optional SearXNG/Crawl4AI
compose profile using pinned internal services and server-mode Crawl4AI. Worker has a DB-backed
polling loop with role lanes, active job heartbeats, systemd templates and alert snapshots, but
network-layer egress controls remain.

Live-цены не парсятся "втихую" со страниц агрегаторов. Для них нужен официальный
API/партнерский доступ, включенный provider adapter и пользовательское действие.
Если источник дает только cached данные, интерфейс обязан показывать cached/stale,
а не называть это live.
