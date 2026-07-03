# ADR 0036: Source Smoke And Deal Discovery Health

Date: 2026-06-29

## Status

Accepted for operational source health checks.

## Context

Deal discovery now has SearXNG and Crawl4AI clients, but operators still needed a safe way to check
whether optional local sources are configured before enabling user-triggered discovery. The monster
plan calls for `flight-hunter-source-smoke --source searxng` and clear no-credentials/no-config
states.

## Decision

1. Add `flight-hunter-source-smoke` as a summary-only operational CLI.
2. Support `aviasales_data`, `searxng` and `crawl4ai` source names.
3. Delegate `aviasales_data` to the existing sanitized Travelpayouts smoke check.
4. Keep SearXNG and Crawl4AI disabled by default. Disabled or missing-url states return structured
   JSON and exit non-zero.
5. Never print raw search payloads, markdown, provider secrets, URLs with tokens or extracted fare
   text in smoke output.
6. Add an optional `deal-discovery` compose profile with SearXNG for local self-hosting. The image
   remains configurable via `SEARXNG_IMAGE` so production deployers can pin it.

## Consequences

- Operators can verify source readiness without running the full web flow.
- CI remains live-call free because tests inject fake clients and sanitized fixtures.
- SearXNG/Crawl4AI remain candidate-discovery helpers, not price truth and not ranked providers.
- Crawl4AI still requires the optional `crawler` dependency group when used outside tests.

## Verification

- `tests/unit/ops/test_source_smoke.py`
- `tests/unit/ops/test_makefile_commands.py`
- `docker compose config`
