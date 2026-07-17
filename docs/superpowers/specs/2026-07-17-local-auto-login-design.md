# Local auto-login design

## Goal

Make the personal loopback build usable immediately: opening the web UI must
produce a normal owner bearer session without an invitation code, name form or
second action. Searches, durable agent runs, history and watches must work on
the first page load.

## Selected approach

Add a config-gated local-session endpoint and reuse the existing auth/session
model. `AUTH_LOCAL_AUTO_LOGIN` stays disabled by default in shared examples but
is enabled in this machine's ignored `.env`. The endpoint accepts only a
loopback client address. This keeps the normal invitation endpoints available
for non-local/multi-user setups without exposing them in the personal UI.

Alternatives rejected:

- Removing authorization from scoped APIs would break household ownership and
  create a second unauthenticated execution path.
- Pre-generating and displaying an invitation still leaves the user blocked by
  setup ceremony and one-time codes.

## Backend contract

`POST /api/v1/auth/local-session` has no request body and returns the existing
`AuthSessionResponse` shape.

- When local auto-login is disabled, return `403` with
  `local_auto_login_disabled`.
- When the client address is not loopback, return `403` with
  `local_auto_login_loopback_required`.
- Reuse the earliest active owner membership so previously created plans and
  watches stay visible.
- If no active owner exists, create one household named `Личный профиль`, one
  user named `Владелец`, and an owner membership in the same transaction.
- Issue a fresh hashed bearer session with the existing configured session TTL.
- Never return or log stored session hashes.

`IdentityRepository` gains one narrow query for the first active owner. No
schema change or migration is required.

## Browser flow

The account area becomes a small `Локальный профиль` status popover. Invitation
code/name inputs and `Войти`/`Выйти` buttons are removed. A secondary
`Переподключить профиль` action is retained for recovery.

On page load:

1. Validate a bearer token already stored in local storage.
2. If it is missing or expired, call `/api/v1/auth/local-session`.
3. Store the returned token through the existing `storeSession` path.
4. Load watches, confirmations, audit data and the last durable agent plan.

Reconnection removes only the browser session token, immediately requests a new
local session and reloads session-bound data. It does not delete server data.
Failure leaves the search composer visible and shows a concise profile error;
it never silently pretends that durable actions can be saved.

## Compatibility and boundaries

- Existing invitation, bearer, household and account-deactivation behavior is
  unchanged when local auto-login is disabled.
- Existing valid sessions always win; auto-login is only a recovery/bootstrap
  path.
- Provider credentials and flight facts never enter the auth response or UI.
- The endpoint is unsuitable for network deployment by design and is protected
  by both an explicit setting and the loopback address check.

## Verification

- API test: disabled setting is rejected.
- API test: enabled setting rejects a non-loopback client.
- API test: first loopback call creates an owner; a later call reuses the same
  household/user and both bearer tokens authenticate through `/auth/me`.
- UI contract test: invitation inputs and `Войти`/`Выйти` copy are absent; the
  local-session bootstrap and reconnect action are present.
- One rendered browser flow: clear the old token, reload, confirm the profile
  becomes ready, submit a complete agent prompt, and observe a durable run
  starting without opening an auth form.
- Targeted Ruff, mypy and auth/UI tests only; no full-suite run.
