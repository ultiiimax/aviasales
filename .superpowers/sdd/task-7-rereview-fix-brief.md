# Task 7 second re-review fix brief

Base commit: `3b0fe4b fix: harden agent execution ledger invariants`

Status: NOT ACCEPTED. Fix every Important finding below with a strict
RED -> GREEN cycle. Do not mark Task 7 accepted; the same independent reviewer
must re-review the final commit.

## TDD order

1. Add focused tests for all five findings. Run only those new tests and record
   the exact failing command/count in `.superpowers/sdd/task-7-report.md` before
   changing production or migration code.
2. Implement the smallest complete database-backed invariants. Migration 0024
   is still unreleased inside this unaccepted local slice, so keep migration and
   Core metadata exactly equivalent.
3. Run the new tests, the complete Task 7 focused gate, lifecycle/API/UI gate,
   full unit and integration suites, Ruff format/check, affected mypy, PostgreSQL
   DDL compilation, and `git diff --check`, strictly sequentially on Windows.
4. Update the report as `pending independent re-review`, commit on local `main`
   with `fix: make agent ledger outcomes idempotent`, and return the exact range.

## 1. PostgreSQL-safe boolean DDL

The migration and Core metadata currently emit `boolean = 0/1` in the logical
shape check and consuming-root partial index. PostgreSQL rejects that DDL.

- Use dialect-safe boolean predicates (`IS TRUE` / `IS FALSE`, or equivalent
  typed SQLAlchemy expressions) in both migration 0024 and Core metadata.
- Add an offline PostgreSQL compilation/migration test covering the actual 0024
  table check and partial index. Assert the emitted SQL contains valid boolean
  predicates and never `consumes_logical_unit = 0/1`.
- Preserve SQLite behavior and migration/Core parity.

## 2. One-shot circuit outcome

One HTTP reservation may mutate circuit state exactly once.

- Persist a typed outcome on `agent_provider_http_attempts`, for example
  `success`, `transient_failure`, or `non_transient_failure`, plus an aware
  recorded timestamp. Add a paired-null/allowed-values constraint in migration
  and Core metadata.
- Lock/CAS the attempt row and update its outcome together with circuit state in
  one transaction/savepoint. PostgreSQL and SQLite concurrent duplicate delivery
  must apply the state transition once.
- Replaying the identical outcome is idempotent and must not change counters,
  state, generation, or version a second time. A conflicting later outcome for
  the same reservation fails with stable code
  `agent_circuit_outcome_conflict`.
- Record non-transient failures too even though they do not increment/open the
  circuit. Never expose the outcome row's private permit digest/token publicly.
- Cover sequential and concurrent duplicate transient failure at threshold 2,
  duplicate success, success-then-failure, failure-then-success, and stale
  half-open takeover regressions.

## 3. Provider-owned evidence results

- Extend result-reference validation so provider-bound results require the same
  `provider_id` as their source operation. This applies at least to
  `calendar_search -> discovery_signal` and
  `exact_poll -> confirmed_offer`.
- Keep composition/ranking cross-provider aggregation behavior explicit and do
  not add a false provider restriction there.
- Add positive same-provider and negative different-provider tests, including
  same household/run/stage so provider is the only mismatch.

## 4. Forward, acyclic exact-operation handoff

An exact start/poll may hand off only to a fresh forward poll, never a leased or
terminal target and never an already-linked predecessor.

- Add an explicit nullable self-FK such as
  `handoff_predecessor_operation_id` on operation rows, with an index/uniqueness
  invariant that gives every poll at most one predecessor and every predecessor
  at most one child. Keep it server/domain metadata, not provider payload.
- On an `OPERATION` result, atomically bind the target predecessor and complete
  the source in the same savepoint. Target must be the same household/run/stage,
  provider, logical root/fingerprint, `exact_poll`, `pending`, attempt_count 0,
  not itself, and created no earlier than the source. A terminal/leased/retry
  target or existing predecessor is rejected with a stable conflict.
- An exact poll is claimable only after predecessor binding. This prevents
  orphan polls from executing.
- Cover start -> poll1 -> poll2, self/cross-root, cycle back to poll1,
  terminal/leased target, fan-in/fan-out and concurrent binding. Preserve the
  exact start/non-final poll `OPERATION` result contract.

If an equivalent DB-backed predecessor design is materially smaller, document
it in the report, but do not rely only on timestamps or an application-only
query without a uniqueness/CAS invariant.

## 5. Private continuation idempotency drift

- Idempotent materialization with the same operation fingerprint must compare
  canonical private continuation state as well as public fields. Same content
  returns the existing operation; different `search_id`/cursor/content fails
  with stable code `agent_operation_private_continuation_conflict`.
- Keep continuation values out of public DTOs, repr, errors, logs and evidence.
  A server-private canonical string comparison or digest is acceptable.
- Cover `None` vs object, empty object vs non-empty object, reordered equivalent
  JSON, sequential drift and concurrent same-fingerprint/different-continuation
  materialization. No secret value may appear in the exception/repr.

## Required fresh gates

- New re-review tests: zero failures after a recorded RED.
- Complete Task 7 focused ledger/schema/upgrade command.
- Lifecycle/API/UI regression command used in Task 7 report.
- Full unit suite, then full integration suite (never parallel on `.pytest-tmp`).
- Offline PostgreSQL DDL compile/migration test.
- `uv run ruff format --check .`
- `uv run ruff check .`
- mypy for every affected source file.
- `git diff --check`
- No provider network calls.

Report all warnings and distinguish pre-existing warnings from new failures.
