# ADR 0060: Deal Discovery URL Dedupe

Date: 2026-06-29

## Status

Accepted.

## Context

SearXNG can return the same deal page multiple times with tracking query parameters, fragments or
minor URL formatting differences. Fetching every duplicate through Crawl4AI wastes optional crawler
capacity and can create repeated manual-verification candidates.

## Decision

- Canonicalize search-result URLs before markdown fetch.
- Deduplicate by lowercase scheme/host, normalized trailing slash, sorted non-tracking query
  parameters and no fragment.
- Ignore common tracking query parameters such as `utm_*`, `gclid`, `fbclid` and `yclid`.
- Continue iterating through search results until the requested number of unique candidates is
  reached or the result set is exhausted.

## Consequences

- Deal discovery avoids duplicate markdown fetches and duplicate candidate rows for the same page.
- Different URLs with meaningful query parameters remain distinct.
- This does not make deal candidates price truth; they still require manual verification.
