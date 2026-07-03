# ADR 0067: Aviasales Data date-matrix cached pricing

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

`POST /api/v1/searches/date-matrix` already produced a pure planning matrix for flexible dates, but
it did not attach available cached prices. The Aviasales Data adapter already supports
`/v2/prices/week-matrix`, which is documented as cached Travelpayouts/Aviasales data and is
appropriate for flexible-date hints when shown with freshness and live-confirmation caveats.

The provider contract was rechecked on 2026-06-29 using the official Travelpayouts Data API and
rate-limit documentation:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

Extend the date-matrix request/response so the endpoint can optionally price cells with cached
Aviasales Data `week-matrix` offers:

- route fields are optional; without `origin` and `destination` the endpoint remains a no-provider
  planning matrix and returns `route_required_for_pricing`;
- if Aviasales Data is not configured, the endpoint returns `aviasales_data_credentials_missing`
  without making an HTTP call;
- child/infant passenger mixes fail closed with `passenger_mix_not_supported` until provider-specific
  passenger pricing is modeled;
- provider authorization uses `ExecutionContext.API_REQUEST` because this endpoint is driven by an
  HTTP request rather than a scheduler pass;
- only `actual=true` rows mapped by the Aviasales Data client can become priced cells;
- cells expose `amount_minor`, `currency`, `provider_id`, `freshness`, `observed_at` and
  `requires_live_confirmation`.

The endpoint does not create booking/search links and does not label cached data as live.

## Consequences

Positive:

- Flexible-date UI/API consumers can show real cached Aviasales Data hints when credentials are
  configured.
- No-credentials demo behavior remains graceful and deterministic.
- Provider-call count and denial reasons make degraded behavior explicit.

Tradeoffs:

- This only covers the week-level matrix path. Month-level and nearby-place matrix product surfaces
  remain separate slices.
- Cached prices still need external confirmation before purchase.

## Verification

- `uv run pytest tests/unit/api/test_date_matrix_api.py tests/unit/providers/aviasales_data/test_adapter.py --quiet`
  -> 14 passed.
- `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_date_matrix_api.py`
  -> 2 files already formatted.
