# ADR 0120: Structured observability logging

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

`MEGA_MONSTER_PLAN.md` requires structured log events for search starts, provider calls, browser
observation jobs, parser extraction and sent alerts. Existing worker health and Prometheus surfaces
cover queue/process state, but operators still need low-cardinality application events that can be
sent to Loki or another log backend without scraping message text or provider payloads.

Provider and privacy rules prohibit logging secrets, raw payloads, signed URLs, callback data,
Telegram chat ids, provider query parameters or PII.

## Decision

Add `flight_hunter.ops.structured_logging.log_event`, which emits compact JSON lines on the
`flight_hunter.observability` logger. The helper normalizes safe scalar values, UUIDs, datetimes,
enums and short sequences, and omits `None` fields.

Emit these events:

- `search_started`: `search_id`, resolved `household_id` when authenticated, result counts and
  `duration_ms`.
- `provider_call`: Aviasales Data provider, stable endpoint name, HTTP status or transport error
  class and `duration_ms`.
- `browser_observation_started`: source id, durable `job_id`, `search_id`, attempt and fixture
  mode.
- `parser_result`: source id, offer count, confidence and parser warning codes.
- `alert_sent`: price-drop `watch_id`, notification id, household id and delivery attempt after
  Telegram send succeeds.

## Consequences

Positive:

- Operators can correlate core flows without enabling verbose HTTP/provider logs.
- Tests lock down that tokens, full URLs, raw HTML, Telegram chat ids and message text are absent
  from the new events.
- The helper is framework-independent and does not move logging into domain code.

Tradeoffs:

- `search_started` is emitted after the search result is available so the durable `search_id` and
  counts can be included. It still carries the plan-required event name.
- Provider call metrics are log events, not Prometheus counters. Prometheus counters remain a later
  broader metrics slice beyond the worker health exporter.

## Verification

- `uv run pytest tests/unit/api/test_api_app.py::test_search_endpoint_logs_safe_structured_started_event tests/unit/providers/aviasales_data/test_client.py::test_prices_for_dates_logs_safe_provider_call_event tests/unit/application/test_personal_observations.py::test_personal_observation_job_runs_and_persists_browser_offers tests/unit/providers/personal_observer/test_runner.py::test_runner_observes_fixture_without_live_browser_enabled tests/unit/application/test_telegram_notifications.py::test_linked_price_alert_is_delivered_once tests/unit/application/test_telegram_notifications.py::test_quiet_hours_defer_delivery_without_transport_call -q`
  -> 6 passed.
