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
