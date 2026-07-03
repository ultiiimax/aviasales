# ADR 0092: Deal discovery markdown evidence guard

Date: 2026-06-29

## Status

Accepted.

## Context

Deal discovery uses SearXNG to find candidate public deal pages and Crawl4AI to turn those pages
into markdown for manual-verification hints. SearXNG result titles and snippets can contain stale,
wrong, SEO-injected or model-hostile text. Treating those snippets as price evidence would violate
Flight Hunter's rule that deal feeds are candidate generators, not sources of fare truth.

## Decision

`DealMarkdownExtractor` now extracts price, route, date/month match and confidence only from fetched
page markdown. SearXNG result title/content are not used for extracted fields, candidate confidence
or visible candidate summary text.

`DealDiscoveryService` no longer passes the SearXNG title into the markdown fetch as page title
evidence. Candidate title is derived from a markdown heading or Crawl4AI page title when available,
with a neutral URL-based fallback.

Confidence remains `low` unless markdown contains all of:

- an airfare-sized RUB price;
- token-bounded origin and destination IATA codes;
- the exact travel date or matching travel month from the intent.

Deal candidates still require manual verification and remain outside priced offer ranking.

## Consequences

- Search snippets can still help discover URLs, but cannot manufacture a price, route or date.
- Markdown-only hints are safer but may miss deals written with natural-language Russian month names;
  that parsing belongs in a future extractor enhancement.
- The domain model still does not expose explicit evidence provenance fields. If UI needs to show
  per-field provenance, that should be a separate schema/migration slice.

## Verification

- Extractor tests cover adversarial SearXNG snippets, exact-date markdown evidence, matching month
  evidence, mismatched month downgrade and ancillary price filtering.
- Service tests cover that SearXNG titles are not passed as markdown title evidence and do not leak
  snippet prices into candidate title/summary.
