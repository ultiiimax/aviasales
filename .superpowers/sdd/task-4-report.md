# Task 4 report: agent plan lifecycle persistence

## Result

Task 4 is implemented as a forward migration and a typed async persistence slice. Plans and
immutable revisions, execution approvals, and runs are household-scoped. Repositories never
commit; the caller owns the outer transaction that binds a run, consumes its approval, and
consumes the immutable revision snapshot.

## TDD evidence

Initial RED was captured before any production or migration edit with the exact focused command:

```powershell
uv run pytest tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
```

It exited 1 with the expected missing implementation: both new repository test modules raised
`ModuleNotFoundError: flight_hunter.persistence.agent_repositories`; pytest reported two
collection errors in 0.82 seconds.

The first GREEN after migration 0023, Core metadata, and repositories was `14 passed in 2.58s`.

A second DB-level RED deliberately synchronized two file-backed SQLite sessions after their
active-run precheck. The concurrent repository outcome was already one winner and one typed
`agent_plan_active_run` loser, but the terminal-history insert exposed an unintended extra
`UNIQUE(revision_id)` constraint: `1 failed, 15 passed in 4.90s`. Removing only that non-contract
overconstraint produced `16 passed in 3.73s`. The synchronized race then passed five consecutive
runs (0.67s, 0.94s, 0.74s, 0.68s, and 0.79s).

## Decisions

- Migration `0023_agent_plan_lifecycle` advances only from 0022; 0022 was not edited.
- Revision content is canonical UTF-8 JSON with sorted keys and compact separators. The stored
  `sha256:` checksum covers plan, frozen scope, capability and cost-model snapshots, versions,
  and estimates. No raw prompt column or repository input exists.
- Successors use a household-scoped compare-and-swap update. The losing concurrent writer gets
  `AgentPlanConflict("agent_plan_stale")`; the old revision content remains untouched.
- Clone idempotency is a unique partial index on `(household_id, clone_idempotency_key)`.
- Execute idempotency is unique on `(household_id, execute_idempotency_key)`.
- Exactly one `queued`, `running`, or `cancel_requested` run may exist per plan. Both Core metadata
  and the migrated SQLite schema use that exact partial-index predicate; terminal history may
  coexist.
- Approval binding is single-use. The run insert, approval CAS, and revision-consumption CAS are
  contained in a savepoint inside the caller's outer transaction. No repository method commits.
- Latest-run selection orders by `(created_at DESC, id DESC)`.

## Verification outputs

- Final focused gate: `16 passed in 3.73s`.
- Migration/upgrade subset: `6 passed in 1.65s`.
- Persistence regression directory: `71 passed in 8.35s`.
- New repository mypy: `Success: no issues found in 1 source file`.
- Targeted Ruff check: `All checks passed`; targeted format check: seven files already formatted.
- Full unit suite, run separately: `629 passed in 45.82s`.
- Full integration suite, run separately: `4 passed in 3.89s`.
- `git diff --check`: clean.

## Concerns

The full unit and persistence regression runs still emit existing `aiosqlite` worker-thread
shutdown warnings from older tests that do not dispose their engines. The new focused tests
dispose their engines and run without warnings. No live provider calls are part of this slice.

## Re-review hardening addendum (2026-07-14)

Task 4 was returned with four Important findings. This addendum records the separate hardening
pass; Task 4 remains pending independent re-review.

### TDD evidence

The first test-only RED imported the required exact integrity classifier and immutable approval
snapshot types before production edits. The focused command failed during collection with one
missing-import error in 0.89 seconds. After the initial implementation, the same command exposed
28 failures and 35 passes: the first root was SQLite savepoint-first-write persistence after an
outer rollback, while canonical serialization of immutable mappings caused the bulk of the
remaining failures.

Focused tests then reached 63 passes. Self-review added stricter rollback cases with a committed
source revision and a precommitted approval. Both failed before the transaction fix: the successor
survived caller rollback and execute left its approval/revision consumed. A global SQLite hook was
rejected because deferred read-to-write upgrades produced `database is locked` under the active-run
race. The final local solution acquires `BEGIN IMMEDIATE` before successor/execute prechecks only
when the aiosqlite driver reports no physical transaction. It neither retries nor commits or rolls
back caller state. The two rollback tests then passed, and the simultaneous clone, execute,
active-run, and successor race selection passed eight tests without a lock leak.

### Corrected contracts

- Approval rows now contain a frozen typed snapshot with non-null revision hash, approving session,
  canonical budget JSON, canonical strategy JSON, and canonical risk-warning version JSON. Approval
  and execution both verify the snapshot hash against the immutable revision being consumed.
- Every repository datetime write converts aware input to UTC. Naive writes are rejected; reads
  interpret legacy naive values as UTC and normalize aware values to UTC. `+03:00` round trips are
  covered for plans, revisions, approvals, runs, and transitions.
