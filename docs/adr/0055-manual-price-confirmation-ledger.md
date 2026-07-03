# ADR 0055: Manual Price Confirmation Ledger

Date: 2026-06-29

## Status

Accepted.

## Context

Search results now contain several non-authoritative result kinds: cached provider prices,
external search links, browser-observed offers, carrier confirmation links and deal candidates.
The monster plan also requires a user-confirmed state, but manual confirmation must not overwrite
provider facts or pretend that Flight Hunter has a live booking guarantee.

## Decision

- Store manual price confirmations in an append-only `manual_price_confirmations` table.
- Scope every record by `household_id` and `user_id`.
- Record the target as `(target_kind, target_id, source_id)` so confirmations can refer to cached
  offers, external links, browser observations, deal candidates or carrier links.
- Accept only closed status values: `confirmed`, `sold_out`, `price_changed`, `bought` and
  `wrong_route`.
- Store an optional confirmed price as integer minor units plus ISO currency.
- Expose scoped API endpoints:
  - `POST /api/v1/manual-price-confirmations`
  - `GET /api/v1/manual-price-confirmations`

## Consequences

- Manual confirmation becomes durable product history without mutating provider snapshots.
- A user can mark an observed/link result as matched, changed, unavailable, bought or wrong-route.
- Future UI and Telegram flows can show confirmation controls and recent confirmation history.
- This does not make a price live, does not create a booking link and does not update alert
  snapshots automatically.
