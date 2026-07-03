# ADR 0066: Personal observer runtime controls

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The Personal Browser Observer already runs Playwright with a dedicated persistent profile per
source, an allowlisted redirect host check and optional diagnostic artifacts. The runtime used a
hard-coded navigation timeout and a fixed post-load delay, which made local self-host operation hard
to tune for slow sources or for pages where a household user must manually reach visible results.

## Decision

Add explicit runtime controls to `PersonalObserverConfig` and `.env.example`:

- `PERSONAL_OBSERVER_NAVIGATION_TIMEOUT_MS`
- `PERSONAL_OBSERVER_READY_SELECTOR`
- `PERSONAL_OBSERVER_READY_TIMEOUT_MS`
- `PERSONAL_OBSERVER_WAIT_FOR_NETWORK_IDLE`
- `PERSONAL_OBSERVER_MANUAL_CHECKPOINT_SECONDS`

The Playwright runner now:

- uses the configured navigation timeout for `page.goto`;
- waits for a manual checkpoint only in visible mode;
- optionally waits for `networkidle`;
- optionally waits for a configured ready selector;
- still captures only after validating the final host against the source allowlist.

These controls do not add stealth, proxy, CAPTCHA bypass, cookies export or background discovery.
The observer remains disabled by default and still requires a user-action path.

## Consequences

Positive:

- Local operators can tune slow source pages without code changes.
- Unit tests can verify runtime sequencing without launching Chromium.
- Manual checkpoint time is explicit and skipped in headless mode.

Tradeoffs:

- Source-specific ready selectors are still operator supplied; this slice does not add per-source
  selector contracts for Yandex Travel or OneTwoTrip.
- This does not replace the need for a no-credentials integration/E2E acceptance harness.

## Verification

- `uv run pytest tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py --quiet`
  -> 14 passed.
- `uv run ruff format --check src/flight_hunter/config.py src/flight_hunter/providers/personal_observer/runner.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
  -> 5 files already formatted.
- `uv run ruff check src/flight_hunter/config.py src/flight_hunter/providers/personal_observer/runner.py tests/unit/providers/personal_observer/test_runner.py tests/unit/test_config.py tests/unit/test_env_example.py`
  -> All checks passed.
