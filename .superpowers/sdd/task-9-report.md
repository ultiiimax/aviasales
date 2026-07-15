# Task 9 — durable calendar/exact worker

Status: accepted by independent review; zero Critical, Important or Minor
findings remain.

## Required tests-only RED

Production sources and Compose were unchanged when this command ran:

```text
uv run pytest tests/unit/application/test_agent_execution.py tests/unit/ops/test_worker_command.py tests/unit/api/test_agent_plan_api.py tests/unit/ops/test_compose_config.py -q
```

Exit code: `1`.

Captured output:

```text
EEEEEEEEEEEEEEEFFF...FF...FF...F.........F....F..FF                      [100%]

ModuleNotFoundError: No module named 'flight_hunter.application.agent_execution'
AssertionError: assert 'agent' in ('browser', 'watch', 'deal', 'telegram', 'maintenance')
TypeError: run_once() got an unexpected keyword argument 'agent_executor_factory'
KeyError: 'stage_counts'
ValueError: substring not found  # dedicated agent-worker Compose service

FAILED tests/unit/ops/test_worker_command.py::test_agent_worker_role_has_stable_parsing_heartbeat_and_idle_counters
FAILED tests/unit/ops/test_worker_command.py::test_agent_worker_role_processes_one_durable_operation_and_commits_progress
FAILED tests/unit/ops/test_worker_command.py::test_worker_processes_queued_browser_observation_jobs
FAILED tests/unit/ops/test_worker_command.py::test_worker_loop_can_stop_after_idle_iteration
FAILED tests/unit/ops/test_worker_command.py::test_worker_loop_stops_after_signal_aware_idle_sleep
FAILED tests/unit/ops/test_worker_command.py::test_worker_cleans_expired_live_observation_state
FAILED tests/unit/ops/test_worker_command.py::test_worker_drain_skips_new_claims_but_runs_maintenance
FAILED tests/unit/api/test_agent_plan_api.py::test_execute_requires_real_bearer_and_never_trusts_legacy_household_headers[asyncio]
FAILED tests/unit/api/test_agent_plan_api.py::test_run_endpoints_never_expose_internal_error_diagnostics[asyncio]
FAILED tests/unit/api/test_agent_plan_api.py::test_openapi_exposes_the_complete_agent_plan_lifecycle_surface[asyncio]
FAILED tests/unit/ops/test_compose_config.py::test_local_v1_package_compose_and_image_contracts
FAILED tests/unit/ops/test_compose_config.py::test_ci_covers_linux_windows_browser_and_image_without_live_credentials
ERROR tests/unit/application/test_agent_execution.py::test_exact_run_transitions_queued_running_completed_through_start_and_poll[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_flexible_calendar_shortlists_by_amount_recency_and_stable_tie_break[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_restart_resumes_saved_exact_cursor_and_start_handoff_is_atomic[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_existing_confirmed_evidence_is_reused_without_duplicate_on_poll_retry[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_cancel_before_next_claim_and_expired_deadline_make_zero_new_provider_calls[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_http_and_logical_budgets_stop_before_unreserved_provider_io[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_401_403_and_schema_failures_are_terminal_and_body_free[asyncio-failure0-provider_auth]
ERROR tests/unit/application/test_agent_execution.py::test_401_403_and_schema_failures_are_terminal_and_body_free[asyncio-failure1-provider_forbidden]
ERROR tests/unit/application/test_agent_execution.py::test_401_403_and_schema_failures_are_terminal_and_body_free[asyncio-failure2-provider_schema]
ERROR tests/unit/application/test_agent_execution.py::test_429_uses_retry_after_and_does_not_hide_an_internal_retry[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_transport_and_5xx_retries_are_new_bounded_leases_and_http_attempts[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_open_circuit_makes_zero_call_and_successful_half_open_probe_closes_it[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_useful_confirmed_evidence_plus_failure_is_partial_but_none_is_failed[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_household_scope_and_private_continuation_never_cross_public_boundary[asyncio]
ERROR tests/unit/application/test_agent_execution.py::test_exact_poll_uses_private_passenger_binding_not_mutable_operation_input[asyncio]

12 failed, 24 passed, 15 errors in 23.30s
```

