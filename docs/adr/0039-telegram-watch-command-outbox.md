# ADR 0039: Telegram Watch Command Outbox

Date: 2026-06-29

## Status

Accepted.

## Context

Flight Hunter already had Telegram webhook security, durable `update_id` dedupe, one-time linking
and notification outbox delivery. The product plan requires Telegram watch management, starting
with `/watches`, without trusting Telegram usernames or exposing one household's data to another.

## Decision

- Add a pure application service, `TelegramWatchCommandService`, for `/watches`.
- Resolve ownership through the linked `telegram_user_id` stored in `telegram_accounts`; do not use
  Telegram username as an account key.
- Enqueue the command reply as a `command_reply` row in `telegram_notification_outbox` instead of
  calling Telegram Bot API inside the webhook.
- Use `telegram:command:watches:{update_id}` as the outbox dedupe key.
- Keep unlinked users silent in this slice: no household data and no outbox row.
- Render only deterministic watch facts: route, dates, passengers, status and watch version. The
  command does not perform provider calls, live refreshes or booking-link creation.

## Consequences

- Webhook handling stays quick and idempotent; existing worker delivery/retry/quiet-hours logic
  sends command replies.
- `/watches` is safe to extend with pause/resume callbacks later because ownership lookup is now
  explicit and tested.
- Inline keyboards, callback ownership checks and `/pause`/`/resume` remain follow-up slices.
