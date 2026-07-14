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
  - [x] Freeze generic geographic scopes with commercial provenance.
  - [x] Parse typed intents, freeze provider capabilities and estimate bounded plans
    (accepted by independent review at `655a069`).
  - [x] Persist immutable revisions, approvals and runs.
  - [x] Expose the bearer-authenticated plan lifecycle API (Task 5 accepted by
    independent review at `2bf8dbe`, with no Critical/Important/Minor findings).
  - [ ] Make free text, all seven presets and the approval-gated web plan card
    use the same builder without provider calls before explicit execution
    (implementation complete on 2026-07-14; pending independent review).
  - [ ] Persist the durable operation ledger.
  - [ ] Execute resumable Aviasales calendar/exact work in the worker.
  - [ ] Compose and rank split, self-transfer, open-jaw and multi-city routes.
  - [ ] Isolate hidden-city research behind a second acknowledgement.
  - [ ] Add evidence-gated buy timing, anomaly and currency analysis.
  - [ ] Pass browser, recovery, migration, security and release gates.

Task 2 slice plan/result: add a forward-only airport provenance migration,
package checksummed ISO/CLDR country and region taxonomies, freeze deterministic
airport-catalog snapshots, then resolve airport/city/country/region/anywhere
scopes behind an application repository protocol. Completed in that order with
test-first RED/GREEN evidence.

Task 2 verification on 2026-07-13: 14 focused scope/import/repository/migration
tests, 2 migration baseline/pre-v1 upgrade tests and 10 geo/airport regressions
pass. Focused mypy and global Ruff format/check pass. The built wheel contains
both versioned taxonomy JSON resources.

Task 3 slice plan/result: add deterministic RU/EN intent parsing with a typed,
field-limited optional model overlay; publish the verified Aviasales tri-state
capability/cost snapshot; estimate logical operations and every worst-case HTTP
attempt before approval; add positive bounded agent settings and keep the legacy
multi-city boolean conservative. Completed test-first without provider calls.

Task 3 verification on 2026-07-14: 53 focused parser/capability/planning/
registry/config/env tests, 23 Task 1/2/preset regressions and all 593 unit tests
pass. Focused mypy and global Ruff format/check pass. Rolling 90-day bounds use
the injected plan-builder clock; quick 60, full 240 and absolute 1,000 boundaries
are covered.

Task 3 review fix cycle on 2026-07-14 established that planning is async and
cannot reach approval until
every finite leg scope is frozen from the local airport catalog or an `anywhere`
leg has a bounded immutable discovery rule. FULL estimates use the untruncated
frozen Cartesian surface; overlay/date dependencies fail as typed
clarifications. The fresh focused suite has 88 tests, Task 1/2 regressions have
25 tests, all 617 unit tests pass, mypy checks 110 source files, and global Ruff
format/check pass.

Task 3 final budget-accounting fix on 2026-07-14: broad QUICK surfaces are no
longer estimate-clamped after their executable scopes/rules are frozen. Exact
one-origin `anywhere` remains 40 calendar + 20 exact and awaits approval;
rolling-90 `anywhere` is honestly 180 + 20 and finite LED-to-France is 360 +
360, so both remain drafts with `quick_budget_too_large`, immutable actual
counts, and narrowing/full actions. Typed budget errors carry stable
reason/actual/limit fields; the builder handles only QUICK-limit reasons, while
the absolute ceiling still raises in QUICK and FULL. FULL budget revision
behavior is unchanged. Final gates: 20 planning tests, 91 focused Task 3/scope
tests and 30 Task 1/2 domain/scope regressions pass; mypy checks 110 source files
and global Ruff checks 267 files. The immediately preceding full-unit gate had
619 passes; the final typed-reason follow-up was limited to the focused gates by
coordinator direction. Independent final review accepted Task 3 with no
Critical, Important or Minor findings at `655a069`.

Task 5 final boundary fix on 2026-07-14 restricts stable invalid-input mapping
to deterministic user input, leaves internal overlay/builder/repository errors
visible to the process boundary after rollback, and closes every service-owned
read transaction on success or failure. Final gates: 47 focused lifecycle/API/
auth tests, 106 parser/repository regressions, all 736 unit tests and 4 separate
integration tests pass; global format, Ruff and mypy are clean. Independent
review additionally ran 146 targeted tests and accepted the complete
`7775f50..2bf8dbe` Task 5 range with no Critical, Important or Minor findings.

Task 6 implementation on 2026-07-14 routes free text and all seven presets
through the durable lifecycle and renders the same sanitized, approval-gated
plan/run card. The rolling-90 QUICK case preserves the accepted Task 3 budget
invariant: actual counts remain visible and execution stays disabled above the
60-operation limit. Focused Task 6 tests pass 33/33, Task 3/5 regressions pass
92/92, all 747 unit tests and 4 integration tests pass, mypy checks all 114
source files,
and global Ruff format/check pass across 276 files. No provider call occurs
before explicit execute. The implementation remains pending independent review.

Task 4 hardening is complete and accepted by independent review. Forward-only
migration 0023 and matching Core metadata persist household-scoped immutable
plan revisions, approval snapshots, and runs without raw prompts. The rejected
review findings are covered by immutable canonical approval evidence, UTC-only
writes and reads, exact PostgreSQL/SQLite integrity classification, the reviewed
run state machine, complete approval estimates, caller-owned rollback proofs,
same-key concurrency tests, atomic chronology guards, and recursively immutable
approval evidence. The final cancellation-chronology follow-up rejects a
`running -> cancel_requested` transition before `started_at` in both the
repository CAS and the matching Core/migration check while accepting equality.
SQLite successor/execute writers acquire a local
`BEGIN IMMEDIATE` only when no physical caller transaction exists. An already
open SQLite savepoint is rejected before mutation with the stable
`agent_sqlite_nested_transaction_unsupported` error; ordinary outer transactions
and autobegin retain caller-owned rollback. PostgreSQL does not run this SQLite
boundary SQL. No repository commits, rolls back, or retries the caller's
transaction. Fresh focused, migration, persistence, mypy, Ruff, unit, and
integration gates pass; the localized cancellation follow-up adds an 81-test
focused green gate. Final independent review accepted Task 4 at `253447e` with
no Critical, Important or Minor findings.

Implementation status on 2026-07-13: the user-approved design and reviewed
implementation plan are complete. Production implementation now includes the
verified provider-neutral contracts and frozen generic geographic scopes;
remaining orchestrator slices are pending.

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
