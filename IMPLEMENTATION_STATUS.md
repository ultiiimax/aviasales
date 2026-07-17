# IMPLEMENTATION_STATUS

This file is maintained by coding agents. Mark a slice done only after implementation and verification.

## External Access

| Provider | Adapter | Credentials | Enabled | Background allowed | Merge allowed | Last verification |
|---|---|---:|---:|---:|---:|---|
| Fake | implemented offline demo | none | yes | yes | yes | n/a |
| Aviasales Search | implemented mobile API, live | `AVIASALES_SEARCH_SIGNATURE`, `AVIASALES_SEARCH_MARKER` | env flag | yes | yes | 2026-07-16 exact mapping/booking boundary reverified against sanitized capture; last live schema checks remain 2026-07-14 |
| SearXNG | implemented URL discovery | self-hosted optional | env flag | no, user action | candidate only | 2026-06-29 |
| Crawl4AI | implemented markdown extraction | self-hosted optional | env flag | no, user action | candidate only | 2026-06-29 |
| Deal discovery | implemented orchestrator | local components | component flags | no, user action | candidate only | 2026-06-29 |
| Telegram Bot API | implemented webhook/outbox transport | bot token | env flag | delivery worker only | n/a | 2026-06-29 |
| Skyscanner Indicative | contract only | none | no | no | no | 2026-06-23 |
| Skyscanner Live | contract only | none | no | no | no | 2026-06-23 |
| Duffel | contract only | none | no | no | no | 2026-06-23 |

## Current Slice: Human-readable places and airlines

- Goal: remove mandatory IATA knowledge from the UI, preserve city-versus-airport
  semantics, and show factual flags, place names and airline identity.
- Selected approach: local place directory now, provider suggest enrichment
  through the same contract after credentials arrive.
- Design:
  `docs/superpowers/specs/2026-07-17-human-readable-places-and-airlines-design.md`.
- Implementation plan:
  `docs/superpowers/plans/2026-07-17-human-readable-places-and-airlines.md`.
- Progress:
  - [x] Audit the existing airport, provider and result presentation paths.
  - [x] Confirm universal city-group versus specific-airport behavior.
  - [x] Select the hybrid local/provider directory architecture.
  - [x] Review and accept the written design.
  - [x] Write the implementation plan.
  - [x] Execute the implementation plan through focused TDD and independent review.
  - [x] Verify desktop/mobile, commit to `main` and restart locally.
- Delivered: immutable typed place directory; `/places/suggest` and batch
  `/places/lookup`; city expansion preserved through search, agent plans and
  durable watches; accessible comboboxes; requested-versus-concrete route
  labels; flags; carrier names, trusted CDN logos and monogram fallback.
- Release verification on 2026-07-17: migration `0030_typed_watch_places` is
  current; global Ruff format/check and mypy pass. The single full backend run
  completed with 1543 passes and three stale-fixture failures; all three
  corrected nodes pass afterward. Chromium completed six unaffected scenarios,
  and the corrected real-combobox search scenario passes separately. Live
  desktop `1440x1000` and mobile `390x844` smoke checks confirm no page-level
  horizontal overflow, correct `city`/`airport` selections, human requested and
  concrete routes, and the carrier identity strip without console warnings.
  `/healthz=ok`, `/readyz=ready` with database `ok`, the `Москва` suggestion is
  `MOW/city`, and the restarted worker healthcheck is green. No live provider
  call or security scan was run for this local-only UI slice.

## Previous Slice: Search-first UI redesign

- Goal: replace the all-at-once technical dashboard with one obvious flow:
  describe a trip, review the plan, run the search, compare results.
- Selected concept: `docs/ui-concepts/01-search-first.png`, with the transparent
  plan structure from `05-journey-board.png`.
- Design:
  `docs/superpowers/specs/2026-07-17-search-first-ui-redesign.md`.
- Execution plan:
  `docs/superpowers/plans/2026-07-17-search-first-ui-redesign.md`.
- Progress:
  - [x] Generate and compare six distinct UI concepts.
  - [x] Select the search-first direction independently as requested.
  - [x] Lock the new hierarchy in HTML/browser tests.
  - [x] Implement the responsive shell and progressive disclosure.
  - [x] Translate remaining mixed-language and mojibake copy.
  - [x] Run focused unit, Chromium, lint and type gates.
  - [x] Restart the local release with the redesigned UI.
