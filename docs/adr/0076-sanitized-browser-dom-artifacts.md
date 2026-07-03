# ADR 0076: Sanitized Browser DOM Artifacts

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer sometimes needs local diagnostic DOM fixtures for parser debugging.
The monster plan explicitly forbids storing raw browser HTML by default and requires a
`flight-hunter-sanitize-html` command for fixture preparation. Raw DOM can contain scripts,
session-bearing URLs, hidden inputs, inline handlers, emails or other private data.

## Decision

- Add `sanitize_dom_html_for_fixture()` in the browser parser layer.
- Remove active code blocks, comments, inline event handlers, styles, secret-like attributes,
  form values, query strings/fragments and obvious email/secret literals from sanitized fixtures.
- Make `PERSONAL_OBSERVER_SAVE_DOM_FIXTURES=true` write sanitized HTML only.
- Add `flight-hunter-sanitize-html --input ... --output ...` and `make sanitize-html`.
- The sanitizer command prints only byte counts and SHA-256 hashes, never DOM content.

## Consequences

- Parser developers have a safer local path for turning raw browser captures into minimal
  diagnostic fixtures.
- Runtime parsing can still use the in-memory DOM from the current user-action page, but debug
  artifacts no longer persist the raw HTML payload.
- The sanitizer is a best-effort privacy guard, not permission to commit full copyrighted pages or
  personal browser state.
