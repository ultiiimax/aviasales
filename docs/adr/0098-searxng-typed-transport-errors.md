# ADR 0098: SearXNG typed transport errors

Date: 2026-06-29

## Status

Accepted.

## Context

SearXNG is a URL-discovery source for deal candidates. It is not a price provider, and worker/source
health needs stable machine-readable error codes rather than raw transport exceptions or raw
payload snippets. The official SearXNG Search API contract was checked on 2026-06-29:
https://docs.searxng.org/dev/search_api.html

The client already rejected unsafe result URLs and malformed result shapes, but transport failures
and invalid JSON could leak as implementation exceptions (`httpx` / `ValueError`) instead of typed
source errors.

## Decision

Wrap SearXNG fetch/parsing failures in sanitized `SearxngClientError` codes:

- timeout -> `searxng_timeout`;
- other transport failure -> `searxng_unavailable`;
- HTTP 429 -> `searxng_rate_limited`;
- invalid JSON -> `searxng_invalid_json`;
- other HTTP 4xx/5xx remains `searxng_http_<status>`.

Invalid JSON errors do not echo response text, query strings or payload content.

## Consequences

- Deal discovery workers and source health events can classify SearXNG failures deterministically.
- Rate-limit events get a distinct code without being treated like generic HTTP failure.
- No raw SearXNG payloads are persisted or logged by this client change.

## Verification

- Unit tests cover 429, transport failure and invalid JSON without payload echo.
- Existing service tests still cover bounded query strategy and URL-policy enforcement.
