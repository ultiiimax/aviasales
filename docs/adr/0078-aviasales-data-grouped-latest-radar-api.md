# ADR 0078: Aviasales Data Grouped and Latest Cached Radar API

Date: 2026-06-29

## Status

Accepted.

## Context

The Aviasales Data adapter already had tested client/planner/adapter support for
`/v3/grouped_prices` and `/v3/get_latest_prices`. The public cached-radar API exposed
`price_range`, `month_matrix` and `nearest_places_matrix`, but not grouped/latest radar modes. That
left two implemented cached endpoints unavailable from the product API.

## Decision

- Extend `POST /api/v1/searches/cached-radar` with `radar_kind=grouped_prices`.
- Extend the same endpoint with `radar_kind=latest_prices`.
- Keep public knobs conservative: grouped uses the adapter default `group_by=departure_at`, latest
  uses `period_type=month` and `group_by=dates`.
- Return normal cached `OfferResponse` rows with `freshness=cached`,
  `requires_live_confirmation=true` and cached radar ranking reasons.
- Keep these rows out of the main exact-date ranked search response unless the user explicitly
  calls the cached-radar endpoint.

## Consequences

- All currently implemented Aviasales Data radar endpoints are reachable through a product API.
- The endpoint still fails closed without credentials and still rejects unsupported child/infant
  passenger mixes before any provider call.
- This does not make Aviasales Data live, bookable or guaranteed inventory.
