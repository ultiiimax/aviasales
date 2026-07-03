# ADR 0111: Deal Discovery Egress Allowlist

Date: 2026-06-29

## Status

Accepted.

## Context

Deal discovery fetches public URLs discovered by SearXNG through Crawl4AI after SSRF URL checks.
Operators may still want a stricter self-hosted deployment posture where crawler egress is limited
to known deal/forum/news domains.

## Decision

- Add optional `DEAL_DISCOVERY_ALLOWED_HOSTS`.
- Keep the default empty value compatible with existing behavior: any public `http`/`https` URL
  that passes `DealUrlPolicy` can be fetched.
- When configured, require exact host matches or wildcard subdomain patterns such as
  `*.example.com` before Crawl4AI receives a URL.
- Validate allowlist patterns through the same hostname normalization and internal-host/IP guards.
- Expose the configured shape through source contract `egress_policy` without paths, queries,
  tokens or raw result payloads.

## Consequences

- Operators can turn deal discovery into a constrained crawler without code changes.
- Off-allowlist URLs fail before markdown fetch with `deal_url_host_not_allowed`.
- This remains an application-layer guard; network firewall rules are still recommended for
  production deployments.
