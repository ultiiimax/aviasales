# ADR 0074: Personal browser source catalog

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

`GET /api/v1/browser-sources` originally returned only the demo live-observer source. The personal
observer flow, parser-test API and web workbench also use RU aggregator sources such as Tutu,
Yandex Travel and OneTwoTrip. Source discovery should show these operator-controlled personal
observer sources without enabling background browser work.

## Decision

Extend `GET /api/v1/browser-sources` with personal observer sources from
`default_ru_aggregator_specs()` where `browser_observation_allowed=true`.

Each personal source response:

- is enabled only when `PERSONAL_OBSERVER_ENABLED=true`, the source is present in
  `RU_AGGREGATORS_ENABLED` and at least one source host is present in
  `PERSONAL_OBSERVER_ALLOWED_HOSTS`;
- always reports `background_allowed=false`;
- always reports `user_action_required=true`;
- reports `permission_status=active` when host policy is configured, otherwise `missing`;
- reports `current_health=healthy`, `disabled` or `host_not_allowed` from local config only.

## Consequences

Positive:

- API/UI source discovery now matches the personal observer sources accepted by parser-test and job
  creation flows.
- Personal sources remain disabled by default and cannot be mistaken for scheduler-safe sources.
- No external calls are made by the discovery endpoint.

Tradeoff:

- The catalog exposes local configuration readiness, not live source availability.

## Verification

- `uv run pytest tests/unit/api/test_live_observations_api.py tests/unit/api/test_web_ui.py --quiet`
  -> 6 passed.
- `uv run ruff format --check src/flight_hunter/api/app.py tests/unit/api/test_live_observations_api.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/api/app.py tests/unit/api/test_live_observations_api.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 88 source files.
