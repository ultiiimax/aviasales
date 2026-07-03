# ADR 0089: Browser Crawl4AI markdown hint hook

Date: 2026-06-29

## Status

Accepted.

## Context

The browser observer parser pipeline already runs source-specific DOM extraction, optional
Scrapling extraction, generic DOM extraction and visible-text price hints. The MEGA_MONSTER_PLAN
also calls for Playwright + Scrapling + Crawl4AI integration, but Crawl4AI must not become the
primary parser for RU aggregator result pages and must not turn unstructured text into confirmed
prices.

Deal discovery has a real Crawl4AI client. Browser observation still needs a safe seam where a
sanitized markdown snapshot can participate in diagnostics without changing price-truth rules.

## Decision

`BrowserOfferParserPipeline` now accepts an optional `crawl4ai_markdown_provider`. When
`crawl4ai_diagnostics_enabled=true`, the final diagnostic stage passes the current `DomSnapshot` to
that provider and scans returned markdown for RUB price hints. If no provider is configured, the
stage keeps the previous fallback behavior of using visible text from the DOM snapshot.

Markdown prices are always rejected `PriceCandidate` hints with
`crawl4ai_hint_requires_manual_verification`; they never become `BrowserObservedOffer` records.

## Consequences

- A future runner or diagnostic CLI can pass markdown captured through the existing Crawl4AI client
  without refactoring the parser pipeline.
- Default local behavior is unchanged and does not perform network work.
- Provider or page text remains untrusted; markdown hints cannot override DOM/parser policy.

## Verification

- Unit tests cover markdown-only price hints from the injected provider.
- Existing parser pipeline and Scrapling tests still pass.
