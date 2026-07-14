# Task 5 Report — Approval-Gated Plan Lifecycle API

Status: implemented; pending independent review.

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
