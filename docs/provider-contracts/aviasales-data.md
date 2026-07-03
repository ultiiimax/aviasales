# Aviasales Data API Contract Notes

Verified: 2026-06-29

Official sources:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

Implementation status: implemented as a policy-gated cached adapter and local smoke helper.
The adapter currently supports `/v3/prices_for_dates`, `/v3/search_by_price_range`,
`/v3/grouped_prices`, `/v3/get_latest_prices`, `/v2/prices/week-matrix`,
`/v2/prices/month-matrix`, `/v2/prices/nearest-places-matrix` and
`/v3/get_popular_directions`, and `/v3/get_special_offers`.

The adapter uses fixture/transport tests and does not make live calls in CI.

Endpoint inventory checked 2026-06-29:

- Implemented cached REST endpoints: `/aviasales/v3/prices_for_dates`,
  `/aviasales/v3/search_by_price_range`, `/aviasales/v3/grouped_prices`,
  `/aviasales/v3/get_latest_prices`, `/aviasales/v3/get_popular_directions`,
  `/aviasales/v3/get_special_offers`, `/v2/prices/week-matrix`,
  `/v2/prices/month-matrix`, `/v2/prices/nearest-places-matrix`.
- Superseded legacy cached endpoints not implemented by default: `/v1/prices/cheap`,
  `/v1/prices/direct`, `/v1/city-directions`, `/v1/prices/calendar`,
  `/v1/prices/monthly`, `/v2/prices/latest`, `/v2/prices/special-offers`.
  Flight Hunter uses the documented v3/v2 replacements above instead of creating parallel
  legacy adapters.
- Deprecated/do-not-implement: `/v1/airline-directions`, marked deprecated in provider docs.
- Reference-data and GraphQL endpoints are outside this adapter's flight-price contract and need
  separate contracts before use.

`uv run travelpayouts-smoke` can be used manually to verify local credentials. It returns only a sanitized summary and does not print the token, raw payload, booking/search link, or prices.

Policy facts used by Flight Hunter:

- Data API prices are cached from Aviasales user search history, not live availability.
- Cached data can be stored by Aviasales for up to 7 days depending on the query type.
- `/v3/prices_for_dates`, `/v3/search_by_price_range`, `/v3/grouped_prices`,
  `/v3/get_latest_prices`, `/v3/get_popular_directions`, `/v3/get_special_offers`,
  `/v2/prices/week-matrix`, `/v2/prices/month-matrix` and
  `/v2/prices/nearest-places-matrix` are rate-limited by Travelpayouts; the official rate-limit
  page lists endpoint-specific limits where published, but Flight Hunter must use its own lower
  internal limiter.
- A 429 response must be treated as a provider rate-limit signal and never retried aggressively.
- `X-Rate-Limit`, `X-Rate-Limit-Remaining` and `X-Rate-Limit-Reset` are parsed into sanitized
  integer metadata when present. Smoke commands may print these numbers, but never raw headers,
  tokens, URLs or provider payloads.
- UI, Telegram, and persisted observations must show `observed_at`, freshness, provider source,
  passengers, `price_basis`, and live-confirmation caveats.
- Flight Hunter treats Aviasales Data price fields as provider single-adult-ticket prices, because
  the official cached endpoints expose `price`/`value` but no passenger-count query field. Until a
  provider-specific total-price contract is documented and modeled, multi-adult, child and infant
  passenger mixes fail closed without an HTTP call; the adapter never multiplies cached provider
  prices by requested passengers.

Current Flight Hunter policy:

- Adapter disabled until credentials are configured and `AVIASALES_DATA_ENABLED=true`.
- Data kind: `cached`.
- Background discovery can only be enabled through `ProviderPolicy` and quota guard.
- Merge is allowed only as cached/indicative data; it must never be labelled live.
- API token is sent in `X-Access-Token` and must not appear in query strings, logs, API responses, or client bundles.
- Rate-limit metadata is exposed only as sanitized counters in local smoke/source-smoke summaries.
- Booking/search links from Data API payloads are not exposed as ready booking URLs by this adapter.
- Exact one-way and round-trip searches are planned through `prices_for_dates`.
- Provider price fields are parsed as integer major units. Integer-valued floats from documented
  matrix examples, such as `26000.0`, are accepted and normalized to integers; fractional floats
  fail closed. Empty return-date fields normalize to `None`, not an empty string.
- Mapped Aviasales Data offers use `price_basis=provider_single_adult_ticket`. Public API routes
  reject `passengers != 1` for Aviasales Data cached pricing before provider lookup.
- Explicit price-band cached radar uses `search_by_price_range` with a validated integer price range in provider major units, parses only documented ticket fields and is still labelled cached.
- Broader cached date/month radar uses `grouped_prices` explicitly and is still labelled cached.
- Latest-period cached radar uses `get_latest_prices` explicitly, parses endpoint-specific
  `value`/`depart_date`/`found_at`/`actual` fields, filters `actual=false` rows, and is still
  labelled cached.
- Week-level flexible-date cached radar uses `week-matrix` explicitly, filters out `actual=false` rows, and does not invent booking/search links.
- The public date-matrix API may overlay `week-matrix` rows onto planned flexible-date cells only
  when origin/destination and Aviasales Data credentials are present; otherwise it returns explicit
  pricing denial codes without making a provider call.
- Month-level flexible-date cached radar uses `month-matrix` explicitly, filters out `actual=false` rows, computes conservative trip duration weeks for round trips, and does not invent booking/search links.
- Nearby-place cached radar uses `nearest-places-matrix` explicitly, parses either legacy
  `success/data` or current top-level `prices` payloads, filters out `actual=false` rows, and does
  not invent booking/search links. This is not a live nearby-airport inventory guarantee.
- Popular-directions cached radar uses `get_popular_directions` explicitly, parses the documented
  `data.origin` list for a destination, and does not invent booking/search links. This is not a
  live inventory or route availability guarantee.
- Special-offers cached radar uses `get_special_offers` explicitly with both origin and
  destination supplied by Flight Hunter. It parses documented route/date/price fields only, filters
  `actual=false` rows when present, ignores `link`/`signature`/`search_id` fields, and labels rows
  as cached special-offer hints that require external confirmation.
- The public cached-radar API exposes `search_by_price_range`, `grouped_prices`,
  `get_latest_prices`, `month-matrix`, `nearest-places-matrix`, `popular-directions` and
  `special-offers` as separate cached hint surfaces; results stay out of ranked exact-date search
  until a user explicitly requests them.
- When an authenticated user explicitly asks cached radar to save deal seeds for an existing
  `search_id`, Flight Hunter may persist those cached rows as `DealCandidate` records with
  `requires_manual_verification=true`, `confidence=low`, source `aviasales_data` and a conservative
  manual Aviasales URL. These candidates are not `FlightOffer`s, not live availability, not booking
  links, and not merged into priced-offer ranking.
- Cached deal seed persistence uses deterministic scoped IDs per household/user/search/radar row, so
  repeating the same user action does not create duplicate candidate rows.
