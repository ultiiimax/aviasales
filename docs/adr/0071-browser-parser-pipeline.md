# ADR 0071: Browser parser pipeline

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

Personal Browser Observer captures a Playwright DOM snapshot from a user-action browser run or a
sanitized fixture. The previous runner selected one parser directly, so a source-specific parser
drift could hide a still-parseable generic fixture shape, and challenge pages were flattened into a
generic no-offers failure.

## Decision

Add `BrowserOfferParserPipeline` as the parser boundary used by `PersonalObserverRunner`.

The pipeline runs:

1. source-specific parser, currently Tutu;
2. optional Scrapling-backed parser when `SCRAPLING_ENABLED=true`;
3. generic HTML offer-card parser;
4. visible-text price hints as rejected diagnostics only;
5. optional Crawl4AI markdown-style hints when `CRAWL4AI_ENABLED=true`, also rejected diagnostics
   only.

Unstructured hints never become `BrowserObservedOffer` rows. They are preserved as rejected
`PriceCandidate` diagnostics so operators can inspect parser drift without showing a false fare.

`source_challenge` and `selector_drift` now map to typed runner/application statuses instead of the
generic `parser_no_offers` bucket.

## Consequences

Positive:

- Source-specific parser drift can fall back to safer generic/Scrapling extraction when the DOM has
  known offer-card boundaries.
- Challenge pages are visible in worker status/source health as `source_challenge`.
- Crawl4AI remains constrained to untrusted hint text and deal discovery, not confirmed prices.

Tradeoff:

- Pipeline warnings are more verbose because they include parser-stage prefixes.
- Live source-specific observation still depends on explicit user action, host allowlists and local
  browser runtime availability.

## Verification

- `uv run pytest tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py --quiet`
  -> 24 passed.
- `uv run ruff format --check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py`
  -> 7 files already formatted.
- `uv run ruff check src/flight_hunter/browser/html_extractor.py src/flight_hunter/providers/personal_observer/runner.py src/flight_hunter/providers/personal_observer/adapter.py src/flight_hunter/application/personal_observations.py tests/unit/browser/test_html_offer_extractor.py tests/unit/providers/personal_observer/test_runner.py tests/unit/application/test_personal_observations.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 88 source files.
