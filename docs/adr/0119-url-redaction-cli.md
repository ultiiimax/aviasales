# ADR 0119: URL redaction CLI

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The monster plan requires `flight-hunter-redact-url` next to the DOM sanitizer. Operators sometimes
need to paste final URLs, signed links or reproduction links into logs, bug reports or sanitized
fixtures. Those URLs can contain credentials, session ids, access tokens, signatures or fragments.

## Decision

Add `flight-hunter-redact-url`:

- Removes URL username/password credentials from the netloc.
- Replaces sensitive query values with `<redacted>`.
- Redacts query keys case-insensitively after normalizing `-` to `_`.
- Removes fragments entirely, because fragments can contain OAuth or signed-link material.
- Prints only a JSON summary with the redacted URL and redaction metadata.
- Exposes `make redact-url REDACT_URL=...`.

This tool is local safety tooling. It does not permit storing signed booking URLs, provider secrets
or raw provider payloads.

## Consequences

Positive:

- Operators can safely produce redacted reproduction URLs.
- The CLI can be used before adding URLs to sanitized fixtures or issue notes.
- Tests lock down that secret query values do not appear in stdout.

Tradeoffs:

- The sensitive-key list is conservative and may redact benign parameters named `code` or `key`.
- The tool does not fetch, validate or canonicalize provider pages.

## Verification

- `uv run pytest tests/unit/ops/test_redact_url.py tests/unit/ops/test_makefile_commands.py -q`
  -> 3 passed.
