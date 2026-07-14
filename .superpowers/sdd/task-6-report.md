# Task 6 Report: One Approval-Gated Agent Plan Builder

Status: review fixes complete; pending independent re-review.

## Result

Free text, all seven compatibility presets, and the web assistant now create the
same durable `AgentLifecycleService` plan revisions. Neither compatibility path
calls the flight provider. The provider boundary remains reachable only through
the bearer-authenticated execute endpoint with the exact plan ID, revision ID,
revision number, content hash, and a fresh idempotency key.

The public plan response contains a typed, sanitized summary derived from the
immutable revision snapshots: requested and frozen scope, expanded date bounds,
passengers, coverage, strategies, preset analysis modes, hidden-city state,
provider/capability/cost versions, RPM, estimates, deadline, and expiry. Raw
canonical payloads and provider secrets are not exposed.

## Delivered behavior

- Preserved all seven preset IDs and the `/api/v1/agent/plan` and
  `/api/v1/agent/chat/turn` compatibility paths.
- Added typed preset edits for ±3 days, 150 km nearby airports, route strategies,
  and analysis modes; every path delegates to the same parser, scope freezer,
  capability registry, estimator, repository, and lifecycle.
- Split compatibility authentication reads from lifecycle mutation sessions so
  SQLite never enters the forbidden nested-transaction path.
- Rendered an accessible durable plan/run card with honest draft, partial,
  failed, cancelled, provider-error, and unknown-data states.
- Persisted only a versioned `plan_id` in local storage. Reload fetches the
  household-scoped plan and latest run; a missing plan clears the key.
- Made plan edits and clarification actions create successor revisions with
  `PATCH`; execute is only bound to the explicit execute button.
- Restricted execute to executable `awaiting_approval` revisions. Hidden-city
  execution stays disabled until Task 11 supplies its separate risk
  acknowledgement.
- Restricted quick-to-full cloning to consumed, expired, or superseded quick
  revisions and always uses a fresh idempotency key.
- Polls queued/running runs with bounded backoff and allows cancellation only
  from queued/running states.
- Removed the compatibility one-shot search/date-matrix/watch branch.

## Independent review fixes

The first independent review did not accept Task 6 and returned four Important
findings. All four are now covered test-first:

- Invalid chat `date_mode` and ISO dates return the same sanitized typed
  `422 agent_plan_invalid_input` lifecycle error as the canonical plan path;
  internal lifecycle details are not exposed.
- Empty or unsupported clarification actions enter edit mode, so the next
  assistant submission patches a successor revision of the current plan instead
  of creating a new aggregate.
- Logout, session expiry, and household session replacement invalidate every
  in-flight chat/plan/revise/edit/execute/clone/cancel/reload/poll response,
  remove sensitive plan/run state from the DOM, and disable plan controls.
- The assistant renders all seven compatibility presets without truncation.

A follow-up re-review found one additional Important session-swap race. It is
also fixed test-first:

- `refreshSessionState()` binds `/auth/me` to both the exact captured token and
  the captured agent-session generation. A late success or error from session A
  becomes a no-op after `storeSession(B)` and cannot overwrite B's auth UI or
  remove B's token.
- Initial signed-out bootstrap and current-session expiry now perform one full
  signed-out clear. The chained session-bound loader becomes a no-op without a
  token instead of clearing and bumping the generation a second time.

## Task 3 invariant vs. Task 6 Step 1

The Task 6 brief says a rolling-90 QUICK selection should show an estimate and an
approval button. That conflicts with the accepted Task 3 budget invariant: a
broad rolling-90 QUICK surface must not be clamped or made executable when its
actual logical operation count exceeds 60. The Task 3 invariant wins.

The rolling-90 card is therefore a durable, non-executable draft. It displays
the immutable actual calendar/exact/logical counts and limit from
`quick_budget_too_large`, and its execute button is disabled. The bounded ±3-day
case proves the positive estimated, approval-ready card path.

## Test-first evidence

Initial RED command:

```powershell
uv run pytest tests/unit/agent/test_chat.py tests/unit/agent/test_presets.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
```

Result on the old production path: `19 failed, 4 passed`. Failures covered the
one-shot chat flow, missing typed summary/preset edits, anonymous compatibility
behavior, and missing durable card.

Independent-review RED evidence:

```powershell
uv run pytest tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
uv run pytest tests/unit/api/test_web_ui.py::test_web_household_agent_actions_ignore_responses_from_old_session_generation -q
```

The first command failed `5` tests with `28` passing: two chat validation 500s,
the missing clarification edit transition, the missing signed-out reset, and
the five-preset truncation. The separate in-flight-session contract then failed
until every household-scoped async action captured and checked the session
generation.

Follow-up re-review RED evidence:

```powershell
uv run pytest tests/unit/api/test_web_ui.py::test_web_auth_refresh_is_bound_to_exact_session_identity tests/unit/api/test_web_ui.py::test_web_auth_refresh_clears_missing_or_current_session_only_once -q
uv run pytest tests/unit/api/test_web_ui.py::test_web_auth_refresh_clears_missing_or_current_session_only_once -q
```

The first command failed both contracts because auth refresh had no exact
session-identity guard and the signed-out path cleared twice. After guarding the
refresh itself, the second command remained RED on the chained bootstrap loader;
it passed only after the loader stopped repeating signed-out mutation.

Final verification on 2026-07-14:

```text
Focused Task 6 + auth: 49 passed
Full unit suite:       756 passed, 18 warnings
Integration suite:    4 passed
Ruff format/check:    passed (276 files)
Full mypy:            passed (114 source files)
Rendered web JS parse: passed (`new Function` syntax check)
git diff --check:     passed
```

The unit warnings are existing aiosqlite event-loop shutdown and lxml
deprecation warnings; there were no test failures. Provider test doubles record
zero calls before explicit execution in every compatibility and chat acceptance
test.

## Review note

This report records implementation and review-fix evidence only. Task 6 remains
unchecked in `IMPLEMENTATION_STATUS.md` until independent re-review accepts the
slice.
