# ADR 0107: Telegram Callback Answer Transport

Date: 2026-06-29

## Status

Accepted.

## Context

Telegram watch callbacks already mutate watches or queue manual browser observation jobs through a
secret-protected webhook, durable `update_id` dedupe and household-scoped ownership checks. The
remaining gap was transport-level acknowledgement: callback results were stored as chat
`command_reply` outbox rows, so Telegram clients did not receive Bot API `answerCallbackQuery`
responses.

## Decision

- Extract Telegram `callback_query.id` in the webhook and pass it to `TelegramWatchCommandService`.
- Store watch callback acknowledgements as durable `callback_ack` rows in
  `telegram_notification_outbox`, still using `telegram:callback:{update_id}` for dedupe.
- Deliver `callback_ack` rows with `TelegramTransport.answer_callback_query(...)` and the Bot API
  `answerCallbackQuery` endpoint.
- Do not place callback data, grant tokens, provider secrets, signed URLs or booking URLs in the
  outbox acknowledgement payload.
- Do not apply quiet-hours deferral to `callback_ack`: it is an acknowledgement of an explicit user
  tap, not a proactive notification.
- Keep the webhook side-effect-light. It records the update, performs local policy/ownership work
  and enqueues outbox rows; actual Telegram API calls remain in worker delivery.

## Consequences

- Callback dedupe and retries remain DB-backed, and duplicate Telegram webhook delivery cannot send
  repeated callback answers.
- `callback_ack` delivery no longer requires `chat_id`; it requires only the Telegram
  `callback_query_id` and configured bot token.
- If the worker is down, callback acknowledgement rows remain retryable, but Telegram may stop
  accepting very old callback ids. Worker health alerts and supervision cover that operational risk.
