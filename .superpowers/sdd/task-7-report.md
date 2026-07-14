# Task 7 implementation report

Status: review fixes complete; pending independent re-review and not accepted yet.

## RED evidence

Tests were added before any Task 7 production file or schema change. The first
focused run was:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q

ERROR tests/unit/persistence/test_agent_operation_repository.py
  ModuleNotFoundError: No module named 'flight_hunter.application.agent_operations'
ERROR tests/unit/persistence/test_agent_evidence_repository.py
  ImportError: cannot import name 'AgentEvidenceRepository'
ERROR tests/unit/application/test_agent_operations.py
  ModuleNotFoundError: No module named 'flight_hunter.application.agent_operations'
3 errors in 1.80s; exit code 1
```

This is the expected RED: Task 7's application module and durable operation /
evidence repositories do not exist on the accepted Task 6 baseline.

After the initial implementation exposed three concurrency gaps, dedicated
regression tests were added before those paths were changed:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py -q

16 failed, 9 passed in 10.67s
```

The failures proved that an expired final-attempt lease remained permanently
`leased`, claim still leased work for cancelled/completed/deadline-expired
runs, reservations had no worker ownership argument, and the Task 7 SQLite
boundary leaked the older plan-layer exception type.

Two focused follow-up regressions were also captured before their fixes:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py -q \
  -k 'rpm_window_excludes'

1 failed, 25 deselected in 1.70s
```

The provider attempt exactly 60 seconds old was still counted and produced the
invalid boundary `retry_at == now`. The rolling window now uses the consistent
half-open predicate `reserved_at > now - 1 minute`.

```text
uv run pytest tests/unit/persistence/test_agent_evidence_repository.py -q

2 failed, 18 passed in 9.10s
```

The targeted failure showed that retrying one ranking fingerprint with a new
row ID created a second snapshot. The other failure was a test expectation that
used a mutable list for an intentionally frozen record and was corrected to the
existing immutable tuple contract. Ranking now has both repository dedupe and
`UNIQUE(run_id, fingerprint)`; different fingerprints remain append-only.

A final privacy audit added a neutral-key URL fixture before changing the
sanitizer:

```text
uv run pytest tests/unit/persistence/test_agent_evidence_repository.py -q \
  -k 'nested_secrets'

1 failed, 5 passed, 16 deselected in 3.62s
```

The signed URL passed under `href`; recursive value-level URI rejection now
closes that key-alias bypass, including leading whitespace and mixed case.

## Schema and transaction decisions

- Migration 0024 adds immutable logical-operation and HTTP-attempt budgets plus
  consumed counters to `agent_plan_runs`. Historical 0023 rows receive honest
  zero budgets/counters, so they cannot perform unapproved new I/O after upgrade.
- New runs copy the exact server-owned revision estimates. Caller input cannot
  raise either approved budget.
- The ten ledger/evidence tables retain household/run/stage ownership. Exact
  start and poll rows have separate row fingerprints but one workflow
  fingerprint; a partial unique root index permits only one logical-unit root.
- Provider rate lock and circuit state are global per provider, while public
  reads remain household-scoped and do not expose cross-household attempt data.
- SQLite multi-statement mutations reuse the reviewed Task 4 boundary: acquire
  `BEGIN IMMEDIATE` only when the physical transaction is repository-owned,
  reject a caller savepoint before mutation, and never commit or roll back the
  caller's transaction. PostgreSQL executes no SQLite-only SQL.
- Public operation records structurally omit continuation state. Only the
  server-private lease return type carries it to a worker.
- Discovery, confirmed evidence, composed candidates and ranking snapshots use
  distinct rows and return types. Candidate/ranking references must match both
  household and run; discovery IDs are rejected from ranking.
- Reservations require the current worker's unexpired lease and re-check an
  active `queued|running` run with a future deadline in the same write
  transaction. A stale worker cannot spend HTTP budget after lease takeover.
- Claim holds/serializes the run state and deterministically terminalizes an
  expired lease whose final attempt was already consumed. Cancel-requested,
  terminal and deadline-expired runs cannot begin new work.
- Evidence JSON is canonical and recursively rejects secret/token/signature,
  marker, raw provider payload, signed booking URL and passenger-PII fields.
  Money pairs, IATA/currency forms, passenger basis, timestamps, component
  references and risk statuses are validated before insert and backed by DB
  checks where relational SQL can express the invariant.
- Generic ledger JSON is URL-free: a recursively nested string whose trimmed
  value starts with a URI scheme is rejected case-insensitively, while ordinary
  prose such as `HTTPS protocol metadata` remains valid. A later research-link
  slice must introduce a separate typed, sanitized public-reference contract;
  it must not weaken this evidence/operation sanitizer.

## Independent review-fix RED evidence

After the first independent review returned 7 Important and 1 Minor finding,
all review-fix tests and schema contracts were written before touching Task 7
production code. The behavior-only review run was:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py -k review -q

62 failed, 5 passed, 56 deselected in 11.30s; exit code 1
```

