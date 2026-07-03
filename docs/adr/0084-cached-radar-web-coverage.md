# ADR 0084: Cached Radar Web Coverage

Date: 2026-06-29

## Status

Accepted.

## Context

The cached-radar API supports Aviasales Data `price_range`, `grouped_prices`, `latest_prices`,
`month_matrix` and `nearest_places_matrix`, but the web workbench only requested three of those
modes. This made `grouped_prices` and `latest_prices` reachable by API/tests but invisible in the
main operator UI.

## Decision

- Make the web Cached radar action call all public cached-radar modes.
- Add distinct labels for grouped and latest cached prices in the rendered result rows.
- Keep the same cached/not-live warning and manual confirmation flow for every mode.

## Consequences

- The UI now mirrors the public cached-radar API surface.
- More provider calls are made when the operator presses Cached radar and Aviasales Data
  credentials are configured, but the action remains explicit and user-triggered.
- Results stay outside live/bookable claims and keep `requires_live_confirmation=true`.
