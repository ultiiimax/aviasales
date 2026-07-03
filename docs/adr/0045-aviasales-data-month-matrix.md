# ADR 0045: Aviasales Data Month Matrix

Date: 2026-06-29

## Status

Accepted for explicit cached month-level flexible-date radar.

## Context

The monster plan requires broader Aviasales Data coverage beyond exact-date searches, including
week and month matrices. Week matrix support already exists; month matrix adds a wider cached radar
for flexible date workflows while preserving Aviasales Data's cached semantics.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `MonthMatrixQuery` for `/v2/prices/month-matrix`.
2. Send the Travelpayouts token only through `X-Access-Token`, never query params.
3. Use endpoint-specific query params: `month`, `currency`, `market`, `show_to_affiliates`,
   `one_way`, optional `trip_duration`, and `limit`.
4. For round trips, compute a conservative whole-week `trip_duration` from the requested
   departure/return dates. For one-way trips, omit it.
5. Parse month-matrix rows with the shared matrix shape: `value`, `depart_date`, optional
   `return_date`, optional `found_at`, and `actual`.
6. Drop `actual=false` rows and do not invent booking/search links.

## Consequences

- Future flexible-date workflows can ask for a month-level cached radar without live claims.
- Results stay `Freshness.CACHED` and `requires_live_confirmation=True`.
- Nearest-places matrix and price-range endpoints remain future explicit provider slices.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
