# ADR 0070: Browser runtime smoke

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The Personal Browser Observer depends on Playwright Chromium being installed locally. Unit tests
cover the runner with fake Playwright objects, but operators still needed a simple command to verify
that the actual Chromium runtime can start on the host without visiting live travel websites.

## Decision

Add `flight-hunter-browser-smoke` and `make browser-smoke`.

The smoke command:

- launches Playwright Chromium in headless mode with a persistent context;
- loads only local inline HTML;
- checks for a visible `ready` marker;
- prints a sanitized JSON summary with no DOM, tokens, cookies or URLs;
- exits non-zero with a typed code when Playwright or Chromium is unavailable.

## Consequences

Positive:

- Operators can verify the browser runtime after `uv run playwright install chromium`.
- The check is safe for CI/local development because it does not contact travel sites.
- Unit tests use fake Playwright runtime objects, so normal test runs do not require browser
  binaries.

Tradeoff:

- This confirms local Chromium startup only; source-specific live observation remains controlled by
  user action, allowlists and separate parser fixtures.

## Verification

- `uv run pytest tests/unit/ops/test_browser_smoke.py tests/unit/ops/test_makefile_commands.py --quiet`
  -> 4 passed.
- `uv run ruff format --check src/flight_hunter/ops/browser_smoke.py tests/unit/ops/test_browser_smoke.py`
  -> 2 files already formatted.
- `uv run ruff check src/flight_hunter/ops/browser_smoke.py tests/unit/ops/test_browser_smoke.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 88 source files.
- `uv run playwright install chromium` -> completed successfully.
- `uv run flight-hunter-browser-smoke` -> `ok=true`, `code=ok`, `browser=chromium`.
