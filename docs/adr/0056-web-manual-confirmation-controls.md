# ADR 0056: Web Manual Confirmation Controls

Date: 2026-06-29

## Status

Accepted.

## Context

The manual confirmation ledger is useful only if a user can record confirmations from the result
surface where cached prices, external links, browser observations and deal candidates are shown.
The existing web UI is a FastAPI-served HTML page with vanilla JavaScript and demo household/user
headers stored in localStorage.

## Decision

- Add compact manual confirmation actions to result rows:
  - `confirmed`
  - `price_changed`
  - `sold_out`
  - `bought`
  - `wrong_route`
- Use `POST /api/v1/manual-price-confirmations` with the same local household/user headers used by
  existing user-action flows.
- Show recent scoped confirmations through `GET /api/v1/manual-price-confirmations`.
- Include known integer minor-unit price only for `confirmed` and `bought` actions when the row
  already has a verified local price object.

## Consequences

- Users can record what happened after opening external links or checking observed results.
- The UI keeps manual confirmations separate from provider facts, ranking and alert snapshots.
- The implementation remains dependency-free and does not add a frontend build step.
- Future Telegram/PWA surfaces can reuse the same API contract.
