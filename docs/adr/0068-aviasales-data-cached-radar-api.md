# ADR 0068: Aviasales Data cached radar API

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The Aviasales Data adapter already supports the documented cached radar endpoints
`/v3/search_by_price_range`, `/v3/grouped_prices`, `/v3/get_latest_prices`,
`/v2/prices/month-matrix` and `/v2/prices/nearest-places-matrix`, but some of these endpoints were
only reachable from adapter/client tests. Product code needed an explicit API surface for these
broader cached hints without mixing them into ranked exact-date search or presenting them as live
inventory.

The provider contract was rechecked on 2026-06-29 using the official Travelpayouts Data API and
rate-limit documentation:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

Add `POST /api/v1/searches/cached-radar` with explicit `radar_kind` values:

- `month_matrix`
- `nearest_places_matrix`
- `price_range`
- `grouped_prices`
- `latest_prices`

The endpoint:

- calls only the Aviasales Data adapter and only when credentials are configured;
- returns explicit denial codes instead of making a provider call when Aviasales Data is not
  requested, credentials are missing, or child/infant passenger mixes are present;
- accepts public price range bounds as integer minor units and converts them to provider major units
  only when they can be represented without rounding;
- uses `ExecutionContext.API_REQUEST`, not scheduler/worker context;
- returns normal `OfferResponse` rows with `freshness=cached`, `observed_at` and
  `requires_live_confirmation`;
- never creates booking/search links and never labels cached rows as live;
- keeps cached radar output separate from the main ranked search response.

## Consequences

Positive:

- Broader month and nearby-place cached hints are now available through product API calls.
- No-credentials demo mode remains deterministic and does not perform hidden provider calls.
- Existing adapter/client contract tests still own provider schema mapping.

Tradeoff:

- The endpoint returns cached radar offers only; it does not persist history or create watch
  snapshots.

## Verification

- `uv run pytest tests/unit/api/test_cached_radar_api.py tests/unit/providers/aviasales_data/test_adapter.py --quiet`
  -> 16 passed.
- `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_cached_radar_api.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 87 source files.
