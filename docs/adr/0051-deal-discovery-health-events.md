# ADR 0051: Deal Discovery Health Events

Date: 2026-06-29

## Status

Accepted for operational visibility.

## Context

Deal discovery can fail because SearXNG is unavailable, Crawl4AI is disabled/unavailable, or URL
policy rejects an unsafe result URL. Before this slice, these failures were not consistently exposed
as typed API responses or persisted source health events.

## Decision

1. Record best-effort `source_health_events` with `source_id=deal_discovery` for successful and
   failed manual deal discovery API calls.
2. Convert URL policy failures into a stable `deal_discovery_url_rejected` API code.
3. Convert SearXNG/Crawl4AI client failures into a stable `deal_discovery_source_failed` API code.
4. Keep event recording best-effort so health write failures do not turn manual discovery into a
   user-facing 500.
5. Do not run live checks from admin source health GET endpoints.

## Consequences

- The admin source health API can show deal discovery failures from persisted facts.
- Unsafe upstream URLs fail closed with a typed response.
- Deal discovery remains disabled by default and still produces manual-verification candidates
  only.

## Verification

- `tests/unit/api/test_api_app.py`
- `tests/unit/api/test_admin_source_health_api.py`
- `tests/unit/deals`
