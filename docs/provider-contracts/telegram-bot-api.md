# Telegram Bot API Contract Notes

Last verified: 2026-06-29

Official references:

- https://core.telegram.org/bots/api
- https://core.telegram.org/bots/api#answercallbackquery

## Scope

Telegram is a delivery and command surface for Flight Hunter. It is not a source of prices,
availability, fare rules, airport data or provider policy.

## Contract Rules

- Production webhook mode requires `X-Telegram-Bot-Api-Secret-Token` verification.
- `update_id` is persisted and deduplicated before command or callback side effects are applied.
- Account linking uses a one-time code and durable Telegram user id/chat id; Telegram username is
  never an account key.
- Callback data is untrusted input. The application resolves the linked Telegram account and checks
  household-scoped watch ownership/version before mutating state or queuing jobs.
- `answerCallbackQuery` requires `callback_query_id`. Flight Hunter sends only
  `callback_query_id`, bounded `text` and `show_alert`; it does not use callback `url` or
  `cache_time`.
- `callback_ack` outbox payloads must not include raw callback data, provider secrets, grant tokens,
  signed URLs, cookies, booking URLs or PII beyond the Telegram callback id needed by the Bot API.
- Callback acknowledgements are explicit user-action responses and are not deferred by quiet hours.
- Tests use fake transports or `httpx2.MockTransport`; CI must not call the live Telegram Bot API.

## Local Smoke

No live smoke runs without `TELEGRAM_ENABLED=true` and `TELEGRAM_BOT_TOKEN`. Unit tests cover webhook
dedupe, ownership checks, outbox delivery, and the Bot API endpoint path without network access.
