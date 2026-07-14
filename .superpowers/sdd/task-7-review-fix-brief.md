# Task 7 independent-review fix brief

Baseline: `bb41bd9` on local `main`. Work directly on `main`. Do not start Task
8 and do not call a provider. Read AGENTS.md, the approved design/plan, Task 7
brief/report/review package, and the independent review verdict delivered to
the root agent. This is one test-first review-fix cycle. Task 7 remains
unaccepted until the same independent reviewer accepts the fix range.

## Mandatory RED first

Before production edits, add focused tests that reproduce all findings below
and record exact RED commands/output in `.superpowers/sdd/task-7-report.md`.
Prefer real independent SQLite sessions for races. Tests must fail for the
reviewed reason, not for an unfinished fixture.

## 1. Independent non-network operations versus logical roots

The approved logical budget is exactly calendar + exact search work. A
provider-neutral `scope_freeze`, `comparison`, `composition`, `ranking`, or
`analysis/report` operation must be materializable with
`consumes_logical_unit=False` and without a fake consuming root. Only a true
child workflow row such as `exact_poll` requires the exact-start logical root.

Make this structural rather than inferred. Add an explicit nullable logical
root operation reference (or an equally strong typed relationship), validate
same household/run/stage/provider/fingerprint and compatible root/child kinds,
and keep the partial unique logical-root budget index. Exact start consumes one
logical unit; all polls share it and consume none. Independent internal rows
consume none and have no root. Reject forged/missing/cross-run/cross-provider
roots and invalid kind/consumption combinations. Preserve deterministic
materialization and caller-owned rollback.

## 2. Cancellation/deadline reconciliation

No inactive run may retain permanently actionable or permanently leased work.
Before `claim_next_operation` returns for cancel-requested/cancelled/terminal or
deadline-expired runs, atomically reconcile pending/retry rows and expired
leases to stable terminal operation states with typed error codes. An active
lease may remain only while its current owner can cooperatively terminate it.
Add an owner/lease CAS transition for the current worker to mark a claimed
operation skipped when cancellation/deadline is observed before I/O. A stale
owner must not terminate a reclaimed lease. Preserve confirmed partial results.

Cover cancellation, deadline, terminal run, final-attempt crash, unexpired
owner cleanup, expired cleanup, and stale-worker rejection.

## 3. Typed and owned result references

`mark_operation_succeeded` must validate, in the same caller-owned write
transaction, that `result_id` exists in the table selected by `result_type` and
belongs to the same household/run (and stage where that result has a stage).
Enforce a closed operation-kind/result-type matrix. Reject missing, discovery
masquerading as confirmed, cross-run, cross-household, cross-stage, self, and
incompatible-kind references with stable non-leaking codes.

Support the future resumable exact start/poll handoff honestly: if a start or
non-final poll succeeds by materializing a next operation, add a typed
same-workflow operation result reference and validate the parent/child link.
Do not invent a confirmed-offer reference for a start response. Final exact
poll may reference confirmed evidence. Scope/calendar/composition/ranking map
to their actual stored result types.

## 4. Idempotent HTTP reservation per claim attempt

Persist a positive operation/claim attempt number (or equivalent deterministic
reservation key) on each provider-attempt row and add a DB uniqueness invariant
for one reservation per operation claim attempt. A repeated reservation call
for the same live lease must return the existing typed reservation without
adding an attempt row or incrementing run/operation counters. A new retry lease
increments the operation attempt and may reserve a new unit.

Bind/validate `attempt_kind`: initial exact start/calendar is `start`, initial
exact poll is `poll`, and a reclaimed attempt is `retry`; provider-neutral
operations cannot reserve HTTP. Test concurrent duplicates, ambiguous repeat,
budget=1, RPM accounting, crash persistence, stale owner, and caller rollback.
Expose enough typed result state (reservation ID/reused flag if needed) so Task
9 cannot mistake a replay for authorization for a second upstream call.

## 5. One-shot circuit permit bound to reservation and outcome

Replace worker-name-only half-open authorization with a server-private opaque
permit token/generation bound to provider and a unique operation claim attempt.
The token must not appear in public DTOs or reprs. Exactly one half-open permit
is issued/usable. `reserve_http_attempt` must atomically validate and consume
the permit with rate/budget/attempt persistence; missing/stale/open-circuit
permits mutate no counters. Rate/budget denial must not burn a probe.

Success/failure callbacks for half-open state must carry the same permit and
only the current generation may close/reopen the circuit. Late callbacks from
probe A after takeover by B are ignored/rejected without changing B's state.
Closed-state permits must be rechecked at reservation so a circuit opened after
the preliminary check starts no new I/O. A duplicate reservation for an
already persisted operation attempt follows the idempotency contract and never
consumes the probe twice.

Test repeated same-worker acquisition, A-expiry/B-takeover/late-A failure,
valid-B success, stale-A reservation, closed-to-open race, rate/budget denial,
restart persistence, and token/repr secrecy.

## 6. Exactly one frozen scope snapshot per run

The run scope is first-discovery immutable. Change the schema invariant to one
scope snapshot per `run_id`, not one per `(run_id, fingerprint)`. Appending the
same fingerprint returns the original immutable row. A different fingerprint
for that run raises a stable conflict; two concurrent different snapshots
cannot both win. Validate IDs/timestamps/sanitized payload and preserve
household isolation/caller rollback.

## 7. Private repr and allowlisted ledger JSON

`OperationSpec`, `NewAgentRunOperation`, every circuit permit/token DTO, and
`ServerPrivateOperationLease` must hide private continuation/token fields from
`repr` (`field(repr=False)` plus a safe custom repr where useful). Public record
types structurally omit them.

Do not rely on a substring denylist as the only data boundary. Introduce
explicit, context-appropriate allowlisted/typed validation for operation input,
scope, discovery evidence, confirmed itinerary evidence, composed evidence,
ranking, and private continuation shapes. Future schema extension must be an
explicit code change. At minimum reject neutral aliases and nested/list values
for credentials/PII, including `api_key`, credential/access keys, email/phone/
traveler contact, URI schemes such as `mailto:`, `data:`, `javascript:`, normal
and mixed-case HTTP(S), protocol-relative URLs, and leading whitespace. Keep
safe normalized route/date/segment/ranking fields working. Never store raw
provider DTOs, raw prompts, signed booking URLs, or provider secrets.

## 8. Jitter (review Minor, required for ideal release)

Add bounded backoff jitter for network/5xx retries as AGENTS.md requires. Keep
tests deterministic through an injected RNG or stable per-operation jitter key;
do not jitter provider `Retry-After` below its required time. Preserve maximum
delay and bounded attempts.

## Schema/migration rule

Task 7 is not accepted/released yet, so keep migration 0024 and matching Core
metadata equivalent while applying review corrections. Expand fresh-head,
0023-upgrade, metadata parity, constraint/index/FK and data-preservation tests.
Do not create an untracked schema divergence.

## Gates and completion

Run at minimum:

```powershell
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
uv run pytest tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run ruff format --check .
uv run ruff check .
uv run mypy src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/persistence/models.py
git diff --check
```

No TODO/pass/NotImplemented/fake return. Update Task 7 report with RED/GREEN,
decisions and warning audit. Keep IMPLEMENTATION_STATUS as pending re-review.
Commit all fixes/report/status as:

`fix: harden agent execution ledger invariants`
