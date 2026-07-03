# ADR 0110: Source Contract Egress Policy Metadata

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter already keeps provider/source readiness in a source contract catalog. Operators still
need a compact way to audit which integrations are expected to make outbound calls, which are
self-hosted components, and which dynamic URL fetches are guarded by URL policy.

## Decision

- Add `egress_policy` to `SourceContract`, `SourceReadiness` and the `/api/v1/source-contracts`
  response.
- Keep values descriptive and secret-free: fixed public API origins, self-hosted base URL hostnames,
  disabled-until-approved markers, and dynamic URL policy markers.
- Do not expose tokens, full URLs with paths/query strings, raw payloads, callback data or user
  identifiers.
- Keep this as operator-visible metadata, not a replacement for runtime provider policy or
  network-level egress controls.

## Consequences

- Admin/source-contract UI and API callers can see expected egress shape per source.
- SearXNG/Crawl4AI dynamic page fetches are visibly tied to `DealUrlPolicy`.
- Broader outbound firewall enforcement remains an operations layer.
