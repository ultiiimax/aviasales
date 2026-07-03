# ADR 0043: Aviasales Data Latest Prices Contract Hardening

Date: 2026-06-29

## Status

Accepted for endpoint-specific latest-period cached radar parsing.

## Context

Flight Hunter had `/aviasales/v3/get_latest_prices` wired as an explicit cached radar endpoint, but
its parser reused the generic `prices_for_dates` shape. The broader Aviasales Data endpoints use
slightly different field names and freshness hints, so relying only on `price` and `departure_at`
would make the adapter brittle and could hide stale rows.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Parse latest rows with endpoint-specific aliases:
   - `value` or legacy `price`;
   - `depart_date` or legacy `departure_at`;
   - `return_date` or legacy `return_at`;
   - optional `found_at`;
   - optional `actual`.
2. Drop `actual=false` rows before mapping to offers.
3. Store parsed `found_at` on the normalized Aviasales item and use it as `FlightOffer.observed_at`
   when present.
4. Keep `Freshness.CACHED` and `requires_live_confirmation=True`; latest prices are not live
   inventory.

## Consequences

- Latest-period radar can safely use docs-style fixtures without inventing freshness.
- Existing legacy-shaped fixtures still work through aliases.
- Rate-limit header metadata and endpoint-specific cache storage remain future hardening work.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
