# Local Auto-Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Open the loopback Flight Hunter UI with a ready owner bearer session and no invitation form, so the first complete agent prompt can start a durable search.

**Architecture:** Keep all scoped APIs on the existing bearer/household path. Add one config-gated, actual-peer-loopback endpoint that selects one active owner or atomically creates a versioned deterministic local owner, then let the browser bootstrap/recover that normal session through a single-flight promise.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, SQLite, static HTML/CSS/JavaScript, pytest, Ruff, mypy, in-app Browser.

## Global Constraints

- `POST /api/v1/auth/local-session` trusts only `request.client.host`, never forwarded headers.
- Accepted peers are IPv4 loopback, `::1`, and IPv4-mapped loopback; missing/malformed peers fail closed.
- Existing invitation and bearer APIs remain compatible.
- Browser token replacement preserves `flight_hunter_agent_plan_id_v1` and `flight_hunter_agent_run_id_v1`.
- Provider credentials, prices and booking data never enter auth responses.
- No database migration and no full-suite test run.

---

### Task 1: Active owner persistence query

**Files:**
- Modify: `src/flight_hunter/persistence/repositories.py`
- Test: `tests/unit/persistence/test_identity_repository.py`

**Interfaces:**
- Produces: `ActiveOwnerIdentityRecord(household_id: UUID, user_id: UUID)`.
- Produces: `IdentityRepository.active_owner_identities(*, limit: int = 2) -> tuple[ActiveOwnerIdentityRecord, ...]`.
- Consumes: existing `household_memberships_table`, `HouseholdRole.OWNER` and async SQLAlchemy session.

- [ ] **Step 1: Write the failing repository test**

Create active owners in two households plus one disabled owner and assert the query returns only enabled owner memberships in deterministic `(created_at, household_id, user_id)` order, bounded to two rows.

```python
owners = await repository.active_owner_identities(limit=2)
assert [(row.household_id, row.user_id) for row in owners] == [first, second]
```

- [ ] **Step 2: Run the repository test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_identity_repository.py -q`

Expected: failure because `active_owner_identities` does not exist.

- [ ] **Step 3: Implement the typed bounded query**

Add the immutable record and query:

```python
@dataclass(frozen=True, slots=True)
class ActiveOwnerIdentityRecord:
    household_id: UUID
    user_id: UUID

async def active_owner_identities(self, *, limit: int = 2) -> tuple[ActiveOwnerIdentityRecord, ...]:
    bounded_limit = min(max(limit, 1), 10)
    # SELECT owner memberships WHERE disabled_at IS NULL, ordered deterministically.
```

- [ ] **Step 4: Run the repository test and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/persistence/test_identity_repository.py -q`

Expected: all tests in the file pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/flight_hunter/persistence/repositories.py tests/unit/persistence/test_identity_repository.py
git commit -m "feat: query active local owner identity"
```

### Task 2: Loopback local-session endpoint

**Files:**
- Modify: `src/flight_hunter/config.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `.env.example`
- Modify: `tests/unit/api/test_auth_api.py`
- Modify: `tests/unit/test_env_example.py`

**Interfaces:**
- Consumes: `IdentityRepository.active_owner_identities(limit=2)`.
- Produces: `AppSettings.auth_local_auto_login: bool` with env key `AUTH_LOCAL_AUTO_LOGIN` and local-v1 default `true`.
- Produces: `_request_has_loopback_peer(request: Request) -> bool`.
- Produces: `POST /api/v1/auth/local-session -> AuthSessionResponse` with status `201` and `Cache-Control: no-store`.

- [ ] **Step 1: Write failing API/config tests**

Cover disabled config, non-loopback with a forged forwarded header, IPv4/IPv6/IPv4-mapped success, malformed/missing peer rejection, first-owner creation, reuse, two-owner ambiguity and concurrent first calls converging on the same identity.

```python
response = client.post("/api/v1/auth/local-session")
assert response.status_code == 201
assert response.headers["cache-control"] == "no-store"
assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['session_token']}"}).status_code == 200
```