The RED is causal: the executor module, worker lane/seam/counters, progress projection,
dedicated Compose service, and CI image build target do not exist yet.

## Implemented scope

- Durable keyset worker scan across all households while every claim and write
  stays household-bound.
- Approved exact start/poll and flexible calendar shortlist execution with
  immutable route/date/passenger/currency binding and server-private continuation.
- Commit checkpoint after circuit permit + HTTP reservation and before transport;
  retries are separate bounded leases and Aviasales client retries stay disabled.
- Logical/HTTP budgets, approved/current minimum RPM, poll cadence, Retry-After,
  cancellation, deadlines, lease expiry and closed/open/half-open circuit behavior.
- Sanitized LIVE discovery/confirmed evidence, confirmed-only ranking and honest
  completed/partial/failed/cancelled stage/run projection.
- Bulk public run counters and budgets without selecting or serializing private
  continuation/error diagnostics; safe typed errors are allowlisted and unknown
  values collapse to `agent_run_failed` / `Search failed.`.
- Dedicated Compose `agent-worker`, heartbeat/counters, validated provider wiring,
  CI image build target, environment example and operator documentation.

The existing `0024_agent_execution_ledger` schema covers the slice. Task 10/11
route-composition work was not started. No live provider call was made and the
provider contract verification date was not changed.

## GREEN verification

```text
Required four-file gate (independently rerun by root):
110 passed in 49.13s

tests/unit/application/test_agent_execution.py:
48 passed in 25.52s

tests/unit/ops/test_worker_command.py (unique basetemp):
18 passed in 16.94s

tests/unit/persistence/test_agent_run_repository.py (unique basetemp):
51 passed in 9.57s

tests/unit/api/test_agent_plan_api.py:
41 passed in 7.89s

tests/unit/ops/test_compose_config.py:
3 passed in 0.06s

tests/unit/ops/test_security_scan.py:
2 passed in 0.07s

tests/integration:
4 passed in 7.09s

uv run mypy src:
Success: no issues found in 117 source files

uv run ruff check <Task 9 changed Python files>:
All checks passed!
```

## Independent acceptance and release-gate hardening

The initial independent review found approval/revision, budget, circuit,
cancellation, chronology, continuation-integrity, freshness, public-projection
and worker-boundary gaps. They were fixed test-first. A fresh specification
review then found four remaining Important issues: calendar evidence identifiers
were not operation-namespaced, private continuation state was not fully bound to
the handoff identifier, flexible round trips could accept an out-of-surface
return, and stale provider replay could be labelled LIVE. All four were fixed;
the root verification also added and closed the rolling-window chronology case.

Clean-environment verification exposed two release-gate defects outside the
executor flow. The optional Crawl4AI import depended on a warm mypy cache, and
one API log test accidentally used the default database when `DATABASE_URL` was
absent. Both now have deterministic regression coverage without making
Crawl4AI mandatory or touching the user's database.

Final verification on the frozen reviewed tree:

```text
Independent review: ACCEPT — 0 Critical / Important / Minor
Full unit suite with a brand-new temporary DATABASE_URL: 1205 passed
Task 9 focused suite: 187 passed
Regression suite: 263 passed
Integration suite: 4 passed
Security tests: 2 passed
Security scanner: ok=true, finding_count=0
Fresh-cache mypy: Success, 118 source files
Ruff format: 286 files already formatted
Ruff check: All checks passed
Alembic: 0024_agent_execution_ledger (head), one head
Compose config: valid with process-only validation secret
```

The reviewer verified combined raw hash
`50d057a794825ec742fb2ca7ba7642ace8aa6b91b648044226fe3f695b949f71`.
The accepted executor hardening is committed on local `main` as `c0d7de6`; the
clean-environment release-gate fixes are `98147bc`. No live provider call was
made and the local user database was not used or modified.

Status: accepted; Task 10 coverage breadth is the next slice.
