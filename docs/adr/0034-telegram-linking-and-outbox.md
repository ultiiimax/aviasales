# ADR 0034: Telegram Linking And Notification Outbox

Date: 2026-06-29

## Status

Accepted for the first Telegram delivery slice.

## Context

Telegram webhook security and `update_id` dedupe existed, and watch scans can now record durable
price-drop alert dedupe. There was still no safe outbound delivery queue, no one-time linking flow,
and no place to preserve notifications when a user has not linked Telegram yet.

## Decision

1. Add one-time `telegram_link_codes` and durable `telegram_accounts`.
2. Use `telegram_user_id` and `chat_id` from the signed webhook update payload. Do not use Telegram
   username as an account key.
3. Add `telegram_notification_outbox` with dedupe key, status, attempts, retry scheduling and safe
   JSON payload. It stores no provider raw payload, bot token, signed URL or callback secret.
4. Add `TelegramLinkService` for creating/consuming link codes and `TelegramNotificationService`
   for price-alert enqueue and delivery.
5. Add `TelegramBotApiTransport` behind `TELEGRAM_ENABLED=true` and `TELEGRAM_BOT_TOKEN`; tests use
   fake transports and never call Telegram live.
6. Wire watch-scan price alerts to enqueue Telegram notifications only after alert dedupe is
   recorded. If the owner has no linked Telegram account, the outbox row is `blocked` with
   `telegram_link_missing`.
7. Keep delivery quiet-hours aware. During quiet hours, queued notifications are deferred to the
   next allowed time without incrementing attempts.
8. Claim due outbox rows with a conditional DB lease before sending. Claimed rows move to
   `sending`; success, failure and quiet-hours retry clear the lease.

## Consequences

- Users can request a link code from the API and consume it with `/link CODE` through the existing
  secret-protected Telegram webhook.
- Alert delivery becomes retryable and inspectable rather than a side effect inside watch scanning.
- A configured Bot API token is required for actual send attempts; no-token environments keep
  notifications queued/blocked rather than pretending delivery happened.
- Parallel workers should not send the same due notification intentionally because delivery uses
  repository-level conditional claims; see ADR 0035.
- Full Telegram command UX and long-detail deep links remain future slices.

## Verification

- `tests/unit/application/test_telegram_notifications.py`
- `tests/unit/api/test_telegram_api.py`
- `tests/unit/application/test_watch_scans.py`
- `tests/unit/ops/test_worker_command.py`
- `uv run pytest tests\unit --quiet`
- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run mypy`
- `uv run alembic upgrade head`
