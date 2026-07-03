# ADR 0042: Tutu Source-Specific Observer Parser

Date: 2026-06-29

## Status

Accepted for the first source-specific Personal Browser Observer extractor.

## Context

The Personal Browser Observer already has a user-action-gated Playwright runtime, durable DB jobs
and a generic fixture parser. The monster plan requires at least one source-specific extractor
before treating the browser observer as production-useful.

Tutu public pages do not provide a stable public flight pricing API for this project, and Tutu
search/offers pages must not become a background crawler target. Flight Hunter therefore keeps this
path as personal, explicit user-action observation only. CI uses sanitized fixtures and never opens
live Tutu pages.

References checked on 2026-06-29:

- https://www.tutu.ru/robots.txt
- https://www.tutu.ru/

## Decision

1. Add `TutuRuHtmlOfferExtractor` selected by `RuAggregatorSpec.parser_id == "tutu"`.
2. Keep the old generic parser for generic/synthetic fixture contracts, but stop using it for Tutu
   runner jobs by default.
3. Parse sanitized Tutu-like ticket cards with source-specific selectors and route/date/price
   extraction.
4. Surface explicit diagnostics:
   - `selector_drift` when expected ticket-card selectors are absent;
   - `source_challenge` when the captured page looks like an access/captcha challenge;
   - `route_mismatch`, `date_mismatch`, `parser_no_offers` for rejected cards.
5. Keep raw HTML persistence off by default and persist only normalized observations.

## Consequences

- Tutu fixture runs exercise a source-specific parser rather than synthetic `data-flight-offer`
  markup.
- Worker/CLI examples must use the source-specific sanitized fixture.
- Live browser observation remains user-action-only and never runs from watches/scheduler.
- Yandex Travel, OneTwoTrip and carrier-specific parser contracts remain future slices.

## Verification

- `tests/unit/browser/test_html_offer_extractor.py`
- `tests/unit/providers/personal_observer/test_runner.py`
- `tests/unit/providers/personal_observer/test_cli.py`
- `tests/unit/providers/personal_observer/test_worker_cli.py`
- `tests/unit/ops/test_worker_command.py`
