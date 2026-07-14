### Task 7: Add the Durable Operation and Evidence Ledger

Implement directly on local `main`. Do not start Task 8 or perform provider
network I/O. Read the repository `AGENTS.md`, README/architecture/status, Task 7
in `docs/superpowers/plans/2026-07-13-agent-route-orchestrator.md`, sections
5.4, 5.5, 7.1, 11, 13 and 16.2 of the approved design, migration 0023, the
current agent repositories and their transaction-boundary tests before editing.
Use strict TDD: commit RED evidence before production implementation in the
task report; do not weaken Task 4-6 invariants.

**Primary files**

- Create `migrations/versions/0024_agent_execution_ledger.py`.
- Modify `src/flight_hunter/persistence/models.py`.
- Modify `src/flight_hunter/persistence/agent_repositories.py`.
- Create `src/flight_hunter/application/agent_operations.py`.
- Modify lifecycle/repository DTO files only where required to initialize the
  approved run budgets; document any extra file in the report.
- Create `tests/unit/persistence/test_agent_operation_repository.py`.
- Create `tests/unit/persistence/test_agent_evidence_repository.py`.
- Create `tests/unit/application/test_agent_operations.py`.
- Modify `tests/unit/persistence/test_alembic_upgrade.py`.
- Modify `tests/integration/test_upgrade_from_pre_v1.py`.
- Update `IMPLEMENTATION_STATUS.md` and `.superpowers/sdd/task-7-report.md`.

**Required persistent surface**

Add forward-only schema and matching SQLAlchemy Core metadata for:

- `agent_plan_stages`;
- `agent_run_operations`;
- `agent_provider_rate_locks`;
- `agent_provider_http_attempts`;
- `agent_provider_circuit_state`;
- `agent_run_scope_snapshots`;
- `agent_discovery_signals`;
- `agent_confirmed_offer_evidence`;
- `agent_composed_route_candidates`;
- `agent_ranking_snapshots`.

Add the immutable approved logical-operation and HTTP-attempt budgets plus
consumed counters needed by the ledger to `agent_plan_runs`. New runs must copy
the exact approved revision estimates into those budgets. Historical runs from
0023 must upgrade safely and honestly: a zero historical budget/counter is
acceptable if it prevents new I/O; never invent completed work. Keep consumed
counters non-negative and never above their budgets. Preserve all existing
0023 rows, approval/run constraints and states.

Use explicit enums/literals and checks for operation/stage/circuit statuses.
Operation status is `pending | leased | retry_wait | succeeded | failed |
skipped`. Store aware UTC datetimes only. Money is integer minor units plus ISO
currency. Unknown baggage/protection/transfer/visa data remains nullable or an
explicit unknown enum, never false/zero.

`agent_run_operations` must include household/run/stage/provider ownership,
typed operation kind, deterministic operation fingerprint, a separate logical
workflow fingerprint, a `consumes_logical_unit` flag, sanitized immutable input,
server-private continuation state, lease owner/expiry, attempt/retry state,
HTTP-attempt consumption, stable result reference/error code and timestamps.
Enforce unique `(run_id, operation_fingerprint)`, the SQLite/PostgreSQL partial
unique logical-root index, and the claim index from the plan. Start and all poll
rows for one exact workflow share a logical fingerprint; only its root consumes
one logical unit.

Provider-attempt rows are append-only and contain no request/response payload,
signature, marker, token, cookie, signed URL or PII. Index `(provider_id,
reserved_at)`. The provider rate-lock row serializes the sliding-window read and
insert in the same write transaction across local workers and all runs. Circuit
state is persistent and stores transient failure count, open/cooldown state and
one compare-and-swap half-open probe lease.

Discovery signals and confirmed evidence are distinct tables and distinct
return types. Confirmed evidence stores source, aware `observed_at`, freshness,
passenger basis, amount minor/currency when known, sanitized itinerary evidence
and deterministic fingerprint. Observations are append-only: a retry may
deduplicate by fingerprint but must never update an existing observation.
Composed candidates reference confirmed evidence only. Ranking snapshots may
reference confirmed evidence/composed candidates only; explicitly reject a
discovery-signal ID in application/repository validation. Ranking creates a new
snapshot and never rewrites evidence.

