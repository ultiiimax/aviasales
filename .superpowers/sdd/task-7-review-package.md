# Final re-review package: 2f74ba0..0babb2a

## Scope

Independent re-review of Task 7, "Add the Durable Operation and Evidence
Ledger". The accepted Task 6 baseline is `2f74ba0`; fixed implementation head
is `0babb2a`. Review the complete implementation range and specifically verify
fix ranges `bb41bd9..3b0fe4b`, `3b0fe4b..97f2ac2`, and
`97f2ac2..0babb2a`.

## Commits

```text
bb41bd9 feat: add agent execution ledger
3b0fe4b fix: harden agent execution ledger invariants
97f2ac2 fix: make agent ledger outcomes idempotent
0babb2a fix: prevent private continuation traceback leaks
```

## Primary requirements

- Migration 0024 and Core metadata stay structurally equivalent and preserve
  0023/pre-v1 data. Historical runs receive zero new budgets; new runs copy the
  immutable approved revision estimates.
- All writes preserve household/run/stage ownership and caller-owned transaction
  boundaries. SQLite concurrency is real, PostgreSQL paths execute no SQLite SQL.
- Operation materialization, lease claim/recovery, retry, HTTP-attempt reservation,
  provider-wide RPM, and persistent circuit/half-open probe state are atomic and
  restart-safe. Cancelled, terminal, and deadline-expired runs start no new work.
- Logical-operation and HTTP-attempt budgets cannot be exceeded or silently
  conflated. Exact start/poll rows share one logical workflow root.
- Public records never expose private provider continuation state. Attempt rows
  contain no payload, token, signature, marker, cookie, signed URL, or PII.
- Discovery signals, confirmed evidence, composed candidates, and ranking
  snapshots remain distinct, append-only, idempotent, and household scoped.
  Discovery IDs cannot enter final ranking.
- No new TODO, `pass`, `NotImplementedError`, fake return, float money, naive
  datetime acceptance, or unbounded provider retry exists in the affected flow.

## Required prior-finding rechecks

- Provider-neutral operations consume no false logical budget; only
  `exact_poll` requires an explicit exact-workflow root. Unsupported suggest
  materialization fails with a stable code until the planner budgets it.
- Cancellation/deadline reconciliation terminalizes pending/retry and expired
  leases, while the active owner has an owner-CAS skip transition before I/O.
- Success references are type-, household-, run-, and stage-owned; exact start
  and non-final polls hand off to a concrete operation result rather than a fake
  confirmed offer.
- HTTP reservation is idempotent per operation claim attempt, returns the same
  reservation identity, derives the attempt kind, and never double-spends.
- Circuit permits are opaque, one-shot, generation-bound, atomically consumed
  with reservation, and immune to stale takeover callbacks. Rate/budget denial
  does not burn a valid permit.
- Exactly one immutable scope snapshot exists per run; same fingerprint is
  idempotent and a different fingerprint gives a stable conflict.
- Private continuation/permit data is absent from repr/public records. Public
  contexts use explicit allowlists and reject credential aliases, PII and all
  URI forms. Retry jitter is bounded and `Retry-After` remains a hard floor.

## Required second-review rechecks

- Actual migration 0024 and Core PostgreSQL DDL use boolean predicates valid for
  PostgreSQL; neither logical-shape checks nor partial indexes emit boolean
  `= 0/1` comparisons.
- A provider HTTP reservation records exactly one circuit outcome. Identical
  sequential/concurrent replay is idempotent; success/failure conflicts are
  rejected and non-transient outcomes are persisted.
- Calendar discovery and exact confirmation evidence must match the producing
  operation provider. Composition/ranking remain deliberately provider-neutral.
- Exact handoff binds a DB-backed predecessor atomically with source completion.
  Orphan polls are not claimable; terminal/leased/retry targets, backward links,
  cycles, fan-in and fan-out are rejected.
- Same-fingerprint materialization compares canonical server-private
  continuation state. Equivalent reordered JSON reuses; any private drift gets
  a secret-safe stable conflict.
- Concurrent/stale-read duplicate materialization must not expose stored or
  requested continuation through `str`, `repr`, formatted traceback,
  `__cause__`, `__context__`, raw SQL parameters, or an unclassified
  `IntegrityError`. The stable conflict is raised outside the DB exception
  handler.

## Files and evidence

Use:

```powershell
git diff --stat 2f74ba0..0babb2a
git diff 2f74ba0..0babb2a -- migrations/versions/0024_agent_execution_ledger.py src/flight_hunter/persistence/models.py
git diff 2f74ba0..0babb2a -- src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py
git diff bb41bd9..3b0fe4b -- tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py
git diff 3b0fe4b..97f2ac2 -- migrations/versions/0024_agent_execution_ledger.py src/flight_hunter/persistence/models.py src/flight_hunter/persistence/agent_repositories.py tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_alembic_upgrade.py
git diff 97f2ac2..0babb2a -- src/flight_hunter/persistence/agent_repositories.py tests/unit/persistence/test_agent_operation_repository.py
cat.exe .superpowers/sdd/task-7-report.md
```

Implementation gates recorded on the exact commit:

```text
traceback regression: 3 passed
second re-review:     27 passed
focused Task 7:       163 passed
lifecycle/API/UI:     77 passed (127 extended)
full unit:            912 passed
integration:          4 passed
PostgreSQL 0024 DDL:  1 passed
Ruff format/check:    clean (281 files)
mypy:                 clean (2 affected source files)
git diff --check:     clean
```

## Review output

Return findings grouped as Critical, Important, and Minor, with exact file/line,
failure scenario, and concrete fix. Run any focused tests needed to validate a
finding. Accept only if Critical and Important are empty; report Minor findings
too rather than silently accepting them.
