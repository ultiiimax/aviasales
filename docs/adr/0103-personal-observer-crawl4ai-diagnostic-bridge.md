# ADR 0103: Personal Observer Crawl4AI diagnostic bridge

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer already captures a visible Playwright page after explicit user action
and parses the DOM through source-specific, Scrapling and generic extractors. Crawl4AI support was
limited to explicit local markdown fixtures/providers, so production browser runs could not attach
markdown diagnostics from the already visited final URL when DOM selectors failed.

Crawl4AI remains optional, disabled by default and verified against the 2026-06-29 contract notes in
`docs/provider-contracts/crawl4ai.md`.

## Decision

Add a `Crawl4AiBrowserMarkdownProvider` for Personal Browser Observer runs. When
`CRAWL4AI_ENABLED=true`, API/worker/CLI runner construction injects the provider into the existing
parser pipeline. The provider:

- reads only the `DomSnapshot.final_url` captured by the visible browser session;
- uses the shared Crawl4AI URL policy before any fetch;
- supports the existing `library` and self-hosted `server` modes through `Crawl4AiMarkdownClient`;
- skips local fixture snapshots so fixture parsing stays network-free;
- returns markdown only as rejected diagnostic price candidates.

The DOM parser remains authoritative for `BrowserObservedOffer` creation. Crawl4AI markdown never
creates a confirmed price, booking link or ranked offer.

## Consequences

- Production browser observations can record better selector-drift diagnostics without adding hidden
  background crawling.
- Crawl4AI runtime/auth/rate-limit failures become sanitized parser warnings, not raw payloads and
  not fatal runner errors.
- Deal discovery and browser observation share the same Crawl4AI client and SSRF guard.

## Verification

- Client tests cover synchronous server-mode `/md` fetch.
- Browser diagnostic provider tests cover final-URL fetch and fixture no-fetch behavior.
- Parser pipeline tests cover sanitized Crawl4AI provider failures.
- Source-contract tests expose the browser diagnostic operation and invariant.
