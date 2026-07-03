# ADR 0028: Aviasales Data Grouped Prices

Date: 2026-06-29

## Status

Accepted for the broader cached Aviasales Data slice.

## Context

The first Aviasales Data adapter slice supported only `/v3/prices_for_dates`, which is useful for
exact cached searches but not enough for flexible-date radar. The monster plan requires at least one
broader matrix/latest endpoint while preserving cached semantics and avoiding live claims.

Official Travelpayouts Aviasales Data API documentation was rechecked on 2026-06-29:

- https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- https://support.travelpayouts.com/hc/en-us/articles/4402565416594-API-rate-limits

## Decision

1. Add `/aviasales/v3/grouped_prices` support to `AviasalesDataClient`.
2. Keep token transport in the `X-Access-Token` header and never in query params.
3. Parse `data` as a mapping of grouped cached offers into the existing normalized
   `AviasalesDataItem` shape.
4. Add `AviasalesDataQueryPlanner.plan_grouped_prices` and `AviasalesDataAdapter.grouped_prices`.
5. Keep `DemoSearchService` exact searches on `prices_for_dates`; grouped prices are an explicit
   cached radar call for future matrix/deal workflows.
6. Continue to fail closed for child/infant pricing until provider-specific passenger semantics are
   modeled.

## Consequences

- Flight Hunter can build cached date/month radar without pretending it is live inventory.
- The broader endpoint is covered by transport/adapter tests and does not run live in CI.
- Latest/popular endpoints remain future work and must get their own explicit planner/tests.

## Verification

- `tests/unit/providers/aviasales_data/test_client.py`
- `tests/unit/providers/aviasales_data/test_query_planner.py`
- `tests/unit/providers/aviasales_data/test_adapter.py`
- `docs/provider-contracts/aviasales-data.md`
