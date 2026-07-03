# ADR 0082: Browser Runtime Diagnostic Manifest

Date: 2026-06-29

## Status

Accepted.

## Context

Personal Browser Observer can run a user-action Playwright browser, save sanitized DOM fixtures and
optional screenshots. Those artifacts are useful, but operators also need a small machine-readable
capture summary for production debugging without storing raw DOM, cookies, query strings or page
titles in logs or database rows.

## Decision

- Add `PERSONAL_OBSERVER_SAVE_RUNTIME_MANIFESTS=false` and a matching runner config flag.
- Write a JSON manifest under `PERSONAL_OBSERVER_ARTIFACT_ROOT/{source_id}` when runtime manifests,
  sanitized DOM fixtures or screenshots are enabled.
- Include only safe capture facts: manifest version, source id, capture timestamp, redacted final
  URL without query/fragment, whether a query/fragment was redacted, DOM/text hashes and artifact
  paths.
- Store title as a SHA-256 hash only. Do not store raw DOM, page text, cookies, local storage,
  query strings or title text in the manifest.
- Keep fixture-mode tests browser-free; live browser manifest behavior is covered with fake
  Playwright runtime objects.

## Consequences

- Operators can correlate a browser observation with sanitized artifacts and hashes without reading
  raw page payloads.
- Diagnostic manifests remain opt-in local files, not durable application facts or client-bundled
  content.
- Future worker/admin surfaces may list manifest paths or hashes, but must continue to avoid
  serving raw artifacts by default.
