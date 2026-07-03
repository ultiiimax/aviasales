# ADR 0099: Deal discovery partial page success

Date: 2026-06-29

## Status

Accepted.

## Context

Deal discovery uses SearXNG for URL candidates and Crawl4AI for page markdown. A single deal page
can fail markdown extraction because the page is unavailable, rate-limited, blocked by the local
crawler, or no longer public. The worker reliability rules require jobs not to lose partial success:
if another already-fetched page produced a valid `DealCandidate`, that candidate should not be
discarded just because a later page failed.

## Decision

`DealDiscoveryService.discover()` now treats per-page `Crawl4AiClientError` as a recoverable page
failure while iterating URL candidates:

- failed page fetches are skipped;
- the first markdown error is remembered;
- if at least one candidate is extracted, the service returns the partial candidate set;
- if every markdown fetch fails, the first typed Crawl4AI error is re-raised for normal
  retry/failure classification.

URL-policy errors are still fail-closed before markdown fetch.

## Consequences

- Deal discovery jobs can persist useful candidates from successful pages even when another page in
  the same manual discovery request fails.
- Complete crawler failure remains retryable through the existing job service path.
- No raw page payloads, SearXNG snippets or failed markdown content are persisted by this change.

## Verification

- Service tests cover partial page success and all-page-failure re-raise behavior.
- Existing job-service tests still cover source-error retry scheduling and URL-policy failure.
