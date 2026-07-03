# ADR 0081: Deal Discovery Query Strategy and Source Contracts

Date: 2026-06-29

## Status

Accepted.

## Context

Deal discovery is intentionally not a provider of confirmed airfare prices. It combines SearXNG
URL discovery and Crawl4AI markdown extraction to create manual-verification `DealCandidate`
hints. The first implementation used a single route query, which made discovery brittle and left
SearXNG/Crawl4AI invisible in the admin source contract surface.

Operators need to see that this pipeline is disabled by default, user-action-only, outside merged
ranking, and blocked until the optional self-hosted components are enabled.

## Decision

- Add `DealQueryBuilder.build_queries()` with a bounded strategy of at most three route/month
  variants: sale/discount, promo/special-offer and suspicious error-fare/forum wording.
- Keep `build()` as a compatibility wrapper returning the first query.
- Make `DealDiscoveryService` iterate the bounded queries, dedupe canonical URLs across all query
  results, and stop once the requested candidate limit is reached.
- Add source contract catalog entries for `searxng`, `crawl4ai` and `deal_discovery`.
- Mark those sources as `deal_feed`, `candidate_only`, background-disallowed and user-action-only.
- Default them to disabled unless `SEARXNG_ENABLED` and/or `CRAWL4AI_ENABLED` are true.
- Extend admin source health items with policy fields so the web/admin surface can explain why the
  pipeline is unavailable without issuing live searches or crawler calls.

## Consequences

- Manual discovery has broader recall while remaining bounded and deterministic.
- Deal candidates remain untrusted hints and cannot enter priced offer ranking.
- Admin GET endpoints still read durable/configured state only; they do not call SearXNG,
  Crawl4AI or travel providers.
- Future query variants must remain bounded, policy-reviewed and covered by unit tests.