Representative failures matched the review findings exactly:

```text
TypeError: OperationSpec.__init__() got an unexpected keyword argument
  'logical_root_operation_id'

assert operation.status is AgentOperationStatus.SKIPPED
E AssertionError: PENDING is not SKIPPED

assert "opaque-1" not in repr(lease)
E 'opaque-1' is contained in ServerPrivateOperationLease(...)

FAILED ...test_review_http_reservation_is_idempotent_per_claim_attempt_and_returns_identity
FAILED ...test_review_half_open_permit_is_one_shot_and_late_owner_cannot_close_takeover
FAILED ...test_review_each_json_context_has_its_own_explicit_allowlist
FAILED ...test_review_network_and_server_retry_use_bounded_jitter_without_lowering_retry_after
```

The migration/Core/pre-v1 RED run was separate:

```text
uv run pytest tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -k review -q

3 failed, 2 passed, 5 deselected in 2.10s; exit code 1
```

The failures prove that migration 0024 and Core metadata lack the reviewed
logical-root self-FK/index/checks, per-claim attempt uniqueness, circuit permit
generation/digest fields, and one-scope-per-run constraint. Production remained
at `bb41bd9` for both RED runs.

## Independent review-fix decisions

- `calendar_search` and `exact_start` are the only consuming logical roots.
  `exact_poll` has an explicit self-FK to its same-household/run/stage/provider/
  workflow exact-start root. Provider-neutral scope, comparison, composition,
  ranking and analysis rows are independent and consume no logical unit.
  `suggest_discovery` is rejected with `agent_operation_kind_not_budgeted` until
  a future approved estimate gives it an honest budget category.
- Claim atomically reconciles pending/retry rows and expired leases when a run is
  cancelled, terminal or deadline-expired. A current worker has a separate
  owner-and-live-lease CAS for cooperative skip; stale owners cannot terminate a
  reclaimed lease. Already completed partial results remain untouched.
- Success references use a closed kind/type matrix and are validated in the same
  caller-owned transaction. Exact start and non-final poll point to a typed next
  operation; final poll points to same-stage confirmed evidence. Scope,
  calendar, composition and ranking point only to their actual owned tables.
  Comparison/analysis success remains deferred instead of fabricating a result.
- Provider attempts persist the positive operation claim-attempt number and are
  unique per `(operation_id, operation_attempt_number)`. A replay of the same
  live claim returns the original reservation ID with `reused=True`, without a
  second RPM entry or budget increment. Attempt kind is derived and checked:
  initial start/calendar=`start`, initial exact poll=`poll`, reclaimed=`retry`.
- Circuit authorization is a server-private opaque token whose digest,
  generation, mode, operation and attempt binding are durable. Reservation
  revalidates and consumes it atomically with RPM/budget/attempt persistence.
  Denials do not consume a half-open probe; duplicate reservation does not grant
  a second call; takeover invalidates late reservations and outcomes from the
  prior generation. Raw tokens and continuations are absent from public records
  and hidden from private DTO reprs.
- Scope is immutable after first discovery: the DB permits one snapshot per run,
  same-fingerprint replay returns the original row, and a different fingerprint
  raises `agent_run_scope_conflict`, including concurrent writers.
