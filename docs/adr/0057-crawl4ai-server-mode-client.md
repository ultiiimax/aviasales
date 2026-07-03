# ADR 0057: Crawl4AI Server Mode Client

Date: 2026-06-29

## Status

Accepted.

## Context

The optional deal-discovery compose profile now runs an internal Crawl4AI service, but Flight Hunter
only used the Python library mode. The monster plan calls for Playwright/Scrapling/Crawl4AI
integration, while the provider rules require disabled-by-default behavior, URL safety and no raw
payload leakage.

## Decision

- Keep `CRAWL4AI_ENABLED=false` and `CRAWL4AI_MODE=library` as defaults.
- Add `CRAWL4AI_MODE=server` for self-hosted internal Crawl4AI.
- Use the documented `POST /md` endpoint with a minimal JSON payload:
  `{ "url": "...", "f": "raw" }`.
- Validate the target URL with Flight Hunter's public HTTP URL policy before any library import or
  HTTP request.
- Support optional `CRAWL4AI_API_TOKEN` as an Authorization bearer token.
- Classify server errors into stable codes such as `crawl4ai_auth_failed`,
  `crawl4ai_rate_limited`, `crawl4ai_http_<status>` and `crawl4ai_server_unavailable`.

## Consequences

- The compose Crawl4AI service can be used by deal discovery and source smoke checks when explicitly
  enabled.
- Smoke output remains summary-only and never includes markdown content or server tokens.
- Server mode still does not enable hooks, JavaScript execution, login/cookie flows, proxies,
  CAPTCHA bypass or aggressive polling.
