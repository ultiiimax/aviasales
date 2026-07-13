# IMPLEMENTATION_STATUS

This file is maintained by coding agents. Mark a slice done only after implementation and verification.

## External Access

| Provider | Adapter | Credentials | Enabled | Background allowed | Merge allowed | Last verification |
|---|---|---:|---:|---:|---:|---|
| Fake | implemented offline demo | none | yes | yes | yes | n/a |
| Aviasales Search | implemented mobile API, live | `AVIASALES_SEARCH_SIGNATURE`, `AVIASALES_SEARCH_MARKER` | env flag | yes | yes | 2026-07-13 exact live MOW–LED smoke: 50 offers |
| SearXNG | implemented URL discovery | self-hosted optional | env flag | no, user action | candidate only | 2026-06-29 |
| Crawl4AI | implemented markdown extraction | self-hosted optional | env flag | no, user action | candidate only | 2026-06-29 |
| Deal discovery | implemented orchestrator | local components | component flags | no, user action | candidate only | 2026-06-29 |
| Telegram Bot API | implemented webhook/outbox transport | bot token | env flag | delivery worker only | n/a | 2026-06-29 |
| Skyscanner Indicative | contract only | none | no | no | no | 2026-06-23 |
| Skyscanner Live | contract only | none | no | no | no | 2026-06-23 |
| Duffel | contract only | none | no | no | no | 2026-06-23 |

## Current Slice: Local v1 Release

- Goal: ship a reliable single-machine v1 without rebuilding the project around
  `MEGA_PROMPT.md`.
- Design: `docs/superpowers/specs/2026-07-13-local-v1-release-design.md`.
- Execution plan: `docs/superpowers/plans/2026-07-13-local-v1-release.md`.
- Progress:
  - [x] Remove wall-clock expiry from worker tests.
  - [x] Centralize SQLite safety settings, concurrency coverage and `/readyz`.
  - [x] Add safe local `.env` initialization and secure auth defaults.
  - [x] Stabilize Aviasales failures, partial success and exact live smoke.
  - [x] Repair Russian web UI encoding.
  - [x] Make browser runtime/bootstrap and local E2E explicit.
  - [ ] Add release-check and pre-v1 upgrade tooling.
  - [ ] Package Compose/CI/release artifacts.
  - [ ] Finish documentation and full release gate.

## Previous Slice: Aviasales Mobile API Hard Cut

- Goal: make Aviasales mobile API the active primary fare source and remove the old cached provider path from active code, API/UI, scripts, env, README and tests.
- Result: implemented.

## Completed

1. Provider registry now registers `ProviderPolicy.aviasales_search_live(...)`.
2. Search provider is `implemented`, `live`, `mergeable`, and `background_requests_allowed=true`.
3. Worker provider factory wires `AviasalesSearchAdapter`; fake remains offline fallback.
4. Search API can return live Aviasales offers when enabled.
5. Offer model/API exposes `seller_name`, `segments[]`, baggage and booking-action availability.
6. Search responses return signed short-lived `booking_action_token`, never raw provider refs or purchase URLs.
7. `POST /api/v1/booking-actions/resolve` resolves purchase URL only from a valid token.
8. Added typed endpoints for suggest, hot offers, calendar and GraphQL main page blocks.
9. Date matrix uses mobile calendar/explore pricing overlay.
10. Removed the old radar endpoint and web controls.
11. Removed old env keys, Makefile target, compose wiring and source smoke path.
12. Source contracts and price source catalog now expose `aviasales_search`.
13. Unit tests cover factory/registry, scheduler policy, search service, booking token signing/expiry/tamper rejection, typed client operations, mapper seller/segments/baggage/ref and API resolve flow.

## Verification

Completed in this slice:

```text
uv run pytest tests/unit/providers/aviasales_search -q -> 27 passed
uv run pytest --disable-warnings -q -> 466 passed, 2 warnings
uv run pytest tests/integration -q --disable-warnings -> 1 passed
uv run pytest tests/unit/policy -q -> 3 passed
uv run ruff format --check . -> 237 files already formatted
uv run ruff check . -> all checks passed
uv run mypy -> no issues in 99 source files
uv run alembic upgrade head -> ok
uv run flight-hunter-security-scan -> ok, 0 findings
uv run flight-hunter-source-smoke --source aviasales_search -> ok with local dummy env, summary-only
uv run flight-hunter-browser-smoke -> ok
docker compose config -> ok
docker compose --profile worker config -> ok
rg removed-provider literals across active files -> no matches
```

Notes: `make` is not installed in the local PowerShell environment used for this
handoff, so the equivalent `uv`/`docker compose` commands above were run directly.
