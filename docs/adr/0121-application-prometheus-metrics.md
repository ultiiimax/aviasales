# ADR 0121: Application Prometheus metrics

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

`MEGA_MONSTER_PLAN.md` lists Prometheus metric names for provider calls, browser observation jobs,
parser extraction, search duration and sent alerts. Worker health already has a dedicated
Prometheus exporter, but the application-level names were not exposed yet.

The structured observability event slice added safe low-cardinality events. Reusing those events
keeps metric labels aligned with the privacy boundary: no tokens, raw payloads, full URLs, Telegram
chat ids, callback data, message text or durable secret-like ids become labels.

## Decision

Add a process-local metrics recorder behind `log_event` and expose it at `GET /api/v1/metrics` as
Prometheus text:

- `flight_hunter_provider_requests_total`
- `flight_hunter_provider_errors_total`
- `flight_hunter_browser_observation_jobs_total`
- `flight_hunter_parser_offers_extracted_total`
- `flight_hunter_search_duration_seconds` summary
- `flight_hunter_alerts_sent_total`

Labels are limited to safe dimensions such as provider, endpoint, status, error class, source,
confidence and reason. IDs remain event log fields only and are intentionally not metric labels.

## Consequences

Positive:

- The metric names required by the plan are scrapeable without provider calls.
- Existing structured events feed both logs and counters.
- Tests cover label escaping and absence of secret-like ids in metric output.

Tradeoffs:

- These metrics are process-local and reset on process restart. They are operational telemetry, not
  durable product analytics or billing counters.
- Multi-process deployments require Prometheus to scrape each process or a future aggregation layer.

## Verification

- `uv run pytest tests/unit/ops/test_application_metrics.py tests/unit/api/test_metrics_api.py -q`
  -> 3 passed.
