# ADR 0122: Offer Risk Visibility

Date: 2026-06-29

## Status

Accepted

## Context

`MEGA_MONSTER_PLAN.md` requires visible risk, freshness and baggage caveats before a user treats a
price as actionable. The current product already ranks mergeable offers and records ranking
reasons, but those reasons are score explanations, not a stable API contract for user-facing risk.

Split-ticket, self-transfer and hidden-city candidate generation are still future work. The system
must not invent those candidates just to expose a risk UI.

## Decision

Add a minimal `flight_hunter.itinerary_engine.risk` module that assesses existing `FlightOffer`
objects only.

The first risk contract contains:

- `level`: `low`, `medium` or `high`;
- `flags`: deterministic machine-readable values such as `cached_price`,
  `requires_live_confirmation`, `baggage_unknown`, `provider_single_adult_ticket`;
- `explanations`: deterministic human-readable strings derived only from domain fields.

`OfferResponse` now includes this `risk` object for exact search, cached radar and live observation
priced offers. The web UI renders the risk level, flags and explanation text on priced result rows.

## Consequences

- Cached and stale prices are visibly distinguished from live/user-confirmed offers.
- Aviasales Data single-adult cached price basis is visible wherever a priced offer is returned.
- The contract can later absorb split-ticket/self-transfer risk flags without changing the basic
  API shape.
- This slice does not generate split-ticket, self-transfer, hidden-city or route-composition
  candidates.
