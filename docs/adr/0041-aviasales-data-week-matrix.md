# ADR 0041: Aviasales Data Week Matrix

Date: 2026-06-29

## Status

Accepted for explicit cached flexible-date radar.

## Context

Flight Hunter already uses Aviasales Data `/v3/prices_for_dates` for exact cached searches and
has explicit cached radar methods for `/v3/grouped_prices` and `/v3/get_latest_prices`. The monster
plan also calls for matrix-style cached coverage without treating Aviasales Data as live inventory.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `WeekMatrixQuery` for `/v2/prices/week-matrix`.
2. Send the Travelpayouts token only through `X-Access-Token`, never query params.
3. Parse week-matrix rows with endpoint-specific fields: `value`, `depart_date`, `return_date` and
   `actual`.
4. Drop `actual=false` rows instead of showing stale/expired cached prices as available offers.
5. Do not invent Aviasales booking/search links; week-matrix rows normalize to cached offers without
   a provider link path.
6. Keep the endpoint behind an explicit `AviasalesDataAdapter.week_matrix()` method. Normal exact
   search continues to use `prices_for_dates`.

## Consequences

- Flexible-date workflows can request a week-level cached radar without live claims.
- UI and Telegram must still label the results cached and require external confirmation.
- Month matrix, nearest-places matrix, price-range and popular endpoints remain future explicit
  provider slices.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
