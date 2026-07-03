# ADR 0031: Aviasales Data Latest Prices

Date: 2026-06-29

## Status

Accepted for explicit cached latest-period radar.

## Context

The Aviasales Data API is cached Travelpayouts data, not live availability. Flight Hunter already
uses exact-date `prices_for_dates` for normal adapter search and `grouped_prices` for broader
cached radar. The monster plan calls for broader Aviasales Data endpoint coverage while preserving
freshness and provider-policy semantics.

Official references rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `LatestPricesQuery` for `/aviasales/v3/get_latest_prices`.
2. Send the Travelpayouts token only in `X-Access-Token`, never in query params.
3. Reuse the normalized cached offer mapper so `Freshness.CACHED` and
   `requires_live_confirmation=True` remain visible.
4. Keep `latest_prices()` as an explicit adapter method. Do not use it for default exact-date
   search ranking.
5. Keep child/infant passenger mixes fail-closed before HTTP calls until provider-specific pricing
   is modeled.

## Consequences

- Future matrix/deal workflows can ask for latest cached prices over a period.
- UI must still label these results cached/indicative and show observed time.
- Popular routes/directions endpoints remain separate future work.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
