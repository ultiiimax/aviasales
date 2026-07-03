# ADR 0047: Aviasales Data Search By Price Range

Date: 2026-06-29

## Status

Accepted for explicit cached price-band radar.

## Context

The monster plan lists `/v3/search_by_price_range` as one of the Aviasales Data endpoints that can
broaden cached discovery beyond exact-date searches. This endpoint is still Aviasales Data, not live
availability, so it cannot be used to claim bookability or hide the need for external confirmation.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `SearchByPriceRangeQuery` for `/aviasales/v3/search_by_price_range`.
2. Use only documented query parameters: `origin`, `destination`, `value_min`, `value_max`,
   `one_way`, `direct`, `locale`, `currency`, `market`, `limit`, and `page`.
3. Require a non-negative ascending integer price range before any HTTP call.
4. Keep this endpoint as an explicit adapter method rather than the default search path.
5. Map returned ticket rows to cached `FlightOffer` values with live-confirmation caveats.
6. Continue sending the token only in `X-Access-Token`.

## Consequences

- Price-band discovery can be requested explicitly for cached radar workflows.
- UI/API presentation remains future work; default exact search remains `prices_for_dates`.
- CI uses mocked transports only and does not make live Travelpayouts calls.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
