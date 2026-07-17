# API-kit Agent Integration and UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the user's working Aviasales credentials safely, turn a complete natural-language request into an immediately started durable search, and polish the local UI around that single flow.

**Architecture:** Keep the existing Aviasales adapter, deterministic intent parser, immutable plan/revision lifecycle, durable worker operations, result projections and booking boundary. Add one narrow `AgentToolGateway` over those services, an optional schema-validated Codex CLI overlay that may only fill unresolved intent fields, and a secret-safe one-time API-kit importer. Keep the server-rendered FastAPI + vanilla HTML/CSS/JavaScript frontend and expose a tagged chat outcome instead of nullable state inference.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy asyncio, Alembic, Aviasales mobile HTTP adapter, vanilla CSS/JavaScript, pytest, Playwright Chromium.

## Global Constraints

- Work directly on the current local `main`, preserving unrelated user changes.
- Do not copy or import `api_kit/aviasales/client.py` into runtime code and never execute it during credential import.
- Never print or log signatures, markers, Android IDs, raw Codex stderr, provider continuations, proposal IDs or signed booking URLs.
- Do not expose Aviasales credentials or provider DTOs to Codex, the browser or the new gateway.
- A complete chat search is explicit permission for `search_execute`; watch creation uses a distinct action grant; booking remains a later candidate-specific click.
- Deterministic parsing, scope resolution and plan validation remain authoritative. The optional model cannot invent provider facts or override a resolved field.
- Do not create a standalone MCP server, another provider client, another ranking implementation or a frontend framework.
- Do not run the repository-wide test suite. Run only the focused checks named in this plan and one summary-only live smoke.
- Preserve honest `LIVE | RECENT | CACHED | STALE`, source, `observed_at`, passenger basis, baggage unknowns and risk visibility.

---

### Task 1: Add the secret-safe API-kit importer

**Files:**
- Create: `src/flight_hunter/ops/api_kit_import.py`
- Modify: `pyproject.toml`
- Create: `tests/unit/ops/test_api_kit_import.py`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ApiKitImportResult:
    configured: bool
    code: Literal["ok", "api_kit_invalid", "api_kit_env_write_failed"]

def import_aviasales_api_kit(
    *, api_kit_root: Path, env_path: Path
) -> ApiKitImportResult: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

CLI:

```text
flight-hunter-import-api-kit --path <api-kit-root> [--env <env-file>]
```

- [ ] Write one parameterized importer test covering: valid `keys.json` + matching AST literals, marker derivation from UTF-8 `ANDROID_ID`, conflicting signature, resolved path escape, redacted stdout/stderr, and unchanged `.env` after invalid input.
- [ ] Add a write-failure case that expects exit code `3`, stable stderr code and no secret/path leakage.
- [ ] Run `uv run pytest tests/unit/ops/test_api_kit_import.py -q`; expect failure because the importer does not exist.
- [ ] Resolve exactly `<root>/aviasales/keys.json` and `<root>/aviasales/client.py`; require both resolved regular files to remain below the resolved root.
- [ ] Parse JSON as data and Python with `ast.parse`; accept only string literals assigned to `X_SIGNATURE`, `MARKER` and `ANDROID_ID`; never import or execute the file.
- [ ] Treat JSON `x_signature` as authoritative and reject a conflicting literal `X_SIGNATURE`. Resolve marker as JSON `marker`, then literal `MARKER`, then `mobile_app.` + MD5 of the UTF-8 `ANDROID_ID` bytes.
- [ ] Validate signature as UUID text and marker as `mobile_app.[0-9a-f]{32}`.
- [ ] Atomically replace only `AVIASALES_SEARCH_ENABLED`, `AVIASALES_SEARCH_SIGNATURE` and `AVIASALES_SEARCH_MARKER` in `.env`, preserving unrelated lines and the existing final-newline convention.
- [ ] Print exactly `{"configured":true,"provider":"aviasales_search"}` on success. On failure print only stable codes, returning `2` for source validation and `3` for the atomic write boundary.
- [ ] Register `flight-hunter-import-api-kit = "flight_hunter.ops.api_kit_import:main"` and document one local invocation without real values.
- [ ] Run the focused importer test again; expect PASS.
- [ ] Commit this task as `feat: import local Aviasales API kit safely`.

