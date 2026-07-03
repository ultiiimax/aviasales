# ADR 0052: Telegram Watch Manual Observation Callback

Date: 2026-06-29

## Status

Accepted.

## Context

`/watches` already supports household-scoped Pause/Resume inline callbacks. The personal browser
observer control plane also already requires one-time user-action grants and queues durable
browser observation jobs. Telegram watch users need a "check now" action, but webhook handling must
not run browser automation directly or create background discovery.

## Decision

- Add compact callback data `fh:w:c:<watch_uuid>:<version>:<source_id>` for manual browser checks.
- Default `source_id` to `tutu`, configurable through `TELEGRAM_WATCH_CHECK_SOURCE_ID`.
- Treat the callback as untrusted. Resolve the linked Telegram account first, read the watch through
  the household-scoped repository, and compare the optimistic `version`.
- On a valid callback, issue a `PersonalObservationService` grant with source
  `telegram_callback`, then immediately create a durable browser observation job with an
  idempotency key derived from Telegram `update_id`, watch id, watch version and source id.
- The webhook enqueues only a Telegram outbox acknowledgement. It never invokes the browser runner.
- Do not place grant tokens, provider secrets, cookies, signed URLs or booking URLs in callback data
  or Telegram replies.

## Consequences

- A Telegram manual check is a real user action and still goes through the same policy gate as the
  web personal observer flow.
- Duplicate Telegram updates are stopped by durable `update_id` dedupe and by the observation job
  idempotency key.
- Stale or foreign-household callbacks do not create grants or jobs.
- The actual browser observation remains the worker's responsibility and continues to respect
  configured concurrency/min-gap claim guards.
