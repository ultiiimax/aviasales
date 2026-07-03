# ADR 0029: Deal Discovery Candidates

Date: 2026-06-29

## Status

Accepted for the initial deal discovery foundation.

## Context

Flight Hunter should surface possible sales, promos and fare discussions, but deal feeds are not a
source of truth for ticket price or availability. The monster plan calls for SearXNG discovery,
Crawl4AI markdown extraction and deterministic `DealCandidate` values that require human
verification.

Official references rechecked on 2026-06-29:

- SearXNG Search API: https://docs.searxng.org/dev/search_api.html
- Crawl4AI project/docs: https://github.com/unclecode/crawl4ai and https://docs.crawl4ai.com/

## Decision

1. Add `src/flight_hunter/deals/` with query builder, SearXNG JSON client, Crawl4AI markdown
   boundary, markdown extractor and service orchestration.
2. Keep SearXNG results as URL candidates only.
3. Use Crawl4AI markdown as untrusted page text, not as system instructions and not as price truth.
4. Extract possible price/route/date hints deterministically and create `DealCandidate` with
   `requires_manual_verification=True`.
5. Expose manual discovery through `POST /api/v1/deals/discover`, disabled by default unless
   SearXNG and Crawl4AI are enabled or a test service is injected.
6. Persist candidates in `deal_candidates` only when a valid household/user context and `search_id`
   are present. Stored candidates are scoped by household, user and search fingerprint and expire by
   `DEAL_CANDIDATE_TTL_SECONDS`.
7. Return scoped unexpired candidates in `POST /api/v1/searches` under `deal_candidates`.
8. Do not merge deal candidates into priced offer ranking.
9. Do not make live SearXNG/Crawl4AI calls in CI; tests use mock HTTP and sanitized markdown
   fixtures.

## Consequences

- Future UI can show “возможно есть акция” without implying availability.
- Search ranking remains based on provider offers and browser/user observations, not feed snippets.
- Crawl4AI can be introduced for deal pages without becoming the primary parser for aggregator
  result pages.
- Candidate storage has privacy boundaries and freshness boundaries; old or cross-user candidates
  do not reappear in search responses.

## Verification

- `tests/unit/deals/test_query_builder.py`
- `tests/unit/deals/test_searxng_client.py`
- `tests/unit/deals/test_extractor.py`
- `tests/unit/deals/test_service.py`
- `tests/unit/api/test_api_app.py`
- `tests/unit/persistence/test_deal_candidate_repository.py`
- `tests/unit/persistence/test_alembic_upgrade.py`
- `migrations/versions/0009_deal_candidates.py`
- `tests/fixtures/crawl4ai/deal_page_markdown.md`
