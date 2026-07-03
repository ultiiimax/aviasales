# ADR 0058: Personal Observer Runtime Artifacts

Date: 2026-06-29

## Status

Accepted.

## Context

The personal browser observer uses a persistent Playwright profile per source. Screenshots and DOM
fixtures are useful diagnostics, but storing them inside the browser profile mixes runtime state
with artifacts and makes cleanup harder. The observer also needs robust host validation after
redirects and reliable browser-context cleanup on navigation failures.

## Decision

- Keep persistent browser profiles under `PERSONAL_OBSERVER_PROFILE_ROOT`.
- Add a separate `PERSONAL_OBSERVER_ARTIFACT_ROOT` for optional screenshots and DOM fixtures.
- Normalize allowlist validation through `urlparse(...).hostname`, so `host:443` does not bypass or
  falsely fail the configured host list.
- Close the persistent Playwright context in a `finally` block after launch, including navigation
  failure paths.
- Sanitize per-source runtime directory names before joining them to profile/artifact roots.

## Consequences

- Browser profile state and diagnostic artifacts can be backed up or cleaned independently.
- Allowed host checks remain exact-host checks, including after redirects.
- Navigation failures are less likely to leave open browser contexts.
- This does not add stealth, proxies, CAPTCHA bypass, login-cookie import or background browsing.
