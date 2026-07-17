# API-kit integration, automatic agent search and UI polish

Date: 2026-07-17
Status: user-approved design; revised after spec review

## Context

Flight Hunter already has a typed Aviasales mobile adapter, normalized offer
mapping, durable agent plans/runs, place resolution, composition, ranking,
watches and click-gated booking actions. The supplied personal API kit contains
working Aviasales credentials and a small reference client. The reference
client is useful as provenance, but it is less strict than the product adapter
and must not become a second production implementation.

A live, redacted probe on 2026-07-17 verified all supplied Aviasales surfaces:

- suggest, hot offers, calendar and Ariadne GraphQL returned HTTP 200;
- round-trip exact start returned the expected private continuation fields;
- three short result polls returned ticket, airline and place data;
- Flight Hunter's own safe source smoke accepted the same credentials;
- Flight Hunter exact search returned 50 normalized `LIVE` results.

The current web-agent endpoint still creates a deterministic plan and asks for
separate confirmation. Its optional Codex/OpenAI intent adapters and MCP flags
are not wired into that path. The main screen also exposes implementation
language and gives search progress/results less visual priority than the user
task.

The user selected an internal typed tool gateway. A separate MCP server is not
part of this slice. A complete user search message is itself authorization to
start a live search immediately.

## Goals

1. Import the supplied Aviasales credentials into local runtime configuration
   without copying secrets into source, browser output, logs or command output.
2. Make the web agent understand broad natural-language flight requests and
   deterministically execute every supported capability through application
   services.
3. Start an approved durable live run immediately when the message contains a
   complete, unambiguous search intent.
4. Preserve the existing normalized provider boundary, durable retries,
   composition, ranking, watches and click-gated booking behavior.
5. Polish the main UI into one obvious flow: ask, watch progress, compare
   results and act.
6. Validate the slice with a small number of high-value checks rather than a
   full regression suite.

## Non-goals

- Do not copy or import the API kit's Aviasales client as production code.
- Do not expose provider credentials to the model, frontend or MCP.
- Do not create a second search/ranking implementation for the agent.
- Do not add unrelated API-kit services such as weather, restaurants or maps.
- Do not add a standalone MCP process in this slice.
- Do not auto-open a seller URL or purchase anything.
- Do not run the repository-wide automated test suite.
- Do not rewrite the vanilla web UI into another framework.

## 1. Credential import and provider ownership

Add a local command:

```text
flight-hunter-import-api-kit --path <api-kit-root> [--env <env-file>]
```

The command owns only configuration import. It does not make provider calls.
It performs the following steps:

1. Resolve `<api-kit-root>`, then resolve exactly
   `<root>/aviasales/keys.json` and `<root>/aviasales/client.py`. Both final
   paths must remain below the resolved root, including through Windows
   junctions/reparse points; reject traversal, escape or missing regular files.
2. Parse JSON as data and parse Python assignments with `ast`; never execute or
   import the API-kit module. The accepted JSON names are `x_signature` and,
   when present, `marker`. The accepted Python names are `X_SIGNATURE`,
   `MARKER` and `ANDROID_ID`; only string literals are read.
3. Resolve values deterministically. `x_signature` is authoritative; if a
   literal `X_SIGNATURE` is also present it must match. A valid JSON `marker`
   is preferred, then a matching literal `MARKER`, otherwise the command
   derives `mobile_app.<md5>` from literal `ANDROID_ID`. Any two supplied
   representations that disagree are a conflict.
4. Validate the same shapes enforced by `AppSettings`: canonical UUID
   signature and `mobile_app.<32 lowercase hex>` marker.
5. Atomically update only `AVIASALES_SEARCH_ENABLED`,
   `AVIASALES_SEARCH_SIGNATURE` and `AVIASALES_SEARCH_MARKER` in the ignored
   local `.env`, preserving unrelated settings and its existing newline style.
6. Print only `{"configured":true,"provider":"aviasales_search"}` on
   success, never paths, lengths, hashes, partial values or source lines.