- Operation input, private continuation, scope, discovery, confirmed,
  composition and ranking JSON each have an explicit allowlist plus typed value
  checks. URI forms, credential/PII aliases and nested/list bypasses are rejected;
  current normalized route/date/segment/component/ranking fixtures remain valid.
- Network/server retry backoff uses injected bounded ±20% jitter, caps at 300
  seconds, and leaves provider `Retry-After` unchanged.

## GREEN evidence

The post-fix review behavior and schema RED suites are green:

```text
review behavior (`-k review`): 67 passed, 56 deselected
review schema (`-k review`):    5 passed, 5 deselected
```

The mandatory focused and adjacent regression gates are green:

```text
Task 7 focused + migration/pre-v1 upgrade: 133 passed in 21.97s
Task 4-6 lifecycle/API/UI regression gate: 77 passed in 16.34s
```

The complete final gates are green:

```text
full unit suite:             882 passed, 13 warnings in 108.76s
separate integration suite:  4 passed in 5.70s
targeted mypy:                no issues in 3 source files
global ruff format --check:  281 files already formatted
global ruff check:           all checks passed
git diff --check:            clean
```

Warning audit: the full unit run had no failure and reported two third-party
`lxml` deprecation warnings plus eleven unrelated `aiosqlite` worker-thread
cleanup warnings in `test_deal_candidate_repository`; none originates in the
Task 7 files or changes gate status. No provider network I/O was performed.
Task 7 remains pending independent re-review and is not accepted by this report.

## Second independent re-review fix RED evidence

The five Important findings from the second independent review were translated
into additive focused tests before any production or migration change. The
first tests-only run from baseline `3b0fe4b` was:

```text
python -m pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_alembic_upgrade.py -k rereview_second -q

24 failed, 2 passed, 74 deselected in 9.00s; exit code 1
```

The failures demonstrated repeated circuit mutations, missing persisted
outcomes, accepted conflicting outcomes, stale half-open replay, cross-provider
result attachment, executable orphan polls, absent predecessor binding and
fan-in/fan-out protection, accepted continuation drift, missing outcome/handoff
schema, and PostgreSQL boolean predicates compiled as `= 0/1`.

The same run also exposed a tests-only fixture error: cursor values in two
private-continuation case groups were strings, while the already reviewed typed
contract requires non-negative integers. Those fixture values are corrected and
a clean second RED is recorded below before production is touched.

```text
python -m pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_alembic_upgrade.py -k rereview_second -q

23 failed, 3 passed, 74 deselected in 9.65s; exit code 1
```

All 23 failures now arise from the five missing product invariants; the three
passing preservation cases prove canonical continuation equality, explicit
self/cross-root rejection, and cross-provider composition/ranking aggregation.
No provider network request was made.

## Second independent re-review fix decisions

- Migration 0024 remains the unreleased Task 7 migration. Its operation checks
  and consuming-root partial index now use `IS TRUE` / `IS FALSE` in both Core
  and migration metadata. The test executes the actual 0024 upgrade through an
  offline PostgreSQL Alembic context and compiles the matching Core DDL.
- Every HTTP reservation owns nullable `circuit_outcome` and
  `circuit_outcome_recorded_at` fields under a paired-null/allowed-values check.
  Outcome handling locks the reservation row on PostgreSQL and uses the existing
  SQLite write boundary; state transition plus outcome CAS share one savepoint.
  Identical replay returns without another state mutation, conflicting replay
  raises `agent_circuit_outcome_conflict`, and non-transient failures are stored
  without incrementing circuit counters.
- Calendar discovery and exact-poll confirmation references include the source
  operation provider in the ownership query. Composition and ranking remain
  intentionally provider-neutral and aggregate evidence from multiple providers.
- `handoff_predecessor_operation_id` is a nullable operation self-FK. A unique
  partial index gives each predecessor at most one child; the target column plus
  CAS gives each poll at most one predecessor. Exact polls are claimable only
  after binding. Binding requires a fresh pending attempt-zero forward poll with
  matching household/run/stage/provider/root/fingerprint and commits in the same
  savepoint as source completion.
