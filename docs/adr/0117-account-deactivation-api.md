# ADR 0117: Account deactivation API

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The architecture lists `DELETE /api/v1/account`. A literal hard delete would conflict with the
product's append-only audit and price-history requirements, and it could hide past watch lifecycle
events that explain alerts or provider calls. At the same time, a user deleting their account must
not keep valid sessions, Telegram delivery links or owned watch monitoring running in the
background.

## Decision

Implement `DELETE /api/v1/account` as account deactivation with retention:

- The endpoint requires a valid bearer session. Legacy demo household headers are rejected for this
  destructive account action.
- All active auth sessions for the current household/user are revoked.
- The current household membership is disabled.
- The user's active Telegram account link is revoked.
- Active watches owned by the user are soft-deleted with version-aware watch lifecycle logic.
- Each stopped owned watch receives a `watch.deleted` audit event.
- The deactivation itself receives an `account.deactivated` audit event.
- Retained categories are declared in the response: audit events, price history, manual
  confirmations, browser observations and deal candidates.

No migration is required because `auth_sessions.revoked_at`, `household_memberships.disabled_at`,
`telegram_accounts.revoked_at` and watch soft-delete columns already exist.

## Consequences

Positive:

- A deleted user cannot keep using bearer sessions.
- Background watch monitoring for the deleted user's owned watches stops.
- Telegram notifications cannot continue through a previously linked account.
- Auditability and append-only history remain intact.

Tradeoffs:

- This is deactivation/retention, not hard erasure or pseudonymization.
- Household-level retained records can still reference the deactivated user's UUID for audit.
- A future hard-erasure workflow would need an explicit retention/legal policy and likely a
  separate asynchronous job.

## Verification

- `uv run pytest tests/unit/api/test_account_delete_api.py tests/unit/persistence/test_identity_repository.py tests/unit/persistence/test_telegram_link_repository.py -q`
  -> 5 passed.
