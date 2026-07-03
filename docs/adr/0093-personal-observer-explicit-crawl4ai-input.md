# ADR 0093: Personal observer explicit Crawl4AI diagnostic input

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer parser pipeline can run source-specific DOM extraction, generic DOM
extraction, visible-text price hints and optional Crawl4AI-style markdown diagnostics. The previous
diagnostic hook fell back to `DomSnapshot.text` when no markdown provider was configured. That made
ordinary browser visible text look like Crawl4AI markdown when `CRAWL4AI_ENABLED=true`.

That fallback was misleading: Crawl4AI markdown is a separate untrusted diagnostic artifact, not a
renamed DOM snapshot and not a confirmed price source.

## Decision

`Crawl4AiMarkdownHintExtractor` no longer falls back to visible DOM text. If diagnostics are enabled
without an explicit markdown provider, it emits `crawl4ai_hint_no_markdown` and produces no price
candidates.

`PersonalObserverRunner` accepts an optional `crawl4ai_markdown_provider` and per-run
`crawl4ai_markdown_fixture_path`. The provider is passed lazily into `BrowserOfferParserPipeline`.
Structured DOM offers short-circuit the pipeline before the markdown provider is called.

`flight-hunter-parse-fixture` and `flight-hunter-observe` accept
`--crawl4ai-markdown-fixture` for local diagnostics. The CLI output remains summary-only and does
not print raw HTML or markdown.

## Consequences

- `CRAWL4AI_ENABLED=true` does not create automatic Crawl4AI network fetches in browser observation.
- Visible DOM text remains a separate rejected `visible_text_price_hint` source.
- Markdown hints remain rejected manual-verification diagnostics and never create
  `BrowserObservedOffer` rows.
- A future production Crawl4AI fetch path must add its own explicit policy, URL validation and tests.

## Verification

- Parser tests cover no-provider behavior, injected markdown hints and structured-offer short-circuit.
- Runner tests cover explicit provider forwarding.
- Fixture CLI tests cover the markdown fixture flag and summary-only output.
