# Task 5 Report — Approval-Gated Plan Lifecycle API

Status: review hardening implemented; pending independent re-review.

## RED

Exact command:

```powershell
uv run pytest tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py -q
```

Result on 2026-07-14: exit 1, one collection error, zero tests executed. The
expected root cause was `ModuleNotFoundError` for the absent
`flight_hunter.application.agent_lifecycle` production module. Production files
were untouched at that point.

## Decisions

- Every persisted route authenticates a real bearer session and derives the
  household, user and approval session ID from that session.
- The lifecycle service owns transition commits. Route handlers do not open
  savepoints or contain transition policy.
- Create/edit/clone only parse, freeze local catalog/capability/cost snapshots
  and persist revisions; an injected counting provider remains at zero calls.
- Execute binds the exact plan/revision/number/hash, derives approval budgets and
  strategies from immutable revision evidence, checks the versioned hidden-city
  warning, then creates approval/run and consumes the revision in one commit.
- Results remain a typed empty `not_ready` response until later worker/evidence
  tasks create real execution evidence.

## GREEN

Verification on 2026-07-14:

```powershell
uv run pytest tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_auth_api.py -q
```

Result: 23 passed in 5.42s.

```powershell
uv run pytest tests/unit/application/test_agent_intent.py tests/unit/application/test_agent_planning.py tests/unit/application/test_agent_scope.py tests/unit/application/test_agent_capabilities.py tests/unit/domain/test_agent_search.py tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py -q
```

Result: 146 passed in 9.19s.

```powershell
uv run pytest tests/unit -q
```

Result: 712 passed in 60.69s. The 23 warnings come from existing async test
cleanup and lxml deprecations; there were no failures.

```powershell
uv run pytest tests/integration -q
```

Result: 4 passed in 3.32s.

Named-file `ruff check` and `mypy` gates passed without findings. The final
focused rerun passed 23 tests in 5.31s; global `ruff format --check .` reported
276 files already formatted and global `ruff check .` passed without findings.

## Concerns

- Worker/provider execution and web UI are deliberately outside this slice.

## Review hardening addendum (2026-07-14)

The review returned six Important and two Minor findings. Production remained
unchanged while the focused review tests were added. The exact lifecycle/API/auth
command then produced `14 failed, 22 passed in 8.59s`. Those failures reproduced
the missing outer rollback, duplicate unchanged clone hash, PATCH text
contamination, missing post-lock idempotency lookup and binding, diagnostic
leakage, open selection/result schemas, and incomplete error mapping.

The service now opens one outer SQLAlchemy transaction before every lifecycle
read or mutation in create/edit/clone/execute/cancel (and expiry-mutating GET).
Any mapped or unknown exception rolls it back; successful exits commit once.
Fault injection covers approval insertion, successor/clone insertion and cancel
status mutation, and proves the session is reusable.

Clone revisions carry canonical approval generation and refreshed-expiry evidence
inside the hashed plan payload. The repository assigns the generation while it
holds the latest-revision write boundary, preserving Task 4's
`(plan_id, content_hash)` uniqueness. Execute performs a fast idempotency lookup,
locks the revision, repeats the household lookup, verifies exact plan/revision
binding, and converges under a synchronized two-session SQLite race.

New PATCH text preserves only independent passenger/currency/strategy settings;
route, legs, dates and trip shape are reparsed from the replacement text plus
explicit selections. Agent selection payloads are closed typed Pydantic models,
and agent-path validation plus direct parser/builder input failures return
`agent_plan_invalid_input` without raw exception text.

Run responses map internal failure diagnostics through a closed public allowlist.
Persisted `error_message`, provider references, continuation values, signatures
and tokens remain internal. Unknown error codes become `agent_run_failed` with no
public message. Results expose only the literal `not_ready` state and evidence
availability until a typed evidence contract exists.

Fresh verification before the final commit:

- Focused lifecycle/API/auth: `38 passed in 8.43s`.
- Task 3/4 regression set: `146 passed in 8.68s`.
- Full unit suite: `727 passed, 4 warnings in 56.70s`.
- Full integration suite: `4 passed in 3.30s`.
- Named source mypy: no issues in five source files.
- Named Ruff check and format: clean across eight changed code/test files.
- Final focused rerun: `38 passed in 8.04s`.
- Global format: `276 files already formatted`; global Ruff passed.
- Global mypy: no issues in 114 source files.
- `git diff --check`: clean.

The unit warnings are aiosqlite event-loop shutdown races and two existing lxml
deprecations; there were no test failures. Task 6 execution, provider calls and
web UI remain outside this hardening pass.

## Final boundary addendum (2026-07-14)

Two Important findings remained. With production still at `3dca87c`, the
expanded lifecycle/API/auth command produced `7 failed, 39 passed in 9.64s`.
The failures proved that broad lifecycle catches misclassified internal builder
and repository exceptions, while list/get/latest/results left SQLAlchemy
autobegin transactions open on success and failure.

`IntentInputError` now marks only the deterministic parser input phase. The
optional overlay path runs outside that classification boundary. Lifecycle
methods catch only this typed input error; internal parser overlay, builder and
repository `TypeError`/`ValueError` probes roll back and propagate unchanged.
Responses therefore keep the stable invalid-input code for real user input
without turning internal failures into 422 responses or exposing raw messages.

Every public lifecycle read now uses the same service-owned outer transaction as
mutators. Success ends autobegin, errors roll back, and the same service/session
can immediately run a valid mutator. Parameterized SQLite coverage includes
get plan, list runs, get run, latest run and results, plus a failed read.

Fresh verification:

- Focused lifecycle/API/auth: `47 passed in 9.44s`.
- Task 3 parser + Task 4 repository regressions: `106 passed in 9.02s`.
- Full unit suite: `736 passed, 3 warnings in 56.65s`.
- Full integration suite, separate process: `4 passed in 3.05s`.
- Global format: `276 files already formatted`.
- Global Ruff: passed.
- Global mypy: no issues in 114 source files.

The three unit warnings are one existing aiosqlite shutdown race and two lxml
deprecations. No ledger, worker, provider execution or Task 6 code changed.
