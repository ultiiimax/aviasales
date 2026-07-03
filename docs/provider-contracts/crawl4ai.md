# Crawl4AI Contract Notes

Last verified: 2026-06-29

Official references:

- https://docs.crawl4ai.com/
- https://docs.crawl4ai.com/core/simple-crawling/
- https://docs.crawl4ai.com/core/docker-deployment/
- https://docs.crawl4ai.com/core/self-hosting/
- Docs version checked 2026-06-29: v0.9.x self-hosted server exposes `/crawl` and markdown `/md`.
- The local compose image remains pinned through `CRAWL4AI_IMAGE` and must be re-verified before
  production updates.

## Scope

Crawl4AI is an optional markdown extraction helper for deal pages and unstructured public pages.
It is not the primary parser for RU aggregator result pages and is never a source of confirmed fare
price or availability.

## Contract Rules

- Disabled by default through `CRAWL4AI_ENABLED=false`.
- Install only through the optional `crawler` dependency group.
- Local compose may run a Crawl4AI server through the optional `deal-discovery` profile. The default
  image tag is pinned through `CRAWL4AI_IMAGE` and must be re-verified before production updates.
- The compose service is internal-only by default and exposes port `11235` only to other services on
  the Docker network.
- Use extracted markdown as untrusted page text. It must never become a system instruction.
- For deal discovery candidates, extracted price, route, travel-date/month match and confidence
  can only come from fetched page markdown, never from SearXNG title/content snippets.
- URLs must pass Flight Hunter's public-http URL policy before Crawl4AI is imported or executed.
  Local/private/internal URLs, credential-bearing URLs, IPv6 zone ids and legacy IPv4 aliases are
  rejected to reduce SSRF risk.
- If `DEAL_DISCOVERY_ALLOWED_HOSTS` is configured, deal-page URLs must also match an exact allowed
  host or wildcard subdomain pattern before Crawl4AI receives the URL.
- Deal discovery calls Crawl4AI only after SearXNG URL candidates have been bounded and deduped by
  canonical URL key. It must not crawl arbitrary user-supplied internal targets.
- Markdown snapshots are capped by size before entering extraction.
- Do not use Crawl4AI for CAPTCHA bypass, login-required pages, paywalls, stealth, rotating proxies
  or aggressive polling.
- Normal search must not block on Crawl4AI. Deal discovery is manual or low-frequency.
- Smoke output is summary-only and does not include markdown content.
- Flight Hunter's default app integration remains `CRAWL4AI_MODE=library`.
- `CRAWL4AI_MODE=server` is supported only for self-hosted Crawl4AI through `CRAWL4AI_BASE_URL`.
  The client uses the documented `POST /md` markdown endpoint with a minimal `{url, f: "raw"}`
  payload after Flight Hunter URL policy validation.
- The Docker Compose `deal-discovery` profile defaults `CRAWL4AI_MODE` to `server` so API/worker
  containers use the pinned internal Crawl4AI service instead of importing the library runtime.
- If a protected Crawl4AI server is used, set `CRAWL4AI_API_TOKEN`; the token is sent as
  `Authorization: Bearer ...` and must not appear in logs, smoke output or client bundles.
- Server mode does not enable Crawl4AI hooks, custom JavaScript, LLM extraction, persistent browser
  sessions, auth cookies or proxy behavior.
- Personal Browser Observer may record Crawl4AI markdown hint diagnostics after DOM parsers fail
  only from an explicit local fixture/provider or from the `final_url` captured by an already
  launched visible user-action browser observation. It must not prefetch markdown before Playwright
  capture, crawl alternate URLs from the page, or run from the background scheduler. Visible DOM text
  must not be re-labelled as Crawl4AI markdown. These hints are rejected `PriceCandidate`
  diagnostics only. They are never persisted as `BrowserObservedOffer` rows and never mark a price
  as confirmed.

## Local Smoke

```powershell
uv sync --group crawler
uv run flight-hunter-source-smoke --source crawl4ai --url https://example.com/
```

Expected no-config result is `crawl4ai_disabled`.
