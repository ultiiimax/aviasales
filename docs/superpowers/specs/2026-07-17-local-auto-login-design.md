# Local auto-login design

## Goal

Make the personal loopback build usable immediately: opening the web UI must
produce a normal owner bearer session without an invitation code, name form or
second action. Searches, durable agent runs, history and watches must work on
the first page load.

## Selected approach

Add a config-gated local-session endpoint and reuse the existing auth/session
model. The local initializer and `.env.example` enable `AUTH_LOCAL_AUTO_LOGIN`
because the packaged v1 binds to loopback. Operators exposing the service beyond
the machine must disable it. The endpoint independently requires a loopback peer
address, so the config flag alone never grants a network client access. Normal
invitation endpoints remain available for non-local/multi-user API clients but
are no longer exposed in the personal UI.

Alternatives rejected:

- Removing authorization from scoped APIs would break household ownership and
  create a second unauthenticated execution path.
- Pre-generating and displaying an invitation still leaves the user blocked by
  setup ceremony and one-time codes.

## Backend contract

`POST /api/v1/auth/local-session` has no request body, returns `201` with the
existing `AuthSessionResponse` shape, and sets `Cache-Control: no-store`.

- When local auto-login is disabled, return `403` with
  `local_auto_login_disabled`.
- Read only the actual ASGI peer address (`request.client.host`); ignore
  `Forwarded` and `X-Forwarded-*`. Accept IPv4 loopback (`127.0.0.0/8`), IPv6
  `::1`, and IPv4-mapped loopback. Missing or malformed peers fail closed.
- When the peer address is not loopback, return `403` with
  `local_auto_login_loopback_required`.
- An active owner means `role=owner` and `disabled_at IS NULL`. If exactly one
  active owner exists, reuse that exact household/user so previous data remains
  visible. If more than one exists, return `409` with
  `local_auto_login_ambiguous`; never select an arbitrary household.
- If no active owner exists, create deterministic local household/user IDs, a
  household named `Личный профиль`, a user named `Владелец`, and an owner
  membership in one transaction. A uniqueness conflict rolls the transaction
  back and re-reads the deterministic active identity, making concurrent first
  requests converge on one profile. If those deterministic rows exist with a
  disabled membership, return `409 local_auto_profile_disabled` rather than
  silently reactivating a deleted account.
- Issue a fresh hashed bearer session with the existing configured session TTL.
- Reconnect does not revoke older sessions; they remain valid until their normal
  expiry/revocation.
- Never return or log stored session hashes.

`IdentityRepository` gains narrow active-owner and deterministic-identity
queries. No schema change or migration is required. Container/proxy peers are
intentionally not treated as loopback; such deployments use the invitation API
or a separately authenticated proxy rather than trusting forwarded headers.

## Browser flow

The account area becomes a small `Локальный профиль` status popover. Invitation
code/name inputs and `Войти`/`Выйти` buttons are removed. A secondary
`Переподключить профиль` action is retained for recovery.

On page load:

1. Validate a bearer token already stored in local storage.
2. If it is missing or expired, call `/api/v1/auth/local-session`.
3. Store the returned token through the existing `storeSession` path.
4. Load watches, confirmations and audit data, then restore the durable agent
   plan/run only from the existing browser-stored IDs. This slice adds no
   backend "latest plan" query.

Reconnection removes only the browser session token, immediately requests a new
local session and reloads session-bound data. It does not delete server data.
Plan/run IDs remain in local storage during token replacement. If the resulting
identity cannot access one, existing scoped API handling clears only that
inaccessible pointer.

Auth bootstrap is single-flight: concurrent callers share one promise, every
response is bound to the captured session generation, and stale responses
cannot overwrite a newer token. A `401` from `/auth/me` removes only the invalid
token and starts local bootstrap. A network error or `5xx` keeps the current
token/pointers intact and shows `Профиль временно недоступен`; reconnect retries
explicitly. A local-session `403`/`409` shows its stable local-profile error and
does not fall back to a fake signed-in state. The search composer stays visible
in all failures, but durable actions remain unavailable until auth succeeds.

## Compatibility and boundaries

- Existing invitation, bearer, household and account-deactivation behavior is
  unchanged when local auto-login is disabled.
- Existing valid sessions always win; auto-login is only a recovery/bootstrap
  path.
- With auto-login disabled or a non-loopback peer, the bundled UI is deliberately
  read-only for session-bound actions; multi-user authentication remains
  available through the documented invitation API.
- Provider credentials and flight facts never enter the auth response or UI.
- The endpoint is unsuitable for network deployment by design and is protected
  by both an explicit setting and the loopback address check.

## Verification

- API test: disabled setting is rejected.
- API test: enabled setting rejects a non-loopback client.
- API test: first loopback call creates an owner; a later call reuses the same
  household/user and both bearer tokens authenticate through `/auth/me`.
- API tests: concurrent first calls converge; multiple active owners and a
  disabled deterministic profile return stable `409` errors; IPv4, IPv6,
  IPv4-mapped, missing/malformed and forwarded-header cases enforce the actual
  peer rule.
- UI contract test: invitation inputs and `Войти`/`Выйти` copy are absent; the
  local-session bootstrap and reconnect action are present.
- UI unit tests: a `401` triggers single-flight replacement, a network/`5xx`
  failure preserves the token and plan/run pointers, and a stale bootstrap
  response cannot overwrite a newer session.
- One rendered browser flow: clear the old token, reload, confirm the profile
  becomes ready, submit a complete agent prompt, and observe a durable run
  starting without opening an auth form.
- Targeted Ruff, mypy and auth/UI tests only; the cases above stay grouped in a
  compact test set and no full-suite run is required.
