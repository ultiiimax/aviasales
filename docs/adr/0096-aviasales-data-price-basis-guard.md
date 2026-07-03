# ADR 0096: Aviasales Data price-basis guard

Date: 2026-06-29

## Status

Accepted.

## Context

The Aviasales / Travelpayouts Data API cached endpoints expose documented `price` / `value`
fields, but the cached flight-price requests implemented by Flight Hunter do not include a
passenger-count parameter. The official Data API documentation was checked on 2026-06-29:
https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API

The previous mapper multiplied cached provider price fields by `SearchIntent.passengers`. That can
create a false total because Flight Hunter has not verified whether each cached provider row is a
single-ticket price, a user-search total, or another provider-specific basis.

## Decision

Treat Aviasales Data cached price fields as `provider_single_adult_ticket` until a stronger
provider contract is documented and implemented.

- `FlightOffer` now has an explicit `price_basis`.
- `total_for_passengers` remains the default for existing fake/live-observed flows.
- Aviasales Data mapped offers set `price_basis=provider_single_adult_ticket`.
- Aviasales Data planner/API paths reject `passengers != 1`, children and infants before any
  provider lookup.
- The Aviasales Data mapper raises if called with multi-passenger input instead of inferring a
  total.

## Consequences

- Flight Hunter no longer invents multi-passenger totals from cached Aviasales Data rows.
- Multi-passenger searches can still use demo/external click-out/manual confirmation paths, but
  Aviasales Data cached pricing returns an explicit unsupported-passenger denial until modeled.
- No live Search API behavior, booking-link preload or scraping fallback is introduced.

## Verification

- Domain tests cover `price_basis` defaults and the single-adult-ticket invariant.
- Aviasales Data mapper, planner and adapter tests cover no multiplication and no HTTP call for
  multi-adult requests.
- Cached radar/date matrix API tests cover public `passenger_mix_not_supported` denials and
  `price_basis` serialization.
