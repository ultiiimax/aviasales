# Search-first UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the confusing all-at-once dashboard with a clear Russian search-first flow while preserving every working search, agent, watch and diagnostic contract.

**Architecture:** Keep the existing server-rendered vanilla HTML/CSS/JS boundary in `render_index_html()`. Reorder and progressively disclose existing regions instead of changing backend APIs; preserve stable element IDs so the durable agent lifecycle remains intact.

**Tech Stack:** Python 3.13, FastAPI server-rendered HTML, vanilla CSS/JavaScript, pytest, Playwright Chromium.

## Global Constraints

- No new frontend framework, dependency, CDN font or external image request.
- Russian user-facing copy only; provider/source identifiers remain raw only where they are data.
- Keep all current API endpoint strings and durable plan/run IDs.
- Keep `LIVE`, `RECENT`, `CACHED`, `STALE`, source and `observed_at` honesty.
- Keep hidden-city isolated and acknowledgement-gated.
- Preserve keyboard focus, semantic labels and reduced-motion behavior.

---

### Task 1: Lock the new information hierarchy in tests

**Files:**
- Modify: `tests/unit/api/test_web_ui.py`
- Modify: `tests/e2e/test_local_v1_browser.py`
- Modify: `tests/e2e/test_agent_route_orchestrator.py`

**Interfaces:**
- Consumes: `GET /` HTML and the existing stable DOM IDs.
- Produces: contract assertions for `Куда летим?`, `Собрать план`, compact account disclosure, exact-route disclosure, Russian copy and mobile overflow safety.

- [ ] Add an HTML contract test that requires the new hero/account/exact-route classes and forbids old visible headings:

```python
def test_web_ui_uses_search_first_russian_hierarchy() -> None:
    html = TestClient(create_app()).get("/").text
    for fragment in ('class="hero-search"', 'class="account-menu"', 'class="exact-search"'):
        assert fragment in html
    for text in ("Куда летим?", "Собрать план", "Задать точный маршрут"):
        assert text in html
    for old_heading in (">Agent cockpit<", ">Session<"):
        assert old_heading not in html
```

- [ ] Update Playwright button selection from `Спросить агента` to
  `Собрать план`, retaining the exact scenario and plan assertions.
- [ ] Run `uv run pytest tests/unit/api/test_web_ui.py -q`; expect the new
  hierarchy test to fail before implementation.

### Task 2: Implement the search-first shell

**Files:**
- Modify: `src/flight_hunter/api/web.py`

**Interfaces:**
- Consumes: existing IDs queried by the current JavaScript.
- Produces: the same elements in a new hierarchy; no API or schema changes.

- [ ] Replace the old grid/background/token set with warm paper, navy and cobalt
  tokens; add `.hero-search`, `.account-menu`, `.exact-search`, `.utility-grid`
  and responsive rules.
- [ ] Move the invitation form into `<details class="account-menu">`, retaining
  `#auth-form`, `#auth-state`, `#auth-submit-button` and
  `#auth-signout-button`.
- [ ] Make the agent the single hero flow, wrap runtime data in a collapsed
  `Как работает поиск` disclosure, and retain every plan/run/result ID.
- [ ] Put the exact `#search-form` in a collapsed `Задать точный маршрут`
  disclosure with an eight-column-safe grid.
- [ ] Move `#results-list` before sources/watches and collapse health/audit by
  default.

### Task 3: Make copy and session state coherent

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Test: `tests/unit/api/test_web_ui.py`

**Interfaces:**
- Consumes: `storeSession()`, `renderSignedOutState()`, `acceptInvitation()` and
  `refreshSessionState()`.
- Produces: Russian account labels without changing session race guards.

- [ ] Add `#account-label` and update it to `Войти` or the active role from the
  existing session functions.
- [ ] Translate auth validation/status strings and the corrupted audit strings.
- [ ] Keep these exact guards unchanged: `agentSessionGeneration`,
  `sessionIdentityIsCurrent`, execute generation and current-plan/run clearing.
- [ ] Run `uv run pytest tests/unit/api/test_web_ui.py -q`; expect PASS.

### Task 4: Verify responsive behavior and working flows

**Files:**
- Modify only if a regression is found: `src/flight_hunter/api/web.py`
- Test: `tests/e2e/test_local_v1_browser.py`
- Test: `tests/e2e/test_agent_route_orchestrator.py`

**Interfaces:**
- Consumes: local Playwright servers and existing fake/durable agent fixtures.
- Produces: desktop/mobile screenshots and green compact acceptance flows.

- [ ] Run `uv run pytest tests/e2e/test_local_v1_browser.py tests/e2e/test_agent_route_orchestrator.py -q -m browser_e2e --strict-markers`.
- [ ] Inspect 1440×1000 and 390×844 screenshots; require no horizontal overflow,
  clipped route fields or overlapping account menu.
- [ ] Run `uv run ruff format --check .`, `uv run ruff check .`, and
  `uv run mypy`.
- [ ] Update `IMPLEMENTATION_STATUS.md` with exact results and restart the local
  API/worker so `http://127.0.0.1:8000` serves the redesign.
