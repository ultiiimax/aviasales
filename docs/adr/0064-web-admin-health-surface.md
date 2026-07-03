# ADR 0064: Web admin health surface

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

Provider and source health read models already exist as API endpoints, but the primary web
workbench did not expose them. Operators had to call admin endpoints manually to see whether a
source was disabled, missing credentials, blocked by policy or reporting recent persisted health
events.

## Decision

Add a read-only Health panel to the existing FastAPI-served workbench:

- Load `GET /api/v1/admin/providers/health`.
- Load `GET /api/v1/admin/sources/health`.
- Render provider readiness flags, credentials presence as a boolean, access approval, data kind
  and blocked reasons.
- Render source contract stage, enabled flag, blocked reasons and latest append-only event message.
- Do not run live probes, provider calls, browser automation or source smoke checks from the panel.

The UI deliberately does not read or display token values, env names or raw payloads.

## Consequences

Positive:

- Local operators can see source/provider readiness from the same screen as search, watches and
  manual checks.
- Health display remains a thin delivery layer over existing server-side read models.
- Refreshing the panel is safe: it reads existing status and persisted events only.

Tradeoffs:

- This is not a full admin console with RBAC, charts or historical filtering.
- API endpoints remain read-only and currently accessible in the local self-host UI context.

## Verification

- `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_admin_provider_health_api.py tests/unit/api/test_admin_source_health_api.py --quiet`
  -> 3 passed.
- Extracted inline script from `render_index_html()` and parsed it with Node
  `new Function(script)` -> `script syntax ok`.
- `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> All checks passed.