### Task 2: Make the intent overlay real but subordinate

**Files:**
- Modify: `src/flight_hunter/agent/codex_cli.py`
- Modify: `src/flight_hunter/agent/chat.py`
- Modify: `src/flight_hunter/application/agent_intent.py`
- Modify: `src/flight_hunter/config.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `tests/unit/agent/test_codex_cli_adapter.py`
- Modify: `tests/unit/application/test_agent_intent.py`

**Interfaces:**

```python
class IntentOverlayProvider(Protocol):
    @property
    def model(self) -> str: ...
    def extract_intent(self, message: str) -> IntentDraft | None: ...

@dataclass(frozen=True, slots=True)
class IntentFieldDecision:
    value: object
    provenance: Literal["selection", "deterministic", "overlay"]

@dataclass(frozen=True, slots=True)
class IntentConstraint:
    kind: str
    value: object
    state: Literal["applied", "advisory", "unsupported"]
```

- [ ] Extend the existing validator test with one valid full overlay and focused invalid cases for unknown/provider-fact fields, wrong types and output larger than the configured byte bound.
- [ ] Add merge tests proving `selection > deterministic > overlay > clarification`, conflict diagnostics do not contain prompt text, and model failure leaves deterministic parsing unchanged.
- [ ] Run only `uv run pytest tests/unit/agent/test_codex_cli_adapter.py tests/unit/application/test_agent_intent.py -q`; expect the new cases to fail.
- [ ] Extend the strict overlay schema with origin/destination text, trip/date shape and hints, passenger mix, currency, nearby radius, requested strategies, baggage preference and explicit watch intent. Reject all unknown fields and provider facts.
- [ ] Execute `codex exec` only when enabled and available, using stdin, `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--sandbox read-only`, `--skip-git-repo-check`, `--output-schema`, an empty temporary cwd, a minimal allowlisted environment and bounded timeout/output.
- [ ] Ensure the subprocess environment excludes every `AVIASALES_*`, token/key variable and workspace path; discard raw stderr and classify failure with stable codes only.
- [ ] Merge overlay values only into fields the explicit selections and deterministic parse left unresolved. Record only stable conflict diagnostics with field and model version.
- [ ] Materialize baggage as `checked | carry_on | none | unspecified`; unknown offer evidence remains unknown. Mark each other recognized constraint `applied`, `advisory` or `unsupported`; block automatic execution only for material unsupported constraints.
- [ ] Wire the configured adapter into `create_app()` while retaining deterministic fallback when Codex is disabled, absent, times out or returns invalid JSON.
- [ ] Run the two focused test files again; expect PASS.
- [ ] Commit this task as `feat: add bounded Codex intent overlay`.

### Task 3: Add the typed gateway and immediate durable search

**Files:**
- Create: `src/flight_hunter/application/agent_tools.py`
- Modify: `src/flight_hunter/agent/chat.py`
- Modify: `src/flight_hunter/application/agent_lifecycle.py`
- Modify: `src/flight_hunter/application/watch_service.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `tests/unit/agent/test_chat.py`
- Modify: `tests/unit/api/test_agent_api.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class AgentPlanBinding:
    plan_id: UUID
    revision_id: UUID
    expected_revision: int
    content_hash: str

@dataclass(frozen=True, slots=True)
class AgentActionGrant:
    kind: Literal["search_execute", "watch_create"]
    household_id: UUID
    user_id: UUID
    session_id: UUID
    binding: AgentPlanBinding
    idempotency_key: str

class AgentToolGateway:
    async def prepare_search(...) -> PlanView: ...
    async def start_search(..., grant: AgentActionGrant) -> RunView: ...
    async def create_watch(..., grant: AgentActionGrant) -> WatchRecord: ...
```

