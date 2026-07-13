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

## Current Slice: Agent Route Orchestrator

- Goal: turn the plan-only assistant into an approval-gated, durable,
  provider-backed route-search agent for arbitrary airport/city/country/region/
  anywhere requests and all supported flight trip shapes.
- Design:
  `docs/superpowers/specs/2026-07-13-agent-route-orchestrator-design.md`.
- Execution plan:
  `docs/superpowers/plans/2026-07-13-agent-route-orchestrator.md`.
- Progress:
  - [x] Add provider-neutral intent, evidence and plan contracts.
  - [ ] Freeze generic geographic scopes and estimate bounded provider work.
  - [ ] Persist immutable revisions, approvals, runs and operation ledger.
  - [ ] Expose the plan lifecycle and approval-gated web flow.
  - [ ] Execute resumable Aviasales calendar/exact work in the worker.
  - [ ] Compose and rank split, self-transfer, open-jaw and multi-city routes.
  - [ ] Isolate hidden-city research behind a second acknowledgement.
  - [ ] Add evidence-gated buy timing, anomaly and currency analysis.
  - [ ] Pass browser, recovery, migration, security and release gates.

Implementation status on 2026-07-13: the user-approved design and reviewed
implementation plan are complete. Production implementation has started with
the verified provider-neutral intent, plan and evidence contracts; remaining
orchestrator slices are pending.

## Previous Slice: Local v1 Release

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
  - [x] Add release-check and pre-v1 upgrade tooling.
  - [x] Package Compose/CI/release artifacts.
  - [x] Finish documentation and full release gate.

Packaging verification on 2026-07-13: version `1.0.0`, secure loopback Compose
configuration and Linux/Windows/browser/image CI contracts pass locally. Docker
image execution remains unverified on this machine because Docker Desktop's Linux
engine pipe is unavailable; the release gate reports `docker_unavailable` instead
of treating it as success.

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

## Local v1 Verification — 2026-07-13

Fresh release evidence:

```text
uv run flight-hunter-release-check --include-browser
  tests             -> passed: 513 passed, 7 deselected, 4 warnings
  format            -> passed: 254 files already formatted
  lint              -> passed
  types             -> passed: 104 source files
  migrations        -> passed: 2 tests
  upgrade_migrations-> passed: 1 pre-v1 data-preservation test
  security          -> passed: 0 findings
  compose           -> passed: secure config --quiet
  health            -> passed: 3 checks
  browser           -> passed: Chromium smoke + 7 E2E

sanitized Aviasales contract smoke -> ok, 1 item
sanitized exact MOW-LED smoke       -> ok, 50 offers, aviasales_search/live
docker image build                 -> not run: docker_unavailable
```

The Docker Desktop Linux engine pipe was unavailable on this machine. The gate
reported `docker_unavailable`; no successful local image build is claimed. The
Dockerfile/Compose contracts and CI image job exist, while the fully verified
runtime path for this release is direct local Python/SQLite on loopback.
