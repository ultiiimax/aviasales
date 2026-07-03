# ADR 0073: Personal observation confirm and mark-stale API

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The monster plan includes:

- `POST /api/v1/personal-observations/{id}/confirm`
- `POST /api/v1/personal-observations/{id}/mark-stale`

Flight Hunter already has an append-only manual price confirmation ledger. Personal observation
confirmation should reuse that ledger instead of overwriting parser/provider facts or mutating price
history.

## Decision

Add two authenticated endpoints:

- `POST /api/v1/personal-observations/{job_id}/confirm`
- `POST /api/v1/personal-observations/{job_id}/mark-stale`

Both endpoints:

- require household/user auth context;
- verify the personal observation job belongs to that household/user;
- append a `manual_price_confirmations` row with `target_kind=browser_observation` and
  `target_id=<job_id>`;
- return the standard `ManualPriceConfirmationResponse`;
- do not alter the original job, parser output or provider facts.

`confirm` accepts `confirmed`, `price_changed`, `sold_out` or `bought`, with an optional price pair.
`mark-stale` accepts `price_changed`, `sold_out` or `wrong_route` and never accepts a price.

## Consequences

Positive:

- The plan endpoints exist without creating a second confirmation model.
- Confirmation and stale states remain append-only and auditable.
- Household isolation uses the same job ownership check as `GET /personal-observations/{job_id}`.

Tradeoff:

- Job status remains the original worker/parser status; user confirmation state is read from the
  ledger.

## Verification

- `uv run pytest tests/unit/api/test_api_app.py --quiet` -> 21 passed.
- `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 88 source files.