- [ ] Add one service/API scenario that submits a complete message with `Idempotency-Key`, receives `run_started` and a durable queued/running run, replays the same key to the same run, rejects reuse against another binding, and proves an incomplete message returns `clarification` with no run/provider call.
- [ ] Include `следи за ...` in that scenario: it creates the baseline run and exactly one watch; replay returns the same watch. Use a deterministic UUIDv5 watch ID bound to household + action key and validate an existing record against the plan binding before treating it as replay.
- [ ] Run `uv run pytest tests/unit/agent/test_chat.py tests/unit/api/test_agent_api.py -q`; expect the new scenario to fail.
- [ ] Implement immutable gateway DTOs and validate household, user, session, action kind, plan/revision/content hash and idempotency binding before delegating to existing lifecycle/watch services.
- [ ] Reuse `AgentLifecycleService.execute_plan()` and its durable idempotency index. Do not publish a second queue message; success is returned only after the run and initial operations commit.
- [ ] Treat a complete authenticated chat message as one `search_execute` grant. If clarifications, material unsupported constraints, scope-freeze failures or absolute budget failures remain, return a clarification/failure without executing.
- [ ] For explicit watch intent, create a separate `watch_create` grant only after the baseline run exists. A watch failure becomes warning `watch_create_failed`; it never rolls back or hides the search run.
- [ ] Leave all legacy create/edit/confirm/execute endpoints unchanged for diagnostics and advanced use.
- [ ] Run the two focused test files again; expect PASS.
- [ ] Commit this task as `feat: start durable search from agent chat`.

### Task 4: Return one tagged chat outcome

