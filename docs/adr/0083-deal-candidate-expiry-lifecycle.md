# ADR 0083: Deal Candidate Expiry Lifecycle

Date: 2026-06-29

## Status

Accepted.

## Context

Deal discovery creates manual-verification hints from SearXNG and Crawl4AI. Persistence already
stored an `expires_at` TTL and filtered expired rows, but the domain/API/UI did not expose that
lifecycle. Users could not see when a candidate hint should be considered stale, and the worker did
not clean expired deal candidates.

## Decision

- Add optional `expires_at` to `DealCandidate` with timezone-aware validation.
- Populate `expires_at` for immediate discovery responses using the configured
  `DEAL_CANDIDATE_TTL_SECONDS`.
- Read persisted candidate expiry back into domain objects and API responses.
- Add `DealCandidateRepository.cleanup_expired()` and run it in the worker TTL-cleanup phase.
- Expose `deal_candidates_deleted` in worker summaries.
- Render deal candidate expiry/freshness in the web workbench while keeping candidates outside
  priced offer ranking.

## Consequences

- Deal candidates now have a visible lifecycle and cannot silently look timeless.
- Expired candidates are still excluded from search responses and are also removed during worker
  cleanup.
- This is a lifecycle foundation only. Durable asynchronous deal-discovery jobs, per-step retries
  and richer source health remain separate follow-up slices.
