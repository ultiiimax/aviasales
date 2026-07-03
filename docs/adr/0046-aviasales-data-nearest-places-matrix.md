# ADR 0046: Aviasales Data Nearest Places Matrix

Date: 2026-06-29

## Status

Accepted for explicit cached nearby-place radar.

## Context

The monster plan requires nearby discovery while respecting provider policy and cached/live
semantics. Travelpayouts Aviasales Data exposes `/v2/prices/nearest-places-matrix`, which returns
cached nearby-place directions. This is useful for hints around nearby airports/cities, but it is
not a live nearby-airport inventory API.

Official Travelpayouts references were rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `NearestPlacesMatrixQuery` for `/v2/prices/nearest-places-matrix`.
2. Use only the documented query parameters used by the endpoint: `origin`, `destination`,
   `currency`, `show_to_affiliates`, `distance`, and `limit`.
3. Parse rows with the shared matrix shape: `value`, `depart_date`, optional `return_date`,
   optional `found_at`, and `actual`.
4. Drop `actual=false` rows and do not invent booking/search links.
5. Expose an explicit `AviasalesDataAdapter.nearest_places_matrix()` method with a conservative
   default `distance_km=300`.
6. Mark Aviasales Data policy as supporting nearby cached radar, while docs continue to distinguish
   this from live nearby-airport availability.

## Consequences

- Nearby-place hints can be requested from cached Aviasales Data without live claims.
- The endpoint remains server-side and token-gated; CI uses mocked transport fixtures only.
- UI still needs a dedicated nearby-radar presentation layer before this becomes a user-facing
  workflow.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
- `tests/unit/application/test_source_contracts.py`