- Verification: 17 focused UI unit tests and 10 Chromium E2E tests pass;
  Ruff format/check passes for the changed files; mypy passes all 123 source
  files; `git diff --check` is clean. Live desktop and 390 px mobile checks
  confirm no page-level horizontal overflow; `/healthz` is `ok`, `/readyz` is
  `ready` with database `ok`, and the local worker heartbeat is healthy.

## Previous Slice: Agent Route Orchestrator

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
  - [x] Make free text, all seven presets and the approval-gated web plan card
    use the same builder without provider calls before explicit execution
    (Task 6 accepted by independent review at `8f7b39b`, with no
    Critical/Important/Minor findings after dynamic session-race verification).
  - [x] Persist the durable operation ledger (Task 7 accepted by independent
    review at `0babb2a`, with no Critical/Important/Minor findings).
  - [x] Execute resumable Aviasales calendar/exact work in the worker (Task 9
    accepted at `c0d7de6`; clean-environment gates fixed at `98147bc`).
  - [x] Execute every frozen finite pair and bounded ANYWHERE discovery binding
    (Task 10 accepted at `39fcf60`; status acceptance at `db7798a`).
  - [x] Compose and rank split, self-transfer, open-jaw and multi-city routes
    (Task 11 accepted at `ce4231a`).
  - [x] Isolate hidden-city research behind a second acknowledgement.
  - [x] Add evidence-gated buy timing, anomaly and currency analysis.
  - [x] Pass compact local browser, recovery, migration and release gates.

Task 8 slice plan: freeze explicit airport/city provider locations; split exact
search into one-call start/poll operations with private continuation state;
map ticket-bearing polls to confirmed evidence; keep calendar rows as
indicative discovery signals in the date matrix; then run fixture-only focused,
unit, integration, type and lint gates. The slice was accepted by independent
review at `e9a1f2d` with no Critical, Important or Minor findings.

Task 8 implementation on 2026-07-15 adds the single-attempt async Aviasales
gateway and keeps Task 9 worker execution out of scope. Typed provider
locations preserve airport flags across reverse directions; the frozen current
capability rejects city semantics before I/O. Exact continuation data is
server-private and repr-redacted, while public polls contain only hash-identified
confirmed evidence, a cursor and conservative `complete=false` because no
terminal provider field is contract-proven. Calendar rows are distinct
indicative discovery signals in both calendar APIs/date-matrix responses, use
the verified `ru_RU` locale, carry the one-passenger basis and require live
confirmation. Wrong-route/out-of-range rows and malformed typed inputs are
rejected before false overlay/provider I/O. The slice is accepted; the progress
checkbox stays open because durable worker execution belongs to Task 9.

Task 8 independent-review hardening on 2026-07-15 closes the reviewed provider
boundary and evidence-invariant gaps without starting Task 9. Result hosts are
strict bare Aviasales ASCII hostnames; private client/gateway state is
repr-redacted; transport/decoder failures cannot retain provider-controlled
exception causes or contexts; and generic HTTP failures expose body-free typed
status/retry metadata. Exact continuations now bind route, dates, currency,
passengers and a caller operation namespace, while exact/calendar observation
UUIDs are idempotent only inside that namespace. Proposal currency, money and
direction groups are strict. Calendar publication and matrix overlay share
route/date/currency/shape validation, with a typed overlay context and explicit
one-adult indicative price basis. Contradictory passenger requests fail before
provider I/O. Fresh independent re-review accepted `e9a1f2d` with zero
Critical, Important or Minor findings.

Task 8 verification on 2026-07-15: the mandatory focused provider/date-matrix
suite passes 72 tests, the standalone mobile API regression suite passes 12,
the complete unit suite passes 943, and the separate integration suite passes
4. Full mypy reports no issues in 116 source files; global Ruff format/check and
`git diff --check` pass. Eight unit-suite warnings come from pre-existing
aiosqlite event-loop teardown and lxml deprecation paths outside this slice.
All provider tests use sanitized fixtures/fakes; no live call or secret-bearing
value is part of the test or report.

