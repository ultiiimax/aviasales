# ADR 0077: Personal Observer Runtime Statuses

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer worker already has durable queued/running/succeeded/error states, but
the monster plan requires operator-visible browser phases such as opening the browser, waiting for
the user, capturing the DOM and parsing. Without these phases, the web UI can only show a generic
`running` state while a visible local browser session is active.

## Decision

- Extend `ObservationStatus` with non-terminal runtime phases:
  `opening_browser`, `waiting_for_user`, `capturing_dom`, `parsing` and `needs_human`.
- Reuse the existing `browser_observation_jobs.status`, `waiting_since` and lease columns, so no
  migration is required.
- Make runtime phases count as active browser work for max-concurrent claims and stale lease
  recovery.
- Let `PersonalObserverRunner` emit progress callbacks and run through `asyncio.to_thread` from the
  application service, so synchronous Playwright work does not block the event loop.
- Allow worker-owned service instances to commit runtime phase updates immediately.
- Expose attempts, `waiting_since`, `next_retry_at` and operator instructions in
  `GET /api/v1/personal-observations/{job_id}`.

## Consequences

- Operators can see where a user-action observation is stuck without exposing raw DOM, cookies or
  browser profile state.
- Long-running browser jobs remain recoverable if the worker dies while in a phase state.
- This does not add background browser discovery, challenge bypass, stealth mode or automated
  collection.
