# Tutu Personal Browser Observer Contract Notes

Verified: 2026-06-29

Official/public references:

- https://www.tutu.ru/
- https://www.tutu.ru/robots.txt

Implementation status: source-specific parser and sanitized fixture tests only. Live browser
observation remains disabled by default and requires an explicit user action. The scheduler and
watch worker must never create Tutu browser observations in the background.

Policy facts used by Flight Hunter:

- Tutu is not used as a live pricing API.
- Search/offers-style pages must not be crawled in CI or by background jobs.
- The parser may read a user-opened/local browser snapshot or sanitized fixture and normalize
  visible facts only.
- Raw HTML, cookies, screenshots and personal browser profile data are not persisted by default.
- If diagnostic artifacts are enabled, sanitized DOM fixtures and optional debug screenshots are
  written under `PERSONAL_OBSERVER_ARTIFACT_ROOT`, separate from the persistent browser profile
  root. The DOM fixture path removes active code, secret-like attributes, query strings and obvious
  PII before writing HTML to disk.
- Diagnostic runtime manifests are also written under `PERSONAL_OBSERVER_ARTIFACT_ROOT` when
  explicitly enabled, or when DOM/screenshot artifacts are enabled. A manifest contains source id,
  capture time, redacted final URL without query/fragment, snapshot hashes and artifact paths. It
  does not contain raw DOM, cookies, local storage, query strings or title text.
- Parsed observations are labelled `browser_observed`, require external confirmation and are never
  treated as guaranteed purchase availability.
- Source challenges and selector drift are first-class parser diagnostics, not generic crashes.
- The runner uses a parser pipeline. Tutu source-specific extraction is attempted first; if it
  drifts without a challenge page, optional Scrapling and then the generic offer-card parser may
  recover structured offers. Unstructured visible-text/Crawl4AI hints remain rejected diagnostics
  and are not persisted as offers.
- Worker claims enforce configured browser-observer concurrency and same-source minimum gap before
  any browser/runtime side effect.

Current Flight Hunter behavior:

- Source id: `tutu`.
- Parser id: `tutu`.
- Allowed fixture path for local tests/examples:
  `tests/fixtures/browser/tutu/search_result_source_specific.html`.
- Expected diagnostics: `selector_drift`, `source_challenge`, `route_mismatch`, `date_mismatch`,
  `parser_no_offers`, `card_missing_price`, plus stage-prefixed pipeline diagnostics such as
  `tutu:selector_drift` and `parser_stage:generic_html`.
- Background watch scans may include a Telegram/web button suggesting manual browser verification,
  but may not launch this observer automatically.
- Telegram `/watches` Check buttons create a one-time `telegram_callback` grant and a queued
  `browser_observation_jobs` row only after the linked user presses the inline callback button.
  The webhook does not run Playwright/browser automation directly.
- Durable worker processing respects `PERSONAL_OBSERVER_MAX_CONCURRENT` and
  `PERSONAL_OBSERVER_MIN_GAP_SECONDS` at the DB claim boundary.
- Durable worker processing records operator-visible runtime phases (`opening_browser`,
  `waiting_for_user`, `capturing_dom`, `parsing`) on the job row; these phases remain
  user-action-only browser work and count as active leases for stale recovery.
- During `waiting_for_user`, the authenticated household/user can explicitly request resume or
  abort through durable API controls. Resume allows DOM capture; abort ends the job as
  `needs_human` with `operator_aborted` so the user can verify manually.
- Playwright persistent contexts are closed on navigation failures; redirect host checks use exact
  hostname allowlist validation.
- `POST /api/v1/browser-sources/tutu/test-parser` is an authenticated sanitized-fixture parser
  check. It does not navigate, does not persist raw HTML, does not echo DOM back to the client and
  validates `final_url` against the observer host allowlist before building a snapshot.
- `flight-hunter-sanitize-html` is the local command for converting raw DOM captures into sanitized
  fixtures before parser debugging or fixture commits.