Task 8 review-fix verification on 2026-07-15: the required tests-only RED was
98 failed / 66 passed before production edits. Final focused tests pass 165,
the complete unit suite passes 1024 with 23 pre-existing teardown/deprecation
warnings outside the changed flow, and integration passes 4. Full mypy reports
no issues in 116 source files; Ruff reports 283 files formatted and all checks
passing. No live provider call, migration or Task 9 worker change was made.

Task 8 acceptance on 2026-07-15: the reviewer independently reran 165 focused,
1024 unit and 4 integration tests plus mypy/Ruff/diff checks, then executed
three forced-probe blocks covering all original provider-boundary findings.
Result: `ACCEPT`, zero Critical/Important/Minor findings, clean `main` at
`e9a1f2d`; no files were changed and no live provider call was made during
review.

Task 9 accepted slice plan/result: add an orchestration-only durable executor
over the accepted Task 7 ledger and Task 8 single-attempt gateway; materialize exact
start/poll handoffs or flexible calendar shortlists within approved logical and
HTTP budgets; persist only sanitized indicative/confirmed evidence; derive
minimal confirmed-only ranking and honest completed/partial/failed progress;
then wire the dedicated `agent` worker lane, public run counters, validated
local Aviasales settings, Compose and operator docs. Prove restart, dedupe,
cancellation/deadline zero-I/O, retry/circuit behavior and household/private
continuation isolation fixture-only before marking the slice complete. The
existing forward migration `0024_agent_execution_ledger` is sufficient. The
slice was accepted on 2026-07-15; Task 10 coverage breadth and Task 11
composition and Task 12 hidden-city isolation are now accepted. Task 13
evidence-gated analysis is the next release slice.

Task 9 implementation on 2026-07-15 is accepted by independent review. The
dedicated agent worker now
executes approved airport calendar/exact workflows as durable single-attempt
operations with committed pre-I/O reservations, private cursor handoffs, fresh
deadline/lease clocks, approved/current RPM minimums, Retry-After, circuit
open/half-open recovery and honest cancellation/partial terminal states.
Flexible shortlists reject route/currency/date/passenger-basis mismatches before
exact I/O, including an unapproved round-trip return. Public run endpoints expose
only bulk-aggregated stage/operation counters, approved/consumed budgets and
allowlisted typed errors; unknown diagnostics collapse to `agent_run_failed`.
Compose isolates the `agent` lane in `agent-worker`, while disabled, missing or
invalid Aviasales credentials fail before permit/reservation/transport. No new
migration was needed and no live provider call was made. The required four-file
gate passes 110 tests; executor, worker, real-SQL keyset, API and Compose focused
gates plus Ruff and mypy are recorded in `.superpowers/sdd/task-9-report.md`.

Task 9 acceptance on 2026-07-15: after two independent review/hardening cycles,
the frozen combined tree received `ACCEPT` with zero Critical, Important or
Minor findings. The final clean-database unit gate passes 1205 tests, focused
Task 9 and regression gates pass 187 and 263, integration passes 4, security
passes 2 with zero scanner findings, fresh-cache mypy passes 118 source files,
Ruff reports 286 files formatted and all checks passing, Compose validates and
Alembic has the single `0024_agent_execution_ledger` head. Accepted executor
hardening is `c0d7de6`; deterministic clean-environment gates are `98147bc`.
No live provider call was made and the user's local database was untouched.

Task 10 implementation was accepted and committed on 2026-07-16. QUICK and FULL
execute every frozen finite
airport/date pair for airport, city, country, region and nearby scopes; aliases
collapse, same-airport pairs are excluded, taxonomy/catalog versions and nearby
distances are frozen before approval, and unknown ground cost remains unknown.
Bounded ANYWHERE discovery queries every approved origin/source binding, stores
typed Aviasales hot-offer signals, and then atomically freezes one immutable
ordered destination/source-signal snapshot before exact searches. Later catalog
or feed changes cannot expand the approved run. Public run views expose an
honest per-pair coverage report; corrupt projections fail closed, and incomplete
FULL coverage remains `partial` with stable reasons. Migration
`0025_agent_anywhere_discovery` is the single head. The exact
four-file Task 10 plan gate passes 231 tests; provider, persistence and worker
regressions pass 382 tests; all 1,362 unit tests and all 4 integration tests pass.
Fresh full mypy passes all 118 source files, Ruff reports 288 formatted files
and all checks passing, the security scan reports zero findings, the 10 focused
ops/release/Compose tests pass, `docker compose config --quiet` passes with a
process-only validation secret, and Alembic has the single `0025` head.