**Files:**
- Modify: `src/flight_hunter/agent/chat.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `tests/unit/api/test_agent_api.py`

**Public response union:**

```text
clarification { code, message_ru, options[] }
run_started   { plan, run, idempotent_replay, warnings[] }
watch_created { watch_id, plan, run, idempotent_replay, warnings[] }
failure       { code, message_ru, retryable }
```

- [ ] Require `Idempotency-Key` on `POST /api/v1/agent/chat/turn`; derive household/user/session only from authenticated server state.
- [ ] Replace nullable chat response inference with a Pydantic discriminated union and stable machine-readable error codes.
- [ ] Do not wait for provider polling in the request. Return the public plan summary and first run projection immediately.
- [ ] Preserve opaque candidate references and existing booking tokens only in result projections; never add raw provider identifiers or seller URLs to chat output.
- [ ] Run `uv run pytest tests/unit/api/test_agent_api.py -q`; expect PASS.
- [ ] Commit this task as `refactor: expose tagged agent chat outcomes`.

### Task 5: Polish the agent-first UI around progress and results

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Modify: `tests/unit/api/test_web_ui.py`
- Modify: `tests/e2e/test_local_v1_browser.py`

**Stable browser behavior:**
- New UUID idempotency key per deliberate submit; retain it only for retry of that pending submission.
- Complete prompt goes directly to run progress; clarification stays inline and keeps the draft.
- Existing authenticated run/results endpoints remain the source of progress and evidence.

- [ ] Add one HTML/JavaScript contract test for the prominent composer, five Russian stages, collapsed diagnostics, tagged outcome handling and hidden technical labels.
- [ ] Update one Playwright smoke to submit a complete prompt, render progress/ranked cards at 1440 px and 390 px, and assert no horizontal overflow.
- [ ] Run `uv run pytest tests/unit/api/test_web_ui.py -q`; expect the new contract assertions to fail.
- [ ] Make the agent composer the first obvious action. Example chips insert editable text; they do not run hidden searches.
- [ ] On submit, compact the composer, scroll/focus the progress workspace and map durable operations to `Понимаю маршрут`, `Проверяю аэропорты и даты`, `Ищу живые варианты`, `Сравниваю маршруты`, `Готово`.
- [ ] Generate one browser idempotency key per new submit, keep it for retry while pending, and create a new key for a deliberate later search.
- [ ] Render clarification options inline. Render partial/empty/retryable/session-missing states without losing the draft or successful evidence.
- [ ] Move harness/runtime/capability/Cloudflare/raw provider details into collapsed diagnostics.
- [ ] Render each unique candidate once with any applicable badges: `Лучший вариант`, `Самый дешёвый`, `Самый быстрый`, `Меньше риска`.
- [ ] Lead each card with total price/passenger basis, requested human route and actual airports; then airline identity/logo, duration, stops, baggage, freshness/observation and visible split/self-transfer/hidden-city risk. Unknown evidence must read `неизвестно`.
- [ ] Keep `Открыть покупку`, `Следить за ценой`, `Подробнее` candidate-specific; keep exact search in progressive disclosure.
- [ ] Add single-column mobile cards, minimum 44 px targets and a non-covering relevant action bar.
- [ ] Run `uv run pytest tests/unit/api/test_web_ui.py -q`; expect PASS.
- [ ] Commit this task as `feat: polish agent search workspace`.

### Task 6: Document, configure and perform the narrow release checks

**Files:**
- Modify: `docs/provider-contracts/aviasales-search.md`
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify if commands changed: `README.md`
- Local ignored file only: `.env`

- [ ] Update the provider contract verification date to 2026-07-17 and record only redacted endpoint/status/schema facts from the successful API-kit probe.
- [ ] Update `IMPLEMENTATION_STATUS.md` with the slice, exact focused checks and known non-goals; do not claim a full regression run.
- [ ] Run the importer against `C:\Users\kiwun\Изображения\api_kit` and the ignored local `.env`; assert stdout is exactly the safe success JSON.
- [ ] Run only these automated checks:

```powershell
uv run pytest tests/unit/ops/test_api_kit_import.py -q
uv run pytest tests/unit/agent/test_codex_cli_adapter.py tests/unit/application/test_agent_intent.py -q
uv run pytest tests/unit/agent/test_chat.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
uv run pytest tests/e2e/test_local_v1_browser.py -q -m browser_e2e --strict-markers
uv run ruff check src/flight_hunter/ops/api_kit_import.py src/flight_hunter/agent/codex_cli.py src/flight_hunter/agent/chat.py src/flight_hunter/application/agent_tools.py src/flight_hunter/application/agent_intent.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py
```

- [ ] Run one safe summary-only Aviasales live smoke after import. Output may include only `ok/error`, item count and freshness class; no price, provider IDs, continuation, token, URL or credential.
- [ ] Restart the local API and worker as hidden processes using the configured `.env`.
- [ ] Verify `GET /healthz`, `GET /readyz` and a non-stale worker heartbeat.
- [ ] Submit one complete local natural-language request and verify a durable run starts without the manual confirm endpoint; inspect only normalized public result fields.
- [ ] Review `git diff --check`, `git status --short`, and a secret-pattern scan over tracked changes before committing.
- [ ] Commit remaining docs/release adjustments as `docs: record local agent API release`.
- [ ] Push current `main` to its configured `origin/main`.

## Acceptance

- The ignored local `.env` is configured from the supplied API kit with no secret output and no runtime dependency on that directory.
- Complete search messages immediately return a durable run ID; incomplete ones produce a useful clarification and zero provider work.
- Same-key retries replay the same bound run/watch; a different binding conflicts.
- Country, region, city and airport phrases still resolve through frozen typed place data; provider facts still come only from normalized evidence.
- UI leads with the agent, shows human progress, readable airports/airlines/flags, honest baggage/freshness/risk and usable mobile cards.
- Booking remains an explicit later click.
- Only the listed focused checks and one safe live smoke are run.
- `main` is committed, pushed and the local API/worker are healthy after restart.