Public/delivery-safe operation records must not have a
`private_continuation_json` field at all. A narrowly named server-private lease
record/accessor may carry the continuation for a worker. Never log/return it.
Canonical JSON must be deterministic and recursively sanitized; do not accept
raw provider DTOs as evidence records.

**Application behavior**

Implement typed operation scheduling and persistent circuit policy in
`agent_operations.py`:

- stable SHA-256 fingerprints from operation kind plus canonical immutable
  input, independent of dictionary order;
- idempotent materialization of an identical `(run, fingerprint)`;
- atomic lease claim; two concurrent claimers cannot receive one operation;
- expired lease recovery to retryable work without losing attempt counts;
- retry scheduling with aware `next_retry_at` and bounded attempts;
- typed `AttemptReservationStatus`: `reserved`, `rate_limited`,
  `budget_exhausted`, with `retry_at` only where meaningful;
- reserve a run budget unit and append provider attempt before every actual
  start/poll/retry I/O; a crash after reservation leaves it consumed;
- rolling provider RPM counts every actual attempt across all households/runs,
  while logical poll rows do not inflate the logical-operation budget;
- terminal auth/403/schema classifications do not loop; 429 uses Retry-After;
  network/5xx use bounded retry;
- repeated transient failures open one persistent circuit; open denies I/O;
  after cooldown exactly one concurrent half-open probe is admitted; success
  closes/resets it.

Do not implement an actual provider gateway in this task. The output is the
durable ledger and typed scheduling primitives Task 8/9 will consume.

**Mandatory RED/negative/concurrency tests**

Write failing tests first for all of these:

1. Two concurrent sessions/claimers cannot lease the same operation.
2. An expired lease is recovered; a live lease is not stolen.
3. Concurrent identical `(run_id, fingerprint)` materializes once.
4. Stable fingerprints ignore mapping order but change on typed immutable input.
5. HTTP reservation is atomic; exhausted run budget starts no attempt row.
6. A reservation committed before a simulated crash remains consumed.
7. The provider RPM window counts start, every poll and retry across different
   runs; rate limited and budget exhausted are distinct typed results.
8. Exact start/polls share one logical fingerprint and only one root consumes a
   logical budget unit.
9. Circuit open/cooldown survives a new repository/service instance and admits
   only one concurrent half-open probe.
10. Candidate/evidence retry deduplicates deterministically without update.
11. A discovery ID is rejected from a ranking snapshot.
12. Household A cannot claim/read evidence, operations, stages or results of B.
13. Public records have no private continuation attribute/serialized key.
14. Sanitization rejects secret-like nested fields and provider payload leakage.
15. Naive datetimes, invalid status transitions, invalid money/passenger bases,
    counter overflow and consumed > budget fail before or at the DB invariant.
16. 0023 -> 0024 and pre-v1 -> head upgrades preserve existing household,
    plan, revision, approval and run rows; fresh metadata equals migration head.
17. Existing Task 4 lifecycle/concurrency/idempotency tests remain green.

Use independent SQLite files/sessions for real concurrency. Do not fake
concurrency with sequential calls in one session. Repositories must never commit
or roll back a caller-owned physical transaction. If a SQLite write lock needs
`BEGIN IMMEDIATE`, follow the reviewed Task 4 boundary: acquire it only for a
repository-owned physical transaction and reject unsupported nested SQLite
savepoints before mutation. PostgreSQL paths must not run SQLite-only SQL.

**Focused gate**

```powershell
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
uv run pytest tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py -q
uv run mypy src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/persistence/models.py
uv run ruff format --check .
uv run ruff check .
```

Then run the full unit suite and separate integration suite. Do not rely on the
known combined AnyIO cross-suite failure as an excuse for a focused failure.
Run migration head/fresh-metadata checks and `git diff --check`.

**Completion**

No TODO/pass/NotImplemented/fake return in this flow. Update the Task 7 report
with exact RED and GREEN evidence, migration/backfill decisions, transaction
ownership, public/private record split and known warnings. Mark implementation
complete but pending independent review; do not check Task 7 as accepted.
Commit all Task 7 production/tests/docs as:

`feat: add agent execution ledger`
