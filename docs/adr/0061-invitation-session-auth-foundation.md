# ADR 0061: Invitation session auth foundation

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

Flight Hunter is intended to be self-hosted and invitation-only, but earlier API slices used
temporary `X-Flight-Hunter-Household-Id` and `X-Flight-Hunter-User-Id` headers to exercise
household isolation before real identity existed. That was useful for demos and tests, but it is
not a production authentication boundary.

The product still needs to preserve demo mode while introducing a path that can be hardened
incrementally without creating passwords, leaking tokens, or mixing users between households.

## Decision

Add a passwordless invitation/session foundation:

- `POST /api/v1/auth/bootstrap-invitation` creates the first household invitation only when
  `AUTH_BOOTSTRAP_TOKEN` is configured and supplied via `X-Flight-Hunter-Bootstrap-Token`.
- `POST /api/v1/auth/accept-invitation` accepts a one-time invitation code, creates a user,
  membership and bearer session.
- `GET /api/v1/auth/me` resolves the current bearer session.
- Invitation codes and session tokens are returned to clients once and stored only as SHA-256
  hashes in persistence.
- Bearer session auth is accepted by protected API routes, including Watch API, manual
  confirmations, Telegram link-code creation, agent/search context enrichment and live/personal
  observation flows.
- Legacy `X-Flight-Hunter-*` headers remain available behind `AUTH_ALLOW_LEGACY_HEADERS=true` for
  local/demo compatibility.
- If both bearer auth and legacy headers are supplied, the bearer session identity wins.

## Consequences

Positive:

- Production deployments can disable legacy headers and rely on bearer session identity for core
  household-scoped flows.
- Session lookup verifies active membership and session expiry before returning context.
- Existing demo and test flows keep working while the UI and admin identity surface mature.

Tradeoffs:

- This is not a complete identity product: there is no polished invitation acceptance screen,
  session revocation UI or admin invitation management yet.
- Bootstrap invitation creation depends on a local environment secret; operators must remove or
  rotate it after initial setup.
- Legacy headers are still enabled by default for demo mode and must be explicitly disabled in
  production.

## Verification

- `uv run pytest tests/unit/api/test_auth_api.py tests/unit/api/test_web_ui.py tests/unit/api/test_watch_api.py tests/unit/api/test_api_app.py tests/unit/api/test_live_observations_api.py tests/unit/api/test_telegram_api.py tests/unit/api/test_agent_api.py tests/unit/persistence/test_identity_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
  -> 62 passed, 2 warnings from the existing Telegram API aiosqlite test harness.
