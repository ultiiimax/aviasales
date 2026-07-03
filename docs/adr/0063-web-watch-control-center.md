# ADR 0063: Web watch control center

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The backend already exposes household-isolated Watch API endpoints for create/list/detail,
pause/resume, versioned archive/delete and append-only price history. The primary web workbench
could search and queue manual checks, but users still had to call the Watch API outside the UI to
manage scheduled monitoring.

## Decision

Add a compact Watch control panel to the existing FastAPI-served workbench:

- Create a watch from the current route form through `POST /api/v1/watches`.
- List current household watches with `GET /api/v1/watches`.
- Pause/resume watches through the existing action endpoints.
- Load append-only price snapshots through `GET /api/v1/watches/{watch_id}/history`.
- Archive/delete watches with the current `expected_version`.
- Reuse `authHeaders()` so bearer sessions win and legacy demo headers remain only as fallback.

The panel does not trigger provider scans, browser observations or Telegram sends by itself.
Those remain worker/user-action flows governed by existing policy checks.

## Consequences

Positive:

- The Watch API is reachable from the main product surface.
- Household/session isolation remains server-side; the UI only passes the same auth headers as
  other auth-aware actions.
- History is shown separately from search results, preserving the distinction between provider
  facts, snapshots and live/browser checks.

Tradeoffs:

- This is still the integrated FastAPI workbench, not a dedicated PWA watch detail page.
- Pause/resume follow the current API and are not optimistic-versioned; archive/delete are.

## Verification

- `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py --quiet`
  -> 8 passed.
- Extracted inline script from `render_index_html()` and parsed it with Node
  `new Function(script)` -> `script syntax ok`.
- `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> All checks passed.
