# ADR 0069: Web cached radar controls

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The cached radar API exposes Aviasales Data `search_by_price_range`, `month-matrix` and
`nearest-places-matrix`, but the primary FastAPI-served workbench did not offer a way to request
those hints. Leaving the feature only in OpenAPI made it hard to use in the self-hosted family UI.

## Decision

Add a compact `Cached radar` action to the existing route form.

The web UI now:

- includes `Radar min` and `Radar max` fields in integer minor units;
- calls `POST /api/v1/searches/cached-radar` for `price_range`, `month_matrix` and
  `nearest_places_matrix`;
- renders results into a separate `cached-radar-list` section instead of merging them into the main
  ranked search offers;
- displays denial codes such as `credentials_missing` when no Aviasales Data token is configured;
- keeps manual confirmation actions available for cached radar offers.

## Consequences

Positive:

- The broader cached radar surface is now usable from the main self-hosted web workbench.
- Cached hints remain visually separate from exact-date search, live observations and deal
  candidates.

Tradeoff:

- This is still the compact built-in workbench. A richer PWA view with segmented radar mode controls
  can be added later.

## Verification

- `uv run pytest tests/unit/api/test_web_ui.py --quiet` -> 1 passed.
- `uv run ruff format --check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/web.py tests/unit/api/test_web_ui.py`
  -> All checks passed.
- Extracted inline script from `render_index_html()` and parsed it with Node
  `new Function(script)` -> `script syntax ok`.
