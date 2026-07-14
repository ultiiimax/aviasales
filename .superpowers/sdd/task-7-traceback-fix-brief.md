# Task 7 traceback secrecy fix brief

Base commit: `97f2ac2 fix: make agent ledger outcomes idempotent`

Status: NOT ACCEPTED because one Important privacy finding remains. Keep Task 7
pending until the same reviewer accepts the exact final range.

## RED first

Add a focused regression that exercises the real duplicate/stale-read
materialization path:

- initial fingerprint lookup misses;
- duplicate `exact_poll` INSERT raises `IntegrityError`;
- retry lookup finds the already persisted operation;
- requested private continuation differs from the stored continuation.

Before production changes, prove:

- public error code is `agent_operation_private_continuation_conflict`;
- `traceback.format_exception(error)` contains the requested private value;
- the SQLAlchemy `IntegrityError` is reachable through the exception context;
- ordinary `repr(error)` remains clean.

Record the exact RED command/result in `.superpowers/sdd/task-7-report.md`.

## GREEN implementation

- Never raise the stable materialization conflict while the `IntegrityError`
  handler is active. Resolve the existing row and compute only a non-sensitive
  conflict code inside the handler, leave the `except` block, then raise a fresh
  `AgentOperationConflict` outside it.
- Do not retain, render, log, chain, or expose the original database exception.
  `from None` alone is insufficient if the resulting exception still exposes a
  secret-bearing `__context__`; the final public exception must have no usable
  SQL exception chain.
- An unclassified integrity collision in this private-payload INSERT path must
  also leave the repository as a stable secret-safe error, never raw
  `IntegrityError` with SQL parameters.
- Preserve idempotent replay for identical canonical continuation, logical-root
  conflict behavior, caller-owned rollback, and concurrent SQLite/PostgreSQL
  behavior.
- The GREEN test must assert the requested and stored private values are absent
  from `str`, `repr`, `traceback.format_exception`, `__cause__`, and any exposed
  context chain. Also cover public fingerprint conflict on the same race path.

Do not add private values to logs, reports, test names, assertion messages, or
fixtures that get printed on failure; use unmistakable synthetic sentinels only
inside local test data and scan the formatted exception output.

## Required gates

Run sequentially:

1. new traceback regression;
2. dedicated second re-review suite;
3. full Task 7 gate;
4. lifecycle/API/UI gate;
5. full unit and integration suites;
6. PostgreSQL 0024 offline DDL test;
7. Ruff format/check, affected mypy, `git diff --check`.

No provider network calls. Update the report as pending re-review. Commit on
local `main` with exact message:

`fix: prevent private continuation traceback leaks`
