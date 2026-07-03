# ADR 0062: Web invitation session panel

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The API can now create invitation-only bearer sessions, but the FastAPI-served web UI only used a
token if a user or operator had already written it into local storage. That left the main product
screen dependent on manual browser storage edits for the new auth path.

## Decision

Add a compact session panel to the existing first screen:

- Users can paste an invitation code and display name.
- The UI calls `POST /api/v1/auth/accept-invitation`.
- The returned bearer session token is stored in `localStorage` under
  `flight_hunter_session_token`.
- Startup validates an existing token through `GET /api/v1/auth/me`.
- All auth-aware fetches use `Authorization: Bearer ...` when a session exists; otherwise they keep
  the old demo header fallback.
- Sign-out clears the stored token and returns the page to demo-header mode.

## Consequences

Positive:

- The invitation/session API is now reachable from the primary UI without asking users to edit
  local storage.
- Session identity still wins over demo headers because `authHeaders()` sends only bearer auth when
  a token exists.
- The main screen remains the usable flight-search workbench rather than a landing/login page.

Tradeoffs:

- This is a compact bootstrap/acceptance surface, not a full account-management UI.
- Bootstrap invitation creation remains API/operator-only because it requires a local bootstrap
  token and should not be exposed as a casual browser control.

## Verification

- `uv run pytest tests/unit/api/test_web_ui.py tests/unit/api/test_auth_api.py --quiet`
  -> 8 passed.
- `node -e "... new Function(script) ..."` -> `script syntax ok`.
- `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> All checks passed.
