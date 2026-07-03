# ADR 0026: Python 3.13 and Personal Observer Runtime Dependencies

Date: 2026-06-29

## Status

Accepted for the personal browser observer slice.

## Context

The monster plan requires Playwright, Scrapling and Crawl4AI integration without turning Flight
Hunter into a hidden mass scraper. The local development environment also needs a reproducible
Python/runtime selection.

`crawl4ai>=0.7,<1.0` currently depends on `lxml>=5.3,<6`. On Python 3.14, `lxml==5.4.0` attempted a
source build in this Windows environment and failed without local libxml2/libxslt headers. Python
3.13 had prebuilt wheels and installed cleanly through `uv`.

## Decision

1. Pin the project runtime to `>=3.13,<3.14` and add `.python-version` with `3.13`.
2. Keep browser/crawler packages out of the default runtime and expose them as optional dependency
   groups:
   - `scraping`: Playwright, Scrapling and BeautifulSoup;
   - `crawler`: Crawl4AI.
3. Install Chromium with `uv run playwright install chromium` for local personal observer runs.
4. Keep Crawl4AI disabled by default. It is available for future deal-page extraction, not as a
   price source and not as a replacement for structured provider adapters.
5. Keep the personal observer gated by source policy, allowed hosts, explicit config and user
   action. Background scheduler calls remain forbidden.

## Consequences

- Clean checkouts can reproduce the browser/crawler environment with `uv sync --group dev --group scraping --group crawler`.
- Default demo/API setup remains lighter and does not install browser tooling unless requested.
- The project avoids Python 3.14 wheel/source-build instability for the current crawler stack.
- Future upgrades to Python 3.14 require rechecking crawler dependencies and recording the result.

## Verification

- `uv sync --group dev --group scraping --group crawler`
- `uv run playwright install chromium`
- `uv run flight-hunter-observe --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20 --fixture-html tests/fixtures/browser/tutu/search_result_source_specific.html`
- `tests/unit/browser/test_scrapling_offer_extractor.py`
- `tests/unit/providers/personal_observer/test_runner.py`
- `tests/unit/providers/personal_observer/test_cli.py`