An invalid or incomplete kit leaves `.env` unchanged. The command has one
stable exit contract: `0` success, `2` invalid/missing/conflicting source and
`3` env write failure. Failure output is one stable code on stderr
(`api_kit_invalid` or `api_kit_env_write_failed`) without exception text or
source content. Existing credentials may be replaced only by an explicit
command run; there is no runtime dependency on the external kit path after
import.

The existing `AviasalesSearchClient`, gateway and adapter remain the sole
production provider implementation. The provider contract records the
2026-07-17 live verification without recording credentials, IDs, prices or
booking URLs.

## 2. Agent boundary

Introduce an application-level `AgentToolGateway`. It is a narrow facade over
existing services, not a generic command runner. Its concrete commands and
results are discriminated immutable DTOs:

```text
ResolveAgentIntent(message, selections) -> ResolvedIntent | Clarification
PrepareAgentSearch(resolved_intent)      -> PlanView
StartAgentSearch(plan_binding, grant)    -> RunView
GetAgentRun(run_id)                      -> RunView
GetAgentResults(run_id)                  -> AgentRunResultsView
CreateAgentWatch(watch_intent, grant)    -> WatchView
```

`plan_binding` is exactly `(plan_id, revision_id, expected_revision,
content_hash)`. `grant` carries action kind (`search_execute` or
`watch_create`), authenticated session/user/household identity, that binding
and the request idempotency key. The gateway validates the tagged DTO before
calling the lifecycle service.

Date discovery, hot offers, exact start/poll, airport expansion, split-ticket
composition, hidden-city research, ranking and price analysis remain internal
operations of the existing plan/execution services. They are not separate
model-controlled provider tools. This prevents the model from inventing a
search sequence or bypassing budgets.

The gateway receives household/user context from the authenticated server
session. It never accepts these identifiers from model output. It returns
closed result objects and stable error codes; no provider DTO, signature,
marker, continuation, raw proposal ID or seller URL crosses the boundary.
Booking does not pass through this gateway. Existing result DTOs expose an
opaque typed candidate reference `(kind, UUID)` and, only when available, a
server-issued short-lived booking token. The existing authenticated booking
endpoint rechecks household, run, candidate and token expiry on the later user
click and returns only `resolved | unavailable`.

## 3. Intent understanding

Keep `IntentParser` as the deterministic source of truth. Add a provider-neutral
intent overlay that may improve free-form understanding but cannot supply
prices, schedules, airport facts or provider decisions.

For the local release, the overlay order is:

1. Use the configured Codex CLI adapter when enabled and available.
2. Optionally retain the existing OpenAI Responses adapter for users who later
   supply an API key.
3. On timeout, invalid structured output or missing model runtime, use the
   deterministic parser unchanged.

The model output is strict JSON and may contain only user intent fields already
validated by the domain: origin/destination text, trip shape, date mode/date
hints, passenger mix, currency, nearby radius, requested strategies, baggage
preference and explicit watch intent. Unknown fields and all provider facts are
rejected.

Merge precedence is fixed per field:

```text
explicit structured user selection
  > unambiguous deterministic parse
  > validated model overlay
  > clarification
```

The overlay may fill a field that the deterministic parser left unresolved; it
cannot replace an explicit selection or a deterministic typed value. A conflict
is ignored and recorded only as the stable diagnostic `intent_overlay_conflict`
with field name and model version. The merged draft carries internal per-field
provenance (`selection | deterministic | overlay`) until `ParsedIntent` is
materialized.

The model may help interpret phrases such as "в конце сентября на неделю",
"куда дешевле во Франции", "с багажом", "можно отдельными билетами" or
"следи за ценой". The deterministic parser/resolver still turns those hints
into typed geography, dates and strategies. Baggage is a typed result
preference (`checked | carry_on | none | unspecified`): candidates with unknown
evidence remain visibly unknown rather than being treated as matches. Every
other recognized constraint is marked `applied`, `advisory` or `unsupported`.
A material `unsupported` constraint blocks auto-execution and produces a
clarification asking whether to search without it; nothing is silently dropped.

