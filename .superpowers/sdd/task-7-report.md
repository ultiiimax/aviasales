# Task 7 implementation report

Status: implementation complete; pending independent review and not accepted yet.

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

## GREEN evidence

The operation-ledger race, ownership and RPM regressions are green:

```text
uv run pytest tests/unit/persistence/test_agent_operation_repository.py -q

26 passed in 8.10s
```

The evidence repository, including concurrent/deterministic dedupe, is green:

```text
uv run pytest tests/unit/persistence/test_agent_evidence_repository.py -q

23 passed
```

The final required gates are green:

```text
focused Task 7 + migration/pre-v1 upgrade: 77 passed in 29.41s
Task 4-6 regression gate:                 114 passed in 36.60s
full unit suite:                          826 passed in 181.54s
separate integration suite:               4 passed in 4.91s
targeted mypy:                             no issues in 3 source files
global ruff format --check:                281 files already formatted
global ruff check:                         all checks passed
git diff --check:                          clean
```

The final full unit run reports only two existing lxml deprecation warnings;
there are no test failures. No provider network I/O was performed.