- [ ] **Step 2: Run focused auth/config tests and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/api/test_auth_api.py tests/unit/test_env_example.py -q`

Expected: failures for the missing config field and route.

- [ ] **Step 3: Implement config, peer parsing and endpoint**

Use named versioned IDs:

```python
LOCAL_OWNER_HOUSEHOLD_ID_V1 = uuid5(NAMESPACE_URL, "flight-hunter:local-owner:household:v1")
LOCAL_OWNER_USER_ID_V1 = uuid5(NAMESPACE_URL, "flight-hunter:local-owner:user:v1")
```

Within a per-app single-flight lock: select up to two active owners; reject ambiguity; create the deterministic identity when none exists; on `IntegrityError`, roll back and re-read; issue the existing hashed bearer session. Treat a deterministic collision without an active membership as `local_auto_profile_disabled`.

- [ ] **Step 4: Run focused auth/config tests and verify GREEN**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/api/test_auth_api.py tests/unit/test_env_example.py -q`

Expected: all selected tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add .env.example src/flight_hunter/config.py src/flight_hunter/api/app.py tests/unit/api/test_auth_api.py tests/unit/test_env_example.py
git commit -m "feat: add loopback local auto-login"
```

### Task 3: Automatic profile browser flow

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Modify: `tests/unit/api/test_web_ui.py`
- Modify: `tests/e2e/test_local_v1_browser.py`

**Interfaces:**
- Consumes: `POST /api/v1/auth/local-session` and existing `GET /api/v1/auth/me`.
- Produces: `ensureLocalSession() -> Promise<boolean>` with single-flight/stale-generation protection.
- Produces: `reconnectLocalSession() -> Promise<void>` preserving stored plan/run IDs.

- [ ] **Step 1: Write failing UI contract/browser tests**

Assert the rendered shell has `Локальный профиль`, `Переподключить профиль` and the local-session request, but no invitation code/name inputs or `Войти`/`Выйти` controls. Extend one browser scenario to clear the token, reload, wait for automatic profile readiness and submit the existing complete agent prompt without opening auth UI.

- [ ] **Step 2: Run UI unit test and verify RED**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/api/test_web_ui.py -q`

Expected: contract assertions fail against the current invitation form.

- [ ] **Step 3: Implement the minimal browser state machine**

Replace the form with a status popover and reconnect button. Implement:

```javascript
async function refreshSessionState() {
  // Existing valid bearer wins. 401 removes only that token and bootstraps local auth.
  // Network/5xx preserves token plus plan/run pointers and shows a retryable error.
}

async function requestAgentChat(prompt) {
  if (!sessionToken() && !(await ensureLocalSession())) return;
  // Continue the same click into the existing durable chat request.
}
```

Bind every bootstrap result to `agentSessionGeneration`, share one pending promise and never delete the plan/run local-storage keys during reconnect.

- [ ] **Step 4: Run UI unit test and one Chromium scenario**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/api/test_web_ui.py -q`

Run: `.venv\Scripts\python.exe -m pytest tests/e2e/test_local_v1_browser.py -q -k "auto_login or root_ui"`

Expected: selected tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py tests/e2e/test_local_v1_browser.py
git commit -m "feat: auto-connect the local web profile"
```

### Task 4: Local release configuration, docs and verification

**Files:**
- Modify: ignored `.env` without printing its values
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `IMPLEMENTATION_STATUS.md`

**Interfaces:**
- Consumes: `AUTH_LOCAL_AUTO_LOGIN=true` and the finished browser/backend flow.
- Produces: accurate local operator instructions and a restarted healthy release.

- [ ] **Step 1: Enable the ignored local setting and update docs**

Mechanically insert or replace only `AUTH_LOCAL_AUTO_LOGIN=true` in `.env`. Replace the mandatory invitation walkthrough with automatic local-profile behavior, and prominently document that container/proxy peers are rejected and network deployments must disable auto-login/use invitation API.

- [ ] **Step 2: Run the focused release gate**

Run one combined pytest command for the changed repository/auth/UI files, targeted Ruff check/format and mypy for `repositories.py`, `config.py` and `app.py`. Run `git diff --check` and the existing tracked-secret audit. Do not run the full suite.

- [ ] **Step 3: Restart API and both workers**

Stop only this workspace's `.venv` API/worker processes, start them hidden, poll `/readyz`, then verify general role `flight_hunter_worker` and agent role `agent` heartbeats.

- [ ] **Step 4: Validate the rendered flow with the in-app Browser**

Flow: `http://127.0.0.1:8000/#main-search` → clear old browser token/reload → profile automatically becomes ready → submit a complete prompt → durable run starts. Check page identity, meaningful DOM, no framework overlay, no relevant console errors/warnings, screenshot evidence and a mobile-width overflow smoke.

- [ ] **Step 5: Commit and push direct main**

```powershell
git add README.md CHANGELOG.md IMPLEMENTATION_STATUS.md
git commit -m "docs: release local auto-login"
git push origin main
```