The rejected pre-hardening freeze is superseded. Its four Important findings
are fixed test-first: curl now returns libcurl's real write-error sentinel on
overflow; hot-offer date/catalog/existing-destination filters run before the
durable remaining-capacity quota; ANYWHERE discovery is capped at 12 inclusive
months at planning/scope/snapshot/client boundaries; and all money entering the
agent path fits the shared signed SQL `Integer` ceiling. The bounded parser still
validates every in-bounds row and constructs only the deterministic selected
top-K. No live provider call was made and no user database was opened or
migrated. Both independent re-review gates accepted the exact same manifest
with zero Critical, Important or Minor findings. The provider/persistence
review additionally passed 521 tests; the architecture/spec review passed the
231-test required gate, 454 expanded tests, all 118 mypy source files, Ruff over
288 files, PostgreSQL offline DDL compilation and the final manifest recheck.
The accepted implementation commit is `39fcf60`; its reviewed pre-commit
manifest was HEAD `4744e4e`, tracked patch `4ce4a188`, migration `0e0d5a3f`,
fixture `af82d67a` and coverage test `648bf32c`.

Task 11 active slice plan: compose routes only from confirmed evidence; retain a
native multi-segment provider result as one ticket with unknown protection;
enforce deterministic same-airport, airport-change, overlap and maximum-layover
rules for split/self-transfer candidates; reject incomparable currency or
passenger bases and keep unknown transfer cost explicit. Materialize open-jaw
and multi-city as bounded per-leg exact searches while native capability is
unknown, bound candidate growth with a stable beam, persist immutable component
and ranking snapshots, then expose cheapest, fastest, balanced, low-risk,
split/self-transfer and risky views without leaking provider references or URLs.
Implementation proceeds test-first through domain composition, execution,
persistence, API reporting and focused/full quality gates.

Task 11 seam audit amendment: composition chronology must use the provider's
verified Unix instants, not local timestamp strings; every confirmed component
must retain its immutable planned-leg binding; and split/self-transfer provider
work must be frozen and included in the approved logical/HTTP budget before any
call. Agent booking actions also require an opaque household-scoped descriptor:
the legacy generic HMAC token embeds its `ref` in reversible base64 and therefore
cannot be reused for agent results. The slice consequently includes provider
timestamp normalization, planning tests and a forward private-descriptor
migration in addition to the original Task 11 file map. No schema change is
needed for composed candidates or ranking snapshots already created by `0024`.

Task 11 implementation and acceptance on 2026-07-16 composes only confirmed
evidence with verified UTC chronology, bounded beam/Pareto growth and explicit
ticket, protection, transfer and unknown-cost facts. Unknown native multi-leg
capability executes frozen ordered per-leg searches; approved split work is
derived only from confirmed hubs and reserved in the pre-execution budget.
Immutable composed candidates and six-view ranking snapshots project through a
typed API without reranking on reads. Normal confirmed results receive only an
opaque household/run-scoped booking token; private Aviasales click descriptors
stay server-side and resolve only after an authenticated explicit click.
Completed/partial runs require a saved ranking snapshot, while typed persistence
or local-analysis failures close their ledger operation instead of leaving a
stale lease. Migration `0026_agent_booking_action_descriptors` is the single
Alembic head. The unified Task 11 acceptance gate passes 530 tests, the full
unit suite passes 1,419 with 35 known `aiosqlite` event-loop teardown warnings
outside the changed flow, and integration passes 4. Migration/upgrade passes 13,
mypy passes 121 source files, Ruff reports 294 formatted files and no findings,
the security scan reports zero findings, release migration/upgrade/Compose/health
stages pass, and a fresh temporary database upgrades through `0026` with the
private descriptor table present. Independent read-only review returned
`ACCEPT` with zero Critical or Important findings and one non-blocking Minor for
optional future recomputation of the composed fingerprint/UUID. The exact
post-review regression set passes 24 tests and `git diff --check` is clean.
Implementation is committed at `ce4231a`. No live provider call or user database
access was performed; Task 12 hidden-city isolation is now accepted.