Only the deterministic post-merge result decides completeness. Auto-execution
requires: no clarifications, all legs materialize through
`ParsedIntent.to_travel_intent(today=...)`, every material constraint is
`applied` or accepted as advisory, scope freezing succeeds and the plan builder
accepts the budget. Model output alone can never satisfy this gate.

Codex CLI execution is bounded by the configured timeout and output-byte limit.
The subprocess runs in a new empty temporary working directory with a minimal
allowlisted environment that omits all `AVIASALES_*`, tokens, keys and the
workspace path. It uses ephemeral read-only mode, receives the user message via
stdin plus the strict output schema, and has no filesystem/tool permissions.
Only validated stdout is consumed. Stderr is discarded after classification to
a stable transport code; raw stderr and command output are never logged.

## 4. Immediate authorization and durable execution

The authenticated chat message is an explicit user action. When parsing and
scope resolution produce a complete intent, the server:

1. creates the immutable plan revision;
2. records a one-time authorization bound to household, user, plan revision and
   request fingerprint;
3. confirms that exact revision;
4. persists the durable run and its initial operations;
5. returns the run ID, public plan summary and first progress state.

Plan creation and execution reuse the existing lifecycle transactions. If the
plan commits but execution does not, the inert awaiting-approval revision makes
no provider call and expires normally; the endpoint returns
`agent_run_not_created`. The run and its initial operations are persisted in
the database before success is returned; there is no separate volatile queue
publish. A crash after the run commit leaves a durable queued run that the
polling worker claims or recovers through existing leases.

The chat endpoint requires `Idempotency-Key`. The browser creates a random key
once per submit and retains it only while retrying that submission. The durable
execute idempotency index scopes the key to the authenticated household and
binds it to the exact plan/revision/content hash: the same key and binding
returns the same run forever, while the same key with another binding returns
`agent_run_idempotency_conflict`. A deliberate later search always gets a new
key; message text is never the idempotency key.

Automatic execution applies only to an explicit search command in the chat
endpoint. The system asks a clarification instead when required dates are
missing, geography is genuinely ambiguous, the plan exceeds absolute limits or
the provider cannot support the requested trip shape. Authorization is
action-scoped and single-use; a search grant cannot create a watch.

| User intent | Search action | Watch action | Public outcome |
|---|---|---|---|
| `найди ...` | one `search_execute` grant | none | `run_started` |
| `следи за ...` | baseline run | separate `watch_create` grant | `watch_created` with `run_id` |
| `найди и следи ...` | baseline run | separate `watch_create` grant | `watch_created` with `run_id` |

If watch creation fails after the run exists, the outcome is `run_started` plus
the nonfatal stable warning `watch_create_failed`; the search is not rolled
back. Booking remains an explicit later click because its URL is short-lived
and candidate-specific.

The legacy manual plan/confirm/run endpoints remain available for diagnostics
and advanced use; their semantics do not change.

## 5. Data flow

```text
user message
  -> authenticated chat endpoint
  -> deterministic parser + optional strict intent overlay
  -> typed place/scope resolution
  -> clarification OR immutable plan + one-time authorization
  -> AgentToolGateway.start_search
  -> durable worker operations
  -> Aviasales adapter (calendar/hot offers/exact start/poll)
  -> normalized evidence
  -> composition, risk, ranking and analysis
  -> public progress/results projection
  -> result cards, watch action and click-gated booking
```

The chat response does not wait for all provider polling. It returns promptly
with `run_id` and `state=queued|running`; the UI follows the existing run
projection until a terminal or partial state. A completed run is reloadable
after browser refresh.

The chat response is one tagged union; clients never infer state from nullable
field combinations:

```text
clarification { code, message_ru, options[] }
run_started   { plan, run, idempotent_replay, warnings[] }
watch_created { watch_id, plan, run, idempotent_replay, warnings[] }
failure       { code, message_ru, retryable }
```

## 6. Web UX

The page remains server-rendered vanilla HTML/CSS/JavaScript and keeps the
current visual identity. The polish changes hierarchy and states rather than
starting another redesign.

### Primary flow

