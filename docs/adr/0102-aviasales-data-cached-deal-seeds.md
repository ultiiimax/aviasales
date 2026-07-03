# ADR 0102: Aviasales Data cached deal seeds

Date: 2026-06-29

## Status

Accepted.

## Context

Aviasales Data cached radar already exposes official cached endpoints such as
`get_special_offers`, `get_popular_directions`, `get_latest_prices` and matrix/range endpoints.
Those rows are useful as deal hints, but they are still cached Aviasales user-search history, not
live fare availability and not a booking contract.

Deal discovery already has a durable `DealCandidate` lifecycle with TTL, household/user scoping and
manual-verification UI warnings. Before this decision, cached radar and deal candidates stayed
separate even when a user explicitly wanted to keep a cached radar row as a deal hint.

Official Travelpayouts documentation was rechecked on 2026-06-29:

- Aviasales Data API: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- API rate limits: https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

`/api/v1/searches/cached-radar` can now, when explicitly requested with `save_deal_candidates=true`
and an authenticated `search_id`, persist Aviasales Data cached rows as manual-verification
`DealCandidate` seeds.

The seed mapper:

- uses source `aviasales_data`;
- sets `requires_manual_verification=true` and low confidence;
- preserves cached price, route and date window as extracted fields;
- uses a conservative Aviasales manual-check URL;
- never exposes provider `link`, `signature` or `search_id` as a booking URL;
- uses deterministic scoped UUIDs per household/user/search/radar row to avoid duplicates.

## Consequences

- Cached radar can feed the existing deal-candidate lifecycle without creating a new persistence
  path or treating cached rows as live ranked offers.
- Repeated saves for the same household/user/search/radar row are idempotent.
- Unauthenticated cached radar remains available as before, but persistence requires explicit
  user/household context.

## Verification

- Mapper tests cover candidate-only semantics and absence of signed provider refs.
- Cached radar API tests cover authenticated persistence, search enrichment and household/user
  isolation.
- Source-contract tests expose the `cached_deal_seed_discovery` operation and candidate-only
  invariant.
