# ADR 0104: Deal discovery compose server-mode default

Date: 2026-06-29

## Status

Accepted.

## Context

The optional Docker Compose `deal-discovery` profile starts pinned internal SearXNG and Crawl4AI
services. Before this decision, API and worker containers still defaulted `CRAWL4AI_MODE` to
`library`, so enabling `CRAWL4AI_ENABLED=true` inside the compose stack could try to import the
local Crawl4AI library instead of using the internal `crawl4ai:11235` service.

## Decision

Within `compose.yaml`, default `CRAWL4AI_MODE` to `server` for API and worker containers. The
application default remains `library` outside compose, and users can still override the mode through
the environment.

Add `make compose-deals-config` so operators can render and inspect the effective pinned
deal-discovery profile without starting containers.

## Consequences

- Compose deal-discovery experiments use the pinned internal Crawl4AI service by default.
- Local non-compose runs keep the existing library default.
- Deployment review has a stable Make target and tests assert the profile stays pinned/internal.

## Verification

- Compose config tests assert pinned image tags, no host port publishing and server-mode default.
- Makefile tests assert the new `compose-deals-config` target.