- One prominent agent input is the first action on the page.
- Short example prompts sit below it and insert editable text rather than
  launching hidden behavior.
- On submit, the composer becomes compact and the progress/results workspace
  moves into the first viewport.
- Human progress stages are: `Понимаю маршрут`, `Проверяю аэропорты и даты`,
  `Ищу живые варианты`, `Сравниваю маршруты`, `Готово`.
- Internal terms such as harness, runtime, capability version, Cloudflare,
  operation ledger and raw provider codes move to a collapsed diagnostics area.

### Results

Candidates are grouped by deterministic ranking labels:

- `Лучший вариант`;
- `Самый дешёвый`;
- `Самый быстрый`;
- `Меньше риска`.

A card leads with total price for the requested passenger mix, human requested
route and the actual airport path. It then shows carrier identity, duration,
stops, baggage state, ticket/split protection, freshness and observation time.
Unknown baggage or protection is written as unknown, not omitted.

Connection details expand into an ordered timeline. Self-transfer, airport
change, overnight, split tickets and hidden-city risk are visible before the
details are opened. Primary actions are `Открыть покупку`, `Следить за ценой`
and `Подробнее`; unavailable actions explain why inline.

The exact form and advanced parameters remain in progressive disclosure. On
mobile, cards become single-column, tap targets remain at least 44 px and the
currently relevant action bar may stay at the bottom without covering content.

### States

- Clarification: inline question with concrete selectable choices.
- Loading: stage-aware skeleton/progress, not a generic spinner.
- Partial: preserve successful candidates and name the failed stage.
- Empty: state what was searched and offer date/airport widening actions.
- Provider rate/network failure: concise message and an enabled retry only when
  the typed error says retry is valid.
- Session missing: keep the drafted prompt while presenting sign-in.

## 7. Failure handling

- API-kit parse/validation failure never changes `.env`.
- Optional intent-model failure falls back to deterministic parsing.
- Invalid model JSON is data-validation failure, not a server crash.
- Provider 401/403/schema errors are terminal typed failures for the operation.
- Provider 429 and retryable transport/5xx errors use the existing durable
  retry schedule and public retry state.
- Failure of calendar/hot-offer discovery does not discard exact confirmed
  evidence already saved; terminal run status may be partial.
- Browser refresh reloads the active run from its opaque ID and authenticated
  household scope.
- No fake offer fills a live failure.

## 8. Focused verification

No repository-wide test run is part of this slice. Verification is limited to:

1. One parameterized credential-import test covering valid import, source
   conflict/path escape, redacted output and unchanged `.env` on invalid input.
2. One fixture-backed application/API scenario proving a complete chat message
   creates one authorized durable live run without a separate confirm call,
   the same idempotency key replays that run, and incomplete input produces a
   clarification with zero provider calls.
3. Targeted tests for the changed intent-overlay validator and the changed web
   rendering/state functions.
4. One Chromium smoke at desktop and 390 px mobile: submit a prompt, observe
   progress, render ranked cards and verify no horizontal overflow.
5. One safe live Aviasales smoke using summary-only output after local import.

Automated checks use fixtures and make no provider calls. The live smoke is a
manual local release check and prints no amount, provider identifier,
continuation, credential or booking URL.

## 9. Delivery and acceptance

Implementation is complete when all of the following hold:

- the import command configures the ignored local `.env` without secret output;
- API and workers restart with Aviasales enabled and report healthy readiness;
- a complete natural-language request immediately returns a durable run ID;
- no separate confirmation click is required for that search;
- an incomplete request returns one useful clarification and does not call the
  provider;
- live results retain source, freshness, observation time and passenger basis;
- country/region/anywhere scopes expand through frozen typed airport data;
- composition/ranking results are visible in polished result cards;
- booking still requires a candidate-specific click;
- the focused checks above pass.

Release handoff, separate from product acceptance: commit the implementation to
the current `main`, push its configured upstream `origin/main`, restart the
already-authorized local API and worker processes, and verify `/healthz`,
`/readyz` plus a non-stale worker heartbeat before reporting completion.
