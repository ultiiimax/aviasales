# ADR 0088: Aviasales Data popular directions cached radar

Date: 2026-06-29

## Status

Accepted.

## Context

The MEGA_MONSTER_PLAN calls out broader Aviasales Data coverage beyond exact `prices_for_dates`.
Flight Hunter already supports exact cached prices, grouped/latest prices, week/month matrices,
nearest places and price-range cached radar. The remaining popular-directions endpoint is still
cached Aviasales user-search history, not live inventory.

Official Travelpayouts documentation verified on 2026-06-29 lists
`/aviasales/v3/get_popular_directions`. Its response shape nests route candidates under
`data.origin`, with destination metadata beside that list.

## Decision

Add explicit support for `/aviasales/v3/get_popular_directions`:

- `PopularDirectionsQuery` sends `destination`, `locale`, `currency`, `limit` and `page`.
- The parser accepts only the documented `data.origin` list and maps each origin row into a cached
  `AviasalesDataItem`.
- The query planner and adapter expose a `popular_directions` method.
- `POST /api/v1/searches/cached-radar` accepts `radar_kind=popular_directions`.
- The web workbench includes popular directions in the separate Cached radar action.

Popular directions remain outside the normal exact-date ranked search. They are shown as cached
hints that require external confirmation and do not include invented booking links.

## Consequences

- Operators get one more official cached radar surface without enabling live Search API access.
- Popular-direction rows may have origins different from the user's requested origin; this is
  acceptable only in the explicit cached-radar surface.
- Child/infant passenger mixes still fail closed before provider calls, matching the rest of the
  cached Data adapter.

## Verification

- Client tests cover safe params and docs-style `data.origin` parsing.
- Query planner and adapter tests cover cached semantics and no live claim.
- Cached radar API and web UI tests cover the new `popular_directions` mode.
