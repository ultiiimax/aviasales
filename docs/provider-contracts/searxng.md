# SearXNG Contract Notes

Last verified: 2026-06-29

Official references:

- https://docs.searxng.org/dev/search_api.html
- https://docs.searxng.org/admin/installation-docker.html
- Docker Hub tags checked 2026-06-29: `searxng/searxng:2026.6.29-0e990f78a`
- Search API checked 2026-06-29: `/search` supports `format=json`, and public instances may
  disable JSON/CSV/RSS formats.

## Scope

SearXNG is a discovery source for possible public deal pages, not a price provider and not a live
flight-search API. Flight Hunter uses it only to find URL candidates that are later converted into
manual-verification `DealCandidate` hints.

## Contract Rules

- Disabled by default through `SEARXNG_ENABLED=false`.
- Use self-hosted SearXNG for JSON search. Public instances can disable JSON/CSV/RSS formats.
- Use `/search` with `format=json`; never treat result title/content as trusted pricing data.
- Use a bounded query strategy per manual discovery request. The production strategy currently
  tries at most three route/month variants: sale/discount, promo/special-offer and suspicious
  error-fare/forum wording. These queries create URL candidates only.
- Result title/content are URL-discovery metadata only. They must not populate extracted price,
  route, travel dates, candidate confidence, or visible candidate summary text.
- Do not store raw search payloads in normal production tables.
- Do not send secrets or provider tokens; SearXNG smoke output is summary-only.
- Transport, timeout, rate-limit and invalid-JSON failures must be wrapped as typed
  `SearxngClientError` codes (`searxng_timeout`, `searxng_unavailable`,
  `searxng_rate_limited`, `searxng_invalid_json`) without echoing response payload text.
- Deal candidates created from SearXNG results must remain outside priced offer ranking.
- Result URLs are treated as untrusted input and must pass Flight Hunter's public-http URL policy
before any Crawl4AI fetch. Private IPs, localhost/internal hosts, credentials and non-default
  ports are rejected. Legacy IPv4 aliases such as integer, hex, octal or shortened dotted forms are
  rejected before fetch.
- If `DEAL_DISCOVERY_ALLOWED_HOSTS` is set, result URLs outside those exact hosts or wildcard
  subdomain patterns fail before any Crawl4AI fetch with `deal_url_host_not_allowed`.
- SearXNG may be run through the optional `deal-discovery` compose profile. The default local image
  tag is pinned through `SEARXNG_IMAGE` and must be re-verified before production updates.
- The compose profile exposes SearXNG only on the internal Docker network by default. Do not publish
  the search UI/API publicly without access controls and rate limiting.
- The compose service has a local HTTP healthcheck; admin dashboards read persisted source health
  events rather than running SearXNG searches from GET endpoints.

## Local Smoke

```powershell
uv run flight-hunter-source-smoke --source searxng
```

Expected no-config result is `searxng_disabled`. Enable with:

```powershell
SEARXNG_ENABLED=true
SEARXNG_BASE_URL=http://searxng:8080
```
