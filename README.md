# Flight Hunter

Local self-hosted flight search/watch project with a web UI, Telegram plumbing and worker jobs.

Primary fare source: Aviasales mobile API, used directly through:

- `tickets-api.aviasales.ru` for live search, prices, gates and lazy purchase links;
- `suggest.aviasales.ru` for city/airport suggest;
- `explore-api.aviasales.ru` for hot offers and calendar prices;
- `ariadne.aviasales.ru` for typed GraphQL feed blocks.

`FakeFlightProvider` remains as the offline demo fallback when no mobile API credentials are set.

## Quick Start

```powershell
make bootstrap
uv run alembic upgrade head
uv run uvicorn flight_hunter.api.app:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

For Docker:

```powershell
make compose-up
make compose-worker-up
make compose-down
```

## Aviasales Mobile API

Set these in `.env`:

```env
APP_SECRET_KEY=replace-with-strong-random-secret
AVIASALES_SEARCH_ENABLED=true
AVIASALES_SEARCH_SIGNATURE=856890a7-59b2-4043-9bc7-e478bb4e6405
AVIASALES_SEARCH_MARKER=mobile_app.replace-with-md5-of-android-id
AVIASALES_SEARCH_INTERNAL_RPM=20
```

Live smoke, summary only:

```powershell
uv run flight-hunter-source-smoke --source aviasales_search
```

Smoke output contains status/code/counts only. It does not print signatures, markers, raw payloads or purchase URLs.

## Public API

- `POST /api/v1/searches` returns mergeable live offers from `aviasales_search` when enabled.
- `POST /api/v1/booking-actions/resolve` resolves a purchase URL only after an explicit tokenized booking action.
- `GET /api/v1/aviasales/suggest`
- `GET /api/v1/aviasales/hot-offers`
- `GET /api/v1/aviasales/calendar`
- `GET /api/v1/aviasales/graphql/main-page-blocks`
- `POST /api/v1/searches/date-matrix` uses the mobile calendar/explore pricing overlay when route fields and provider credentials are present.
- `GET /api/v1/source-contracts`, `/api/v1/providers`, admin health endpoints expose readiness without leaking secrets.

Offer responses include:

- `seller_name`
- `segments[]`
- `baggage_summary`
- `booking_action_available`
- `booking_action_token`

Raw provider refs and purchase URLs are not exposed in search responses, logs or Telegram callback data. Purchase URLs appear only in the direct response of `POST /api/v1/booking-actions/resolve`.

## Useful Commands

```powershell
make test
make test-unit
make test-integration
make lint
make typecheck
make migrate
make provider-contracts
make security
make source-smoke SOURCE=aviasales_search
make browser-smoke
make backup
make restore BACKUP=...
```

Worker:

```powershell
uv run flight-hunter-worker --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
uv run flight-hunter-worker --role watch --loop
uv run flight-hunter-worker --role telegram --loop
uv run flight-hunter-run-personal-observation --job-id JOB_UUID --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html
```

## Current Verification

Last checked in this slice:

```text
uv run pytest tests/unit/providers/aviasales_search -q -> 27 passed
uv run pytest --disable-warnings -q -> 466 passed, 2 warnings
uv run ruff format --check . -> ok
uv run ruff check . -> ok
uv run mypy -> ok
uv run alembic upgrade head -> ok
uv run flight-hunter-security-scan -> ok, 0 findings
uv run flight-hunter-source-smoke --source aviasales_search -> ok with local dummy env, summary-only
uv run flight-hunter-browser-smoke -> ok
docker compose config -> ok
docker compose --profile worker config -> ok
```

Run the full gate before shipping a larger slice:

```powershell
uv run pytest tests/unit --disable-warnings -q
uv run pytest tests/integration -q --disable-warnings
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run alembic upgrade head
uv run flight-hunter-security-scan
```

## Docs

- `AGENTS.md` - agent rules.
- `docs/ARCHITECTURE.md` - architecture boundaries.
- `docs/provider-contracts/aviasales-search.md` - Aviasales mobile API contract notes.
- `docs/START_HERE_RU.md` - short Russian onboarding.
- `IMPLEMENTATION_STATUS.md` - current implementation status.
