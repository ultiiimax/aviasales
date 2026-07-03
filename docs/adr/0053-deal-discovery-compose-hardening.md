# ADR 0053: Deal Discovery Compose Hardening

Date: 2026-06-29

## Status

Accepted for local self-hosted deal-discovery experiments.

## Context

Deal discovery uses SearXNG as a candidate URL discovery source and Crawl4AI as an optional markdown
extraction helper. Both are disabled by default and are not price-truth providers. The existing
compose profile used a floating SearXNG image and did not model Crawl4AI as an operational service,
which made the local self-hosted path less reproducible.

Official references checked on 2026-06-29:

- SearXNG Docker installation: `https://docs.searxng.org/admin/installation-docker.html`
- SearXNG Search API: `https://docs.searxng.org/dev/search_api.html`
- Crawl4AI Docker deployment: `https://docs.crawl4ai.com/core/docker-deployment/`
- Crawl4AI simple crawling: `https://docs.crawl4ai.com/core/simple-crawling/`
- Docker Hub tags:
  `searxng/searxng:2026.6.29-0e990f78a`, `unclecode/crawl4ai:0.8.9`

## Decision

- Pin the default local SearXNG image tag to `searxng/searxng:2026.6.29-0e990f78a`.
- Add a Crawl4AI service to the optional `deal-discovery` compose profile, pinned to
  `unclecode/crawl4ai:0.8.9`.
- Expose both services only on the internal Docker network by default. Do not publish SearXNG or
  Crawl4AI host ports from the default compose profile.
- Add HTTP healthchecks for both services.
- Keep Flight Hunter's default Crawl4AI integration in `library` mode. Raw server REST integration
  requires a separate stable client/contract slice before production use.

## Consequences

- `docker compose --profile deal-discovery config` now describes the optional deal-discovery
  runtime more honestly and reproducibly.
- Local operators can still override `SEARXNG_IMAGE` and `CRAWL4AI_IMAGE`, but must re-verify image
  tags before updates.
- This is not a full production deployment: egress controls, resource limits, secrets, backups and
  monitoring runbooks remain separate hardening work.
