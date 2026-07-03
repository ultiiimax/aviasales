# ADR 0049: Deal Discovery URL Policy

Date: 2026-06-29

## Status

Accepted for deal discovery hardening.

## Context

SearXNG result URLs and feed/page text are untrusted. Before Crawl4AI fetches any page, Flight
Hunter needs an explicit URL policy so discovery cannot be turned into localhost/private-network
fetching or credential-bearing requests. Deal discovery remains manual-verification candidate
generation, not a source of confirmed fares.

Official references were rechecked on 2026-06-29:

- https://docs.searxng.org/dev/search_api.html
- https://docs.crawl4ai.com/core/simple-crawling/

## Decision

1. Add `DealUrlPolicy` for public `http`/`https` URLs.
2. Reject localhost/internal hosts, private/link-local/reserved IP literals, IPv6 zone ids,
   credential-bearing URLs, unsupported schemes and non-default ports.
3. Apply the policy when parsing SearXNG result URLs.
4. Apply the policy in `DealDiscoveryService` before calling any markdown client.
5. Apply the policy in `Crawl4AiMarkdownClient` before disabled/import/runtime checks.
6. Cap markdown size before extraction.

## Consequences

- SearXNG can still be self-hosted locally as the search API, while discovered result URLs must be
  public fetch targets.
- Crawl4AI remains disabled by default and cannot be pointed at obvious private/internal targets
  through normal service paths.
- Legacy IPv4 aliases such as integer, hex, octal or shortened dotted forms are rejected before
  fetch, even when a lower-level HTTP stack might resolve them.
- CI remains fixture-only; no live crawling is added.

## Verification

- `tests/unit/deals/test_url_policy.py`
- `tests/unit/deals/test_searxng_client.py`
- `tests/unit/deals/test_crawl4ai_client.py`
- `tests/unit/deals/test_service.py`
