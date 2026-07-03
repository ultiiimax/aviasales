# ADR 0040: Telegram Watch Callback Actions

Date: 2026-06-29

## Status

Accepted.

## Context

`/watches` can now render a linked user's household-scoped watch list through the durable Telegram
outbox. The next Telegram management requirement is safe pause/resume actions from inline button
callbacks without trusting callback data as authorization.

## Decision

- Use compact callback data:
  - `fh:w:p:<watch_uuid>:<version>` for pause 24 hours.
  - `fh:w:r:<watch_uuid>:<version>` for resume.
- Treat callback data as untrusted input. The application resolves the linked account by
  `telegram_user_id`, then checks the watch through household-scoped repository methods.
- Use watch `version` as an optimistic lock. Stale callbacks enqueue a generic retry message and do
  not mutate the watch.
- Store callback acknowledgements in `telegram_notification_outbox`, using
  `telegram:callback:{update_id}` as the dedupe key. ADR 0107 supersedes the original
  `command_reply` delivery method with Bot API `answerCallbackQuery` delivery.
- Render Pause/Resume inline button payloads in `/watches` replies, but do not put provider secrets,
  signed booking URLs or personal data into callback data.
- Keep provider/live refresh work out of callbacks. Pause/resume only mutates local watch state.

## Consequences

- Telegram retry or duplicate callback delivery cannot apply the same state change twice.
- Foreign-household callbacks return a generic "not found or access denied" message.
- Future slices can add `/pause` and `/resume` text commands and richer web deep links without
  changing the ownership model.
