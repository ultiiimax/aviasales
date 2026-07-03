# ADR 0091: Aviasales Data special offers cached radar

Date: 2026-06-29

## Status

Accepted.

## Context

The Aviasales / Travelpayouts Data API adapter already supports exact cached prices and several
explicit cached-radar endpoints. The MEGA_MONSTER_PLAN calls for broader Data API coverage while
keeping cached data separate from live availability and booking flows.

Travelpayouts documents `/aviasales/v3/get_special_offers` as a cached Data API endpoint for
special/abnormally cheap offers. The endpoint can infer origin from caller context if origin is not
provided, but Flight Hunter must not rely on provider IP inference for a household-scoped product.

## Decision

Add `SpecialOffersQuery`, `AviasalesDataClient.special_offers`,
`AviasalesDataQueryPlanner.plan_special_offers`, `AviasalesDataAdapter.special_offers`, and expose
the feature only through `radar_kind=special_offers` on `/api/v1/searches/cached-radar`.

The planner always supplies both origin and destination from `SearchIntent`. Child/infant passenger
mixes fail closed before HTTP, as with other cached Data API endpoints.

The parser accepts documented route/date/price fields, filters `actual=false` rows when present,
uses provider `found_at` as observation time when available, and deliberately drops
`link`/`signature`/`search_id`. Results are mapped to cached `FlightOffer` hints with
`requires_live_confirmation=true` and the `cached_special_offers` ranking reason.

This slice also hardens `nearest-places-matrix` parsing to accept the current top-level `prices`
payload shape in addition to the earlier `success/data` fixture shape.

## Consequences

- Special offers are available as explicit cached hints without entering exact-date ranked search.
- No special-offer booking/search link is exposed as a ready booking URL.
- Provider contract catalog now lists `popular_directions_cached_radar` and
  `special_offers_cached_radar`.
- Remaining Data API endpoints must still be added deliberately with contract tests.

## Verification

- Client tests cover request params, response parsing and dropping link-like fields.
- Planner/adapter/API tests cover cached-radar behavior and policy gates.
- Source contract tests cover the expanded operation list.