Task 12 accepted slice plan/result: add a pure typed hidden-city eligibility boundary,
then bind the current warning acknowledgement to the exact revision, execute
bounded onward-destination research only for the final eligible one-way plan
leg, and keep qualifying candidates outside normal rankings. Hidden-city output
will be research-only when checked baggage is unknown, rejected when checked
baggage is known included, and will expose neither booking nor watch actions.
The existing generic approval snapshot can store the warning version; execution
requires a distinct durable operation kind and therefore extends the Task 12
file map to the operation repository and its contract tests. All provider work
remains fixture-only during implementation.

Task 12 accepted result on 2026-07-16: hidden-city now freezes a bounded
onward-destination rule only for the final finite one-way leg, requires the
exact `hidden-city-v1` acknowledgement bound to the immutable revision, and
runs provider discovery through the distinct durable
`hidden_city_discovery` operation introduced by migration
`0027_agent_hidden_city_research`. Exact ticket evidence is classified from
typed ticket shape, segment continuity and checked-baggage state. Known
checked baggage is rejected; unknown baggage remains
`research_only_not_actionable`. Accepted candidates are stored with
`search_role=hidden_city`, excluded from normal composition/ranking, never
receive booking descriptors, expose no watch action, and render in a separate
reload-safe web/API section with source, `LIVE` freshness and `observed_at`.
Legacy pre-Task-12 evidence with `baggage_status=NULL` remains readable as
`UNKNOWN`, while new hidden evidence fails closed unless live baggage facts
are explicit and consistent. Aviasales `baggage_count` now maps conservatively:
positive is included, zero is not included, missing or negative is unknown.
The post-review Task 12 regression set passes 321 tests; the full executor
passes 155, persistence/migration passes 250, and integration passes 4.
Independent read-only review returned `ACCEPT` with zero Critical, Important
or Minor findings. The fresh full release check passes 1,445 tests with 7
deselected and 11 warnings, Ruff format/lint over 298 files, mypy over 122
source files, 12 migration tests, the pre-v1 upgrade test, security with zero
findings, Compose validation and health tests. The browser stage was
intentionally skipped because no browser runtime was requested. Implementation
is committed at `cabeeeb`. No live provider call or user database access was
performed.

Task 13 was accepted by independent read-only review on 2026-07-16 with zero
Critical, Important or Minor findings. Exact confirmed evidence now receives a
canonical history-series hash; migration `0028_agent_fare_analysis_history`
adds the household/series/time index and one immutable append-only analysis
snapshot per run. Legacy `NULL` evidence stays excluded rather than guessed.
Buy timing and suspected-anomaly decisions publish their thresholds, sample
coverage and calculation versions; all market-minimum observations participate
even when the snapshot stores only a bounded representative reference set plus
a fingerprint of the full input history. Open-jaw, multi-city and composed
split/self-transfer routes return an explicit unsupported full-itinerary state
instead of analyzing one component as the trip. Old active `task9-v1`
`minimal_report` operations recover after upgrade, while mismatched immutable
inputs or stale snapshots fail closed. Currency output remains
`fx_provider_unavailable` until a real approved FX path exists, never invents
savings, and the UI distinguishes a generic price monitor from the canonical
analysis history.

Task 13 verification: the exact plan gate passes 114 tests; analysis/executor
passes 196; lifecycle/API/web passes 102; all persistence tests pass 313 with
one pre-existing aiosqlite teardown warning; migration/history upgrade checks
pass 18; full mypy passes 123 source files; focused Ruff format/lint and
`git diff --check` pass. No live provider call or user database access was
performed. Task 14 browser/recovery/observability and the final release gate are
next.

Task 14's practical local-v1 scope is complete on 2026-07-16. The bundled web UI
now persists versioned plan and run IDs, prevents duplicate execute requests,
binds the execute lock to the current session generation, and restores only the
newest run for the current plan revision. It stops terminal polling, keeps
cancel bound to explicit IDs, and renders typed `sources` and ranking reasons
for confirmed results separately from hidden-city research. Accessible
live/status regions, hidden-city acknowledgement and mobile controls are
covered by a compact real-Chromium smoke set. The deterministic fixture gateway
cannot make network calls; a migrated file-backed SQLite integration proves
that a new worker resumes the persisted exact poll continuation after process
restart and stores one deduplicated confirmed evidence record.