- Materialization compares the stored server-private canonical continuation JSON
  after all public fingerprint fields match. Exact equality, including reordered
  JSON, reuses the operation; any `None`/empty/content drift raises
  `agent_operation_private_continuation_conflict` without rendering either value.

## Second independent re-review fix GREEN evidence

The final dedicated re-review command is green after adding the explicit
`retry_wait` target case:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_alembic_upgrade.py -k rereview_second -q

27 passed, 74 deselected in 6.90s
```

The complete focused and adjacent gates are green:

```text
repository + migration final gate:                    101 passed in 24.04s
Task 7 ledger/evidence/application/schema/pre-v1 gate: 160 passed in 33.26s
Task 4-6 lifecycle/API/UI regression gate:             77 passed in 15.90s
extended lifecycle run including run repository:       127 passed in 22.35s
```

The complete final gates are green:

```text
full unit suite:                 909 passed, 9 warnings in 111.04s
separate integration suite:      4 passed in 3.65s
actual 0024 PostgreSQL DDL test:  1 passed in 0.77s
affected source mypy:             no issues in 2 source files
global ruff format --check:       281 files already formatted
global ruff check:                all checks passed
git diff --check:                 clean
```

Warning audit: the unit suite reported two third-party `lxml` deprecation
warnings and seven unrelated `aiosqlite` event-loop cleanup warnings in
`test_household_watch_repository`; none originates in Task 7 files. A direct
system-Python lifecycle invocation also stopped before collection because that
interpreter lacks the project's optional `httpx2`; the required `uv run` command
then passed. An intermediate `uv` re-review run exposed only a namespace-package
test harness import (`26 passed, 1 harness failure`); loading the actual migration
by absolute file path fixed the harness without changing production behavior.

No provider network I/O was performed. Task 7 remains pending independent
re-review and is not accepted by this report.

## Traceback secrecy re-review RED evidence

The traceback finding was reproduced from clean base `97f2ac2` with tests only;
no production or migration file had changed. The focused command was:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py -k traceback_review -q

3 failed, 90 deselected in 2.18s; exit code 1
```

Both the private-continuation and public-fingerprint stale-read cases exercised
a real duplicate `exact_poll` INSERT followed by retry lookup. Their public error
codes were already stable and ordinary `repr` was clean, but the formatted
exception reported `requested_exposed=True`, `chain_present=True`, and
`integrity_context=True`. The third case proved that an unclassified duplicate
INSERT still escaped as a raw database error. Synthetic private sentinels were
kept out of test names, assertion messages, and this report. No provider network
request was made.

## Traceback secrecy re-review fix decisions

- The duplicate-INSERT handler now resolves the winning row and computes only a
  non-sensitive conflict code. Idempotent reuse or a fresh stable conflict is
  handled after the `except IntegrityError` block has ended, so the public error
  cannot retain the database exception as implicit context.
- Public fingerprint and private continuation precedence is shared by a pure
  conflict-code classifier. The ordinary no-race path retains its existing
  behavior, while the race path no longer raises from inside the SQL handler.
- A duplicate INSERT with no matching fingerprint row and no competing logical
  root is classified as `agent_operation_fingerprint_conflict`; raw SQL errors
  and their parameter payloads do not cross the repository boundary.

## Traceback secrecy re-review GREEN evidence

The new real-collision regression and every required sequential gate are green:

```text
traceback regression:                    3 passed, 90 deselected in 1.53s
dedicated second re-review suite:       27 passed, 77 deselected in 5.91s
Task 7 combined gate:                  163 passed in 26.82s
Task 4-6 lifecycle/API/UI gate:         77 passed in 14.46s
full unit suite:                       912 passed, 2 warnings in 98.67s
separate integration suite:             4 passed in 3.36s
actual 0024 PostgreSQL DDL test:         1 passed in 0.64s
affected source mypy:                    no issues in 1 source file
global ruff format --check:            281 files already formatted
global ruff check:                      all checks passed
git diff --check:                       clean
```

The two unit warnings are unrelated third-party `lxml` deprecations. No provider
network I/O was performed, Task 8 was not started, and Task 7 remains pending
independent re-review rather than accepted by this report.