- PostgreSQL integrity handling uses only `diag.constraint_name`. SQLite handling accepts only exact
  known `UNIQUE constraint failed` signatures. Foreign-key, check, primary-key, unknown, and
  near-match errors are re-raised rather than translated.
- Run statuses are exactly `queued`, `running`, `cancel_requested`, `completed`, `partial`, `failed`,
  and `cancelled`. Compare-and-swap transitions, lifecycle timestamps, terminal immutability, and
  error-field compatibility match the reviewed state machine.
- Awaiting-approval estimates must be complete, positive/non-negative as applicable, and internally
  consistent in both typed validation and the database check. Draft revisions may omit estimates.
- Migration 0023 and Core metadata have matching SQLite/PostgreSQL active-run predicates for only
  `queued`, `running`, and `cancel_requested`; terminal history is allowed. Migration 0022 remains
  unchanged.

### Fresh verification

- Exact focused repository/migration/pre-v1 upgrade gate: `65 passed in 7.27s`.
- Full persistence unit directory: `122 passed in 12.79s`.
- SQLite engine/concurrency plus focused migration gate: `69 passed in 7.91s`.
- Full unit suite: `680 passed, 23 existing aiosqlite shutdown warnings in 45.94s`.
- Full integration suite: `4 passed in 2.99s`.
- Global format: `271 files already formatted`; global Ruff: `All checks passed`.
- Global mypy: `Success: no issues found in 111 source files`.

- `git diff --check`: clean.

## Second re-review hardening addendum (2026-07-14)

One Important and two Minor findings remained after the first hardening commit. Production and
migration files stayed unchanged while the next focused RED was captured: `12 failed, 65 passed in
10.45s`. The failures were the two real SQLite caller-savepoint mutations, shallow nested approval
data, three repository chronology violations, three direct database chronology violations, a
PostgreSQL fake observing an unnecessary connection acquisition, and the missing Core/migrated
chronology checks.

### Transaction boundary

- Successor and execute inspect the bound dialect before acquiring a connection. PostgreSQL is a
  SQL-free no-op even when its session is nested.
- SQLite rejects any already-open caller savepoint before a read, row mutation, or repository-owned
  savepoint with `agent_sqlite_nested_transaction_unsupported`. Tests roll the caller back, prove
  source/revision/approval/run state is untouched, then write successfully from a fresh session.
- Ordinary explicit `session.begin()` and autobegin remain supported. When no physical SQLite
  transaction exists they acquire `BEGIN IMMEDIATE`; caller rollback removes every mutation.

### Chronology and immutable evidence

- Run transition CAS updates require `changed_at >= created_at`; completed/partial/failed also
  require `changed_at >= started_at`, and cancelled requires
  `changed_at >= cancel_requested_at`. Equal timestamps are valid.
- Matching `ck_agent_plan_run_chronology` checks in Core metadata and unreleased migration 0023
  enforce the same ordering against direct database writes.
- Approval mappings and sequences are recursively defensive-copied and frozen. Nested caller
  mutation cannot alter input or read DTOs, nested mutation attempts fail, and canonical JSON is
  generated from a deterministic mutable copy without weakening the immutable snapshot.

### Fresh verification

- Exact focused repository/migration/pre-v1 upgrade gate: `78 passed in 8.51s`.
- Migration/pre-v1 upgrade subset: `7 passed in 1.98s`.
- Full persistence unit directory: `135 passed in 13.93s`.
- Full unit suite: `693 passed, 19 existing dependency/aiosqlite warnings in 47.95s`.
- Full integration suite: `4 passed in 3.31s`.
- Global format: `271 files already formatted`; global Ruff: `All checks passed`.
- Global mypy: `Success: no issues found in 111 source files`.

## Final cancellation-chronology addendum (2026-07-14)

The remaining Minor finding was reproduced test-first. With tests changed and production untouched,
the exact focused repository/migration/pre-v1 upgrade command produced `4 failed, 77 passed in
9.21s`: the repository accepted a cancellation request before the run start, a direct database
write accepted the same invalid chronology, and the exact Core/migrated check definitions lacked
the clause. A direct database equality case already passed.

The running-to-cancel-requested compare-and-swap now requires
`started_at <= cancel_requested_at`; queued cancellation remains valid because `started_at` is
null. Core metadata and unreleased migration 0023 contain the exact matching clause
`cancel_requested_at IS NULL OR started_at IS NULL OR cancel_requested_at >= started_at`.
Repository and direct database tests reject a request one minute before start and accept equality.
Migration 0022 remains unchanged. Task 4 remains pending final independent re-review.

### Localized verification

- Exact focused repository/migration/pre-v1 upgrade gate: `81 passed in 9.25s` (fresh pre-commit rerun).
- Targeted Ruff format/check: clean.
- Targeted mypy: `Success: no issues found in 2 source files`.
- `git diff --check`: clean.
