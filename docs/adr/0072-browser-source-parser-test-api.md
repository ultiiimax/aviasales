# ADR 0072: Browser source parser test API

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The monster plan calls for `POST /api/v1/browser-sources/{source_id}/test-parser`. Operators need a
safe way to verify sanitized parser fixtures through the same API response schema used by the web
and personal observer flow, without starting Playwright, touching live sites or saving raw HTML.

## Decision

Add an auth-gated parser test endpoint:

`POST /api/v1/browser-sources/{source_id}/test-parser`

The request accepts:

- `search_intent`, using the existing `SearchRequestBody`;
- sanitized `html`, capped at 500 KB;
- optional `final_url` and `title`.

The endpoint:

- requires household/user auth context;
- validates the source exists in the personal observer catalog and allows browser observation;
- validates `final_url` as public `http(s)` without credentials and with a host from
  `PERSONAL_OBSERVER_ALLOWED_HOSTS`;
- runs `BrowserOfferParserPipeline`;
- returns `BrowserObservedOfferResponse` rows, parser warnings, snapshot hashes and rejected price
  candidates;
- never returns raw HTML or candidate context and does not persist anything.

## Consequences

Positive:

- Parser diagnostics are available without live browser work.
- Tests and operators can exercise the API contract with sanitized fixtures.
- The endpoint keeps raw DOM payloads out of logs/storage/response bodies.

Tradeoff:

- The endpoint is intended for operator/debug workflows, not for the main family web screen.
- It does not prove live navigation; `flight-hunter-browser-smoke` and the worker/runner cover
  runtime startup and queued execution separately.

## Verification

- `uv run pytest tests/unit/api/test_api_app.py --quiet` -> 20 passed.
- `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_api_app.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 88 source files.
