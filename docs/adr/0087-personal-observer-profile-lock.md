# ADR 0087: Personal observer profile lock

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer uses Playwright persistent contexts so a self-hosted operator can keep
source-specific cookies and local storage in `.local/browser-profiles/{source_id}`. After adding
role-scoped workers, operators can accidentally run more than one browser worker. Two Chromium
persistent contexts pointed at the same profile can corrupt or wedge that profile and can turn a
legitimate user-action observation into an opaque browser runtime failure.

The database job lease prevents two workers from claiming the same job, but it does not protect a
source profile if multiple different jobs for the same source are started by separate processes or
manual CLIs.

## Decision

Before launching Playwright, acquire an exclusive `.flight_hunter_profile.lock` file inside the
source profile directory. The lock:

- is source-scoped and separate from diagnostic artifacts;
- defaults to fail-fast with `PERSONAL_OBSERVER_PROFILE_LOCK_TIMEOUT_SECONDS=0`;
- can remove stale lock files older than `PERSONAL_OBSERVER_PROFILE_LOCK_STALE_SECONDS`;
- is released after Playwright context shutdown, including failure paths;
- never stores cookies, URLs, tokens or page content.

If the lock is held, the runner raises a typed `PROFILE_LOCKED` error. The application adapter maps
that to `SOURCE_UNAVAILABLE`, so durable jobs can retry instead of marking a policy or parser
failure.

## Consequences

- Separate `flight-hunter-worker --role browser` processes cannot open the same source profile at
  the same time.
- Local fixture parsing is unaffected because it does not launch Playwright or touch browser
  profiles.
- Operators can tune timeout/stale behavior in `.env` without enabling hidden background browser
  work.
- The lock is a local filesystem guard, not a distributed lock across multiple hosts sharing no
  filesystem.

## Verification

- Unit tests cover active lock rejection before Chromium launch.
- Unit tests cover stale lock replacement and lock release after successful capture.
- Config and `.env.example` tests cover the new env variables.
