# ADR 0015: RUB Click-Out Price Observer

Date: 2026-06-23

## Status

Accepted for the current backend slice.

## Context

The product does not need in-app booking, order creation, payment processing or ticket issuing. The desired flow is:

1. Find the cheapest visible prices across relevant sources.
2. Show source, freshness and caveats.
3. Send the user to an external aggregator or official carrier website to buy in RUB.

Official references checked on 2026-06-23:

- Travelpayouts Aviasales Data API: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
- Aviasales Search API access requirements: https://support.travelpayouts.com/hc/en-us/articles/210995808-How-to-get-access-to-the-Aviasales-Search-API
- Yandex Travel affiliate registration: https://yandex.com/support/travel-distr/en/partner/registration
- Yandex Travel partner links: https://yandex.com/support/travel-distr/en/instruments/partner-links

## Decision

1. Flight Hunter is a price observer and click-out product, not a booking product.
2. Every source is represented as a `PriceSource` with:
   - source type;
   - price kind;
   - RUB support;
   - external purchase flow;
   - manual confirmation requirement.
3. API and cached sources are separated from external partner links and carrier websites.
4. Scraping is not a default adapter. A future scraping observer can exist only behind a feature flag and per-source permission check.
5. The scraping observer policy blocks:
   - CAPTCHA solving;
   - stealth/fingerprint spoofing;
   - rotating/residential proxies;
   - reused cookies;
   - login-required/private pages;
   - background collection.
6. Any scraped/displayed fare is labelled `observed_price`, not guaranteed availability.

## Consequences

- The app can guide users toward cheaper RUB purchase options without storing payment data.
- RU aggregators and official carrier sites can appear as click-out sources even when no public API exists.
- Real live automation remains source-by-source work, not a generic hidden scraper.
- The user can explicitly opt into risky scraping later, but the codebase keeps hard guardrails.

## Implementation note: 2026-06-29

The search API now returns a bundle-shaped result with priced offers, external check links,
browser-observed offers, deal candidates and a freshness summary. The current RU click-out
implementation builds conservative HTTPS base links only; it does not fabricate precise deeplinks,
prices, availability, booking URLs or live observations. `RU_AGGREGATORS_ENABLED` and
`CARRIER_LINKS_ENABLED` control which external check links are shown, and browser observation remains
behind explicit user-action policy/config gates.

The fixture parser slice also adds `GenericRuHtmlOfferExtractor`, which reads sanitized HTML with
explicit offer-card markers into `BrowserObservedOffer` values. It is intentionally offline and does
not navigate pages, bypass protections, solve CAPTCHA, reuse cookies or infer prices outside an
offer card.

The personal observer runtime slice adds optional Playwright/Scrapling/Crawl4AI dependency groups,
the `flight-hunter-observe` CLI, a user-action gated Playwright persistent-profile runner and
short-lived persistence for normalized `browser_observed` offers. Live observation still requires
explicit config, an allowed source/host, a user action grant and no background scheduler calls.
Crawl4AI is available as an optional dependency/config surface for later deal-page extraction, but
it is not yet a source of fare prices or deal candidates.

The durable job slice adds `/api/v1/personal-observations/*` and
`flight-hunter-run-personal-observation`. API requests enqueue user-action jobs and return status;
the worker CLI performs the browser/fixture observation separately and persists normalized offers.
The scheduler still cannot create or run browser observations without an explicit user grant.

## Verification

- `tests/unit/application/test_price_sources.py`
- `tests/unit/api/test_price_sources_api.py`
- `tests/unit/application/test_scraping_policy.py`
- `tests/unit/domain/test_search_results.py`
- `tests/unit/providers/ru_clickout/test_link_builder.py`
- `tests/unit/application/test_search_service.py`
- `tests/unit/api/test_api_app.py`
- `tests/unit/browser/test_html_offer_extractor.py`
- `tests/unit/browser/test_scrapling_offer_extractor.py`
- `tests/unit/providers/personal_observer/test_runner.py`
- `tests/unit/providers/personal_observer/test_cli.py`
- `tests/unit/persistence/test_browser_observed_offer_repository.py`