Task 14 observability is also complete: lifecycle audit events contain only
IDs, parser/planner/ranker versions, stable status codes, states and numeric
budgets. Migration `0029_agent_operation_telemetry` persists cumulative
provider-denial and expired-lease recovery counters, so separate API and worker
processes expose the same facts through admin health and `/api/v1/metrics`.
Due-work aggregation now uses the exact claim predicate. `agent_acceptance`
runs async backend contracts and focused Playwright in separate processes with
live provider/LLM/Telegram credentials disabled. The full-suite audit also
keeps legacy confirmed records with a missing `history_series_hash` readable as
`None`.

Task 14 verification: backend agent acceptance passes 291 tests; focused
Chromium acceptance passes 3; focused changed-area regression passes 76 plus 8
restart/worker/telemetry checks; the full non-browser suite passes 1499 with 10
browser tests deselected. The actual
`flight-hunter-release-check --stage agent_acceptance` command reports
`status=passed`. Ruff format checks 309 files, global Ruff lint passes and full
mypy passes 123 source files. The exhaustive ten-scenario browser expansion was
intentionally not added: this personal local release keeps the three
high-value plan/run/reload/cancel/mobile flows instead of an enterprise test
matrix. Existing full-suite aiosqlite event-loop teardown warnings remain test
harness noise. No live provider call or user database access was performed.

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
60-operation limit. The first independent review's four Important findings are
fixed test-first: chat validation now returns sanitized typed 422 errors,
clarification fallback enters successor-revision edit mode, every
household-scoped async response is invalidated across logout/session changes,
and all seven presets render. Focused Task 6 tests pass 40/40, Task 3/4/5
regressions pass 166/166, all 754 unit tests and 4 integration tests pass, mypy
checks all 114 source files, and global Ruff format/check pass across 276 files.
No provider call occurs before explicit execute. Independent re-review repeated
the late-401 and late-200 A-to-B session swap in headless Chromium, verified
that current-session expiry and initial signed-out bootstrap clear exactly once,
and accepted `aed323d..8f7b39b` with no Critical, Important or Minor findings.

Task 6 follow-up re-review fix on 2026-07-14 binds auth refresh to the exact
captured token and session generation. A late `/auth/me` success or error from
session A cannot overwrite or clear a newer session B. Signed-out bootstrap and
current-session expiry clear once; the chained session-bound loader is a no-op
without a token. Focused Task 6 plus auth regressions pass 49/49, all 756 unit
tests and 4 integration tests pass, rendered web JavaScript parses, mypy checks
114 source files, and Ruff format/check remain clean across 276 files. Final
independent re-review accepted the slice at `8f7b39b` with no findings.

Task 7 implementation and three independent-review fix cycles are complete and
accepted by final independent re-review at `0babb2a`; its acceptance checkbox is
complete. The
third cycle reproduces the real stale-read/duplicate-INSERT race and now raises
stable fingerprint or private-continuation conflicts only after leaving the
`IntegrityError` handler. Public errors retain no SQL cause/context or formatted
private parameters, and unknown INSERT collisions no longer escape raw. Unreleased
migration 0024 and matching Core metadata now compile PostgreSQL-safe boolean
predicates, persist one-shot circuit outcomes, and add a unique DB-backed
predecessor link for forward exact-search handoffs. Duplicate circuit callbacks
are idempotent while conflicting outcomes fail stably; provider-bound operations
can attach only their own provider evidence. Orphan polls cannot execute, and a
source completes atomically with binding one fresh forward poll. Canonical private
continuation drift is rejected without entering public DTOs, reprs, errors, or
formatted traceback chains. The traceback suite passes 3/3, the second re-review
suite passes 27/27, the combined Task 7 gate passes 163/163, Task 4-6
lifecycle/API/UI regressions pass 77/77, all 912 unit tests and 4
integration tests pass, the actual 0024 PostgreSQL offline compilation passes,
targeted mypy and global Ruff format/check are clean, and `git diff --check`
passes. The warning audit found only two unrelated third-party `lxml` warnings.
No provider call was made and Task 8 was not started. The final reviewer repeated
the stale-read duplicate race, prior 27-case re-review suite, focused Task 7 and
integration gates and accepted the slice with no Critical, Important or Minor
findings.

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
