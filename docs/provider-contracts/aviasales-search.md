# Aviasales Search API Contract Notes

Verified: 2026-07-17. Sanitized live checks established that Suggest and exact
start returned schema-valid HTTP 200 responses, exact polls returned both
schema-valid lists and an empty HTTP 304 incremental response, and Explore calendar returned schema-valid rows with
`locale=ru_RU`. The older `locale=ru` value returned HTTP 400 with an invalid
locale classification. No prices, search IDs, result hosts, booking URLs,
credentials or raw payloads were recorded. Search/result/click field provenance
also uses the sanitized 2026-07-04 capture against `tickets-api.aviasales.ru`.

The 2026-07-17 release smoke imported the local Aviasales kit without executing
its Python client. A sanitized `LED` → `CDG` one-way smoke received 50
schema-valid `live` items; a separate round-trip check received 48 valid offers.
The live result also confirmed a provider-tagged airport-change itinerary whose
adjacent flights used different Istanbul airports. Only status, counts, source,
freshness, timestamps and the minimum structural tags needed to verify the
contract were retained; no price, credential, provider reference, raw payload
or booking URL was recorded.

The same verification found valid Paris-area round trips where outbound and
return use different airports. Aviasales marks these rows with
`airport_different`. The v1 reciprocal round-trip evidence model cannot express
that shape without losing facts, so those rows are skipped individually; other
well-formed tickets in the same chunk continue through exact request binding.

Hot offers: APK contract statically verified 2026-07-15. No live hot-offer smoke
was run, so the hot-offer section makes no claim of current upstream availability
or of having captured an observed live payload.

Exact-search mapping and lazy booking-action boundaries were reverified
2026-07-16 against the sanitized 2026-07-04 capture and the local APK sources.
This verification covered Unix departure/arrival instants, deterministic
evidence identity, duplicate-ticket handling and the private click descriptor.
No live provider request was made.

Source: reverse-engineered from Aviasales Android APK `Aviasales_7.24.0` (local
hobby project, not a partner integration). The mobile API endpoints below are
used directly — no authorization, no partner token, no official ToS gating. See
`AGENTS.md` for the project's stance on this.

Local provenance inspected for this release:

- `C:\Users\kiwun\Документы\api finder\aviasales_search.py`;
- `C:\Users\kiwun\Документы\api finder\aviasales_client.py`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work` (APK/decompiled worktree).

The Explore hot-offer contract is pinned to these exact decompiled classes:

- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\feature\hottickets\data\hotticket\service\HotTicketsService.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\feature\hottickets\data\hotticket\entity\HotTicketsDto$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\feature\hottickets\data\hotticket\entity\HotTicketsDto$Direction$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\feature\hottickets\data\shared\entity\TicketDto$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\feature\hottickets\data\shared\entity\CityDto$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\content\data\model\places\PlacesDto$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\explore\content\data\model\places\PlacesDto$Translation$$serializer.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\shared\ariadne\fragment\PriceFragmentImpl_ResponseAdapter$PriceFragment.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\shared\ariadne\fragment\PriceFragmentImpl_ResponseAdapter$Segment.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\shared\ariadne\fragment\PriceFragmentImpl_ResponseAdapter$FlightLeg.java`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work\jadx_out\sources\aviasales\shared\ariadne\fragment\PriceFragment.java`.

Credential values from these materials are intentionally not copied into this
contract, logs, fixtures or smoke output.

Implementation status: **implemented** as a live adapter at
`src/flight_hunter/providers/aviasales_search/` with fixture-based contract tests.
Live calls are made with `curl_cffi` Chrome TLS impersonation to pass CloudFront
WAF. No live calls run in CI.

## Endpoint inventory

| Endpoint | Method | Purpose | Auth |
|---|---|---|---|
| `https://tickets-api.aviasales.ru/search/v2/start` | POST | Start a search, get `search_id` + `results_url` | `X-Signature` header |
| `https://{results_url}/search/v3.2/results` | POST | Poll result chunks until tickets appear | `X-Signature` + `X-Request-Id` |
| `https://tickets-api.aviasales.ru/searches/{search_id}/clicks/{proposal_id}` | GET | Resolve a purchase URL for a specific proposal | `marker` query |
| `https://suggest.aviasales.ru/v2/places.json` | GET | City/airport IATA autocomplete | `marker` query |
| `https://explore-api.aviasales.ru/v1/hot_offers/list.json` | GET | Hot offers | `marker` query |
| `https://explore-api.aviasales.ru/api/v6/calendar.json` | GET | Price calendar | `marker` query |
| `https://ariadne.aviasales.ru/api/gql` | POST | GraphQL feed/blocks (`MainPageBlocksV1`, `DirectionPageBlocksV2`, `WeekendPricesListV1`, `AIFlexibleCalendarResultsV4`) | — |

Reference: the local provenance paths above and provider fixtures in
`tests/fixtures/provider/aviasales_search/`. `raw_chunk_mow_led.json` is the
sanitized exact-search capture. `hot_offers_nested_apk_contract.json` is a
synthetic fixture constructed from the inspected APK serializers/adapters; it
is not an observed provider response.

## Request schema — `/search/v2/start`

Headers:
```
User-Agent: Aviasales/7.24.0 (Android; 14; Pixel_8) okhttp/5.3.2
X-Client-Type: mobile
X-Signature: <redacted mobile client signature>
Referer: https://www.aviasales.ru/
Accept: application/json
```

Body:
```json
{
  "search_params": {
    "directions": [
      {"origin": "SVO", "destination": "LED", "date": "2026-09-15",
       "is_origin_airport": true, "is_destination_airport": true}
    ],
    "passengers": {"adults": 1, "children": 0, "infants": 0},
    "trip_class": "Y"
  },
  "marker": "mobile_app.{md5(android_id)}",
  "market_code": "RU", "currency_code": "RUB",
  "languages": {"ru": 1.0}, "debug": {}, "brand": "AS",
  "search_source": "mobile", "filters": {}
}
```

Round trip: append a second direction with swapped origin/destination and
`date` = return date. Each direction preserves the typed location kind of its
own origin/destination, so an airport remains `true` after the swap. The agent
gateway admits a city code only when its frozen capability snapshot marks city
semantics `supported`; the current snapshot is `unknown`, so agent plans fan out
to explicit airport codes instead of guessing these flags. The legacy adapter
retains its compatibility city flow outside approved orchestrator runs.

Response: `{"search_id": "...", "results_url": "host.aviasales.ru", "blet_url": "..."}`.

`results_url` is contractually a bare ASCII hostname, not a URL. The client
normalizes it to lowercase and accepts only `aviasales.ru` or a DNS-valid
subdomain of `aviasales.ru`. Schemes, paths, queries, fragments, userinfo,
ports, IP literals, non-ASCII labels and external suffixes fail before any
poll/click I/O. The start response and every later poll/click boundary apply
the same validator.

The only contract-verified exact-search trip class is the closed provider enum
value `Y` (economy). Market and currency inputs are ASCII-only; a proposal must
carry an explicit ASCII ISO currency and a non-negative integer-minor-unit
amount. The mapper never supplies a fallback currency.

## Request schema — `/search/v3.2/results` (polling)

POST `https://{results_url}/search/v3.2/results` with header `X-Request-Id: {uuid}`.

Body:
```json
{
  "search_id": "...", "limit": 50,
  "last_update_timestamp": 0,
  "required_tickets": [], "highlighted_ticket": null,
  "search_by_airport": false, "price_per_person": false,
  "filters_state": {}
}
```

`last_update_timestamp` is updated monotonically to the max seen across chunks.
`poll_results_once` performs one request and returns validated chunks, the next
cursor and whether that response contains tickets. The legacy synchronous
`poll_results` wrapper repeats that primitive for compatibility. Approved agent
runs use a client with `max_retries=0`; each retry is therefore a separate
leased/budget-reserved operation attempt rather than hidden transport work.

Live verification on 2026-07-17 returned both ticket-bearing and empty chunks
with `last_update_timestamp=0`. Confirmed, request-bound evidence counts as
useful progress even when the provider cursor does not advance; an empty chunk
stores no evidence and consumes one of the explicitly bounded poll rounds before
retrying. A cursor regression is still rejected as a schema error, so an
unchanged empty response cannot create live evidence or an unbounded loop.

An HTTP 304 poll with an empty body means that this cursor has no incremental
update yet. It is normalized to an empty chunk tuple without JSON decoding and
without advancing the cursor; the same bounded poll loop can then continue.
Malformed bodies remain schema errors.

The gateway continuation binds the normalized route, departure/return dates,
currency, passenger total and caller-supplied operation UUID at start. Poll has
no independent passenger argument: it reconstructs and validates this private
state before I/O, then rejects any ticket whose route, trip shape, dates,
currency or money contradicts the bound request.

The sanitized exact-search fixture exposes no verified terminal
`complete`/`finished` field. A ticket-bearing poll proves confirmed evidence is
available but does **not** prove the upstream search is complete; the resumable
gateway conservatively reports `complete=false`.

## Request/response schema — Explore hot offers

GET `https://explore-api.aviasales.ru/v1/hot_offers/list.json`. The agent path
sends the frozen airport origin and approved date basis as:

```text
origin=SVO
origin_type=airport
market=RU
passport_country=RU
language=ru
currency=rub
one_way=true
sort_type=price
with_baggage=false
direct=false
depart_months[]=2026-09&depart_months[]=2026-10
marker=<private>
```

`depart_months[]` is the canonical, unique, ascending `YYYY-MM` sequence that
covers every month intersecting the inclusive approved `date_from..date_to`.
It is a coarse provider filter, not permission to publish every returned day.
ANYWHERE discovery is limited to 12 inclusive calendar months. Planning returns
the typed `anywhere_date_range_too_large` clarification above that boundary;
scope reconstruction and the client repeat the same check before provider I/O.

The APK serializers establish this nested response, with no flat `tickets` or
flat price fallback:

- top level: `origin` (`CityDto`, whose required translation key is `su`),
  `directions`, nullable `sale_info`, `entities_info` (`PlacesDto`; its
  airport/city/country maps are optional), nullable `tags_order`,
  `filters_order`;
- each direction: `destination_iata`, `ticket`, nullable `sale_ticket`, nullable
  `tags`, `tickets_count`;
- each ticket: a required `price` JSON object and nullable `badge`;
- each price: `signature`, `value`, `currency`, `duration`, `gate`, `search_id`,
  `origin_city_iata`, `destination_city_iata`, `depart_date`, `return_date`,
  `withBaggage`, `fareKey`, `segments`.
- each non-empty segment: `localArrivalDate`, `localArrivalTime`,
  `localDepartDate`, `localDepartTime`, non-empty `flightLegs`, `transfers`;
- each flight leg: `localArrivalDate`, `localArrivalTime`, `localDepartDate`,
  `localDepartTime`, `origin`, `destination`, `carrier`, `technicalStops`,
  `flightNumber`, `aircraftCode`, `durationSeconds`, `equipmentType`.

`HotTicketsDto` and its `Direction` serializer provide the container mapping;
`TicketDto$$serializer` proves that `price` is the nested JSON object; the
`PriceFragment` response adapters provide the price, segment and flight-leg
response names and scalar types. The mapper emits one typed row for
`ticket.price` and, when present, one for `sale_ticket.price`.

`origin_city_iata` and `destination_city_iata` are city identifiers, not airport
identifiers. The direction `destination_iata` is bound to
`destination_city_iata`; neither city code is exported as the flown route. The
actual origin/destination airports come from the first origin and final
destination of the ordered, continuous, non-empty
`segments[].flightLegs[]`. The first airport must equal the approved request
origin. The fixture deliberately models request `SVO`, price city route
`MOW`→`PAR`, and actual flight leg `SVO`→`CDG`; the typed output is `SVO`→`CDG`.
Empty, malformed or discontinuous flight legs are schema errors.

The mapper also requires canonical ISO dates, matching ASCII ISO currency and
an integer-valued, non-negative major-unit `value`, converted once to integer
minor units. The converted value must fit the shared signed SQL `Integer`
ceiling of `2,147,483,647` minor units; larger provider values fail as schema
errors before multiplication, mapping or persistence.
`signature` is validated only as private structural provenance and is never
stored, logged, represented or exported.

Malformed rows, route/origin contradictions, currency contradictions and
one-way rows carrying a return date fail the whole response with the stable
`aviasales_search_schema_error`. A structurally valid row outside the exact
approved day window is merely a coarse-month nonmatch and is skipped; valid
in-window rows in the same payload remain usable.

The hot-offer boundary is resource-bounded before mapping: at most 2 MiB of
response bytes, 512 directions, 64 direction/top-level tags, 64 filters, 2,048
combined airport/city/country entities, 8 segments per price, 16 flight legs
and 16 transfers per segment, and 8 technical stops per leg. Exceeding any
limit fails the whole batch as `aviasales_search_schema_error` without retry.
The parser still validates every object inside those bounds, but constructs and
retains no more `HotOffer` objects than the current durable per-binding
remaining capacity. Exact approved day bounds, the frozen catalog-airport
allowlist and already-persisted destinations for that origin/source binding are
applied before a row consumes this capacity. Candidate selection is bounded and
deterministic; the cheapest eligible row per destination wins. Rows outside the
filters are still schema-validated, so a malformed later row fails the batch.

Hot offers are `API_CACHED` discovery signals, never live confirmed prices.
The endpoint exposes an indicative provider-one-adult basis, so every emitted
signal has `passengers=1` even when the approved request contains a larger
adult/child/infant mix. Exact search later verifies the actual requested mix.
The gateway passes the frozen airport allowlist only to make bounded candidate
selection safe; it does not consult mutable geography. The executor independently
revalidates every returned destination, source binding, date, currency and
remaining durable capacity before persistence.

## Request schema — Explore calendar

GET `https://explore-api.aviasales.ru/api/v6/calendar.json` with typed
`origin_iata`/`destination_iata`, matching `origin_type`/`destination_type`,
date bounds, currency and `locale=ru_RU`. Live verification on 2026-07-14
confirmed `ru_RU`; `ru` is no longer accepted by this endpoint.

Calendar rows are mapped to `DiscoverySignal` with source `calendar`, integer
minor-unit money, an explicit one-adult passenger basis and aware observation
time. They remain
`indicative`, require exact live confirmation and can never enter the confirmed
offer ranker. Wrong-route or out-of-range rows are discarded before date-matrix
overlay. A central validator also enforces ISO dates, requested ASCII currency,
non-negative amounts and one-way/round-trip shape. Date-matrix overlay requires
a typed context for route, currency, passengers and trip shape; contradictory
signals become a stable pricing denial or an empty validated result, never a
published fact.

## Response schema — result chunk

Top-level keys (verified from live capture 2026-07-04):
`tickets`, `flight_legs`, `airlines`, `agents`, `alliances`, `equipments`,
`places`, `meta`, `search_params`, `last_update_timestamp`, `chunk_id`, `order`,
`cheapest_ticket`, `filtered_cheapest_ticket`, `direct_flights_v2`, `filters`,
`brand`.

### `tickets[]`
- `id`: internal ticket id
- `signature`: ticket signature (redacted in fixtures)
- `segments[]`: each `{flights: [leg_index, ...], transfers: [], tags: []}` —
  `flights` are **indices** into the chunk's `flight_legs` array. A verified
  cross-airport connection contains a transfer object tagged
  `airport_change`; the ticket is tagged the same way.
- `proposals[]`: each `{id: "agent_id:index", price: {value, currency_code},
  price_per_person, agent_id, flight_terms, unified_price, weight, tags,
  minimum_fare, is_warmcache, cashback, cashback_per_person}`
- `flight_terms`: keyed by leg index, each `{fare_code, trip_class,
  seats_available, marketing_carrier_designator: {carrier, airline_id, number},
  baggage: {count}, handbags: {count, weight}}`

### `flight_legs[]`
- `origin`, `destination`: IATA airport codes
- `local_departure_date_time`, `local_arrival_date_time`: `"YYYY-MM-DD HH:MM"`
- `departure_unix_timestamp`, `arrival_unix_timestamp`
- `operating_carrier_designator`: `{carrier, airline_id, number}`
- `equipment`: `{code, type, name}`
- `signature` (redacted in fixtures)

### `airlines` / `agents` / `places`
Dictionaries keyed by IATA/id. `airlines[id].name.ru.default`, `agents[id].label.ru.default`
(or `.gate_name`), `places.airports[iata].name.ru.default`.

An exact ticket has one non-empty outbound direction and at most one non-empty
return direction. Adjacent flights must be continuous unless the corresponding
provider transfer object explicitly carries the verified `airport_change` tag;
an untagged gap remains a schema failure. A return must be reciprocal to the
outbound route, and extra or non-reciprocal direction groups are rejected.
Normalization derives the public origin/destination from the outbound and the
return date from the inbound departure. Provider-tagged airport changes remain
visible in the segment path, receive a ranking risk penalty and are shown in the
UI with unknown ground-transfer cost rather than being silently discarded.
Provider-tagged `airport_different` round trips are valid upstream alternatives,
not corrupt schema; they are omitted until the typed model carries distinct
return-airport endpoints. Other route/date/currency mismatches are filtered at
the gateway and never become confirmed evidence.

## Resumable agent gateway boundary

Exact start returns server-private `ExactSearchContinuation` state only. Its
search ID, result host, blet state, cursor, request ID, operation UUID and bound
request facts are excluded from `repr` and are not members of the public poll
result. Client DTOs holding start state or raw poll chunks are repr-redacted as
well. Ticket-bearing chunks map inside the provider boundary to
`ConfirmedOfferEvidence`: hash-only deterministic provider offer/segment IDs,
provider source, aware observation time, bound passenger total, verified
seller/segments, unknown protection and `None` for baggage when the response
does not provide it. Evidence UUIDs use UUIDv5 under the caller-supplied
operation namespace: retrying the same operation and provider content is
idempotent, while a new operation produces a distinct append-only observation.
Composition chronology uses only the verified
`departure_unix_timestamp`/`arrival_unix_timestamp` values normalized to aware
UTC datetimes. Local timestamp strings remain display evidence and never decide
connection feasibility.
Public evidence contains no raw DTO, proposal or click payload, booking URL,
signature, marker, cookie or token.

## Purchase URL — `/clicks/{proposal_id}`

GET `https://tickets-api.aviasales.ru/searches/{search_id}/clicks/{proposal_id}?marker=...&host={results_host}&blet_request_id={uuid}`.

`proposal_id` is the proposal `id` field (format `"agent_id:index"`, e.g. `"312:154"`).

Response: `{"url": "https://www.kupibilet.ru/booking/..."}` — direct booking URL
on the gate's site. The adapter resolves this **lazily on user click**, not
preloaded for every offer.

Agent-search results do not reuse the legacy reversible booking reference.
For each confirmed offer the provider boundary emits a repr-redacted private
descriptor (`search_id`, `proposal_id`, results host) tied to the sanitized
evidence UUID. The server stores it in the household/run scope and exposes only
a short-lived HMAC token containing an opaque descriptor UUID and expiry. An
authenticated explicit click rechecks household, plan, run, provider and expiry
before resolving the URL. Composed multi-ticket candidates remain unavailable
unless a later flow can represent every required purchase action unambiguously.

## Marker / identification

`marker = "mobile_app." + md5(android_id)`. Any generated marker is accepted by
the server for search. No account or JWT is required for search/prices/gates/
purchase links. JWT via `auth.aviasales.ru` is only for personal profile/orders.

## Transport — CloudFront WAF

Plain `httpx`/`requests` get HTTP 403 from CloudFront. The adapter uses
`curl_cffi` with `impersonate="chrome120"` (Chrome TLS fingerprint) plus the
mobile app headers (`User-Agent`, `X-Client-Type: mobile`, `Referer`). This is
the same approach as the decompiled APK client. HTTP 403 is surfaced as
`aviasales_search_blocked` so the UI can show an honest `blocked` state.
The real transport streams into a bounded buffer and aborts the download above
16 MiB for every endpoint; hot offers apply the tighter 2 MiB pre-decode limit
described above. A size abort is a non-retryable schema failure, and the
provider exception text and partial response bytes are discarded.

Stable failure codes:

| Condition | Direct API HTTP | Code | Retry |
|---|---:|---|---|
| Provider disabled | 503 | `aviasales_search_disabled` | no |
| Credentials missing | 503 | `aviasales_search_credentials_missing` | no |
| Local credential shape invalid | 503 | `aviasales_search_credentials_invalid` | no |
| Upstream HTTP 401 | 502 | `aviasales_search_auth_failed` | no |
| Upstream HTTP 403 | 502 | `aviasales_search_blocked` | no |
| Upstream HTTP 429 | 429 | `aviasales_search_rate_limited` | after `Retry-After` |
| Other upstream HTTP 4xx | 502 | `aviasales_search_unavailable` | no |
| Transport/5xx exhausted | 502 | `aviasales_search_unavailable` | bounded |
| Invalid provider JSON/schema | 502 | `aviasales_search_schema_error` | no |

Generic HTTP failures are body-free typed errors carrying only the numeric
status, its `client_error`/`server_error` class and retryability. Transport and
JSON-decoder implementation exceptions are converted after leaving their
active handlers, so provider-controlled exception text is absent from public
errors, tracebacks, causes and contexts. Structured logs use only a closed
endpoint name and stable error code; raw URL/host/payload/response text is not
logged.

Aggregate search and date-matrix endpoints keep their successful fake/partial
data and report the same stable code as a provider denial instead of failing the
whole request.

Exact live smoke (summary only):

```powershell
uv run flight-hunter-source-smoke --source aviasales_search --exact-search --origin MOW --destination LED --departure-offset-days 30
```

The output contains only status, code, count, source IDs and freshness values;
it excludes amounts, offer IDs, raw payloads, provider refs and booking URLs.
This command is historical exact-search provenance; it was not run as part of
the 2026-07-15 hot-offer APK verification.

## Policy (Flight Hunter, local hobby project)

- Adapter disabled until `AVIASALES_SEARCH_ENABLED=true` and
  `AVIASALES_SEARCH_SIGNATURE` / `AVIASALES_SEARCH_MARKER` are set in `.env`.
  Missing credentials → `credentials_missing` denial, no HTTP call.
- Exact search data kind: `LIVE`; confirmed results carry `observed_at` and
  `Freshness.LIVE`. Explore hot offers are `API_CACHED` indicative discovery
  signals and require exact verification.
- Background watch scans **allowed** (scheduler context authorized).
- Results are **mergeable** with other sources.
- Booking URL resolved lazily on click (`resolve_purchase_url`), not preloaded.
- `X-Signature`, `marker`, signed booking URLs and full tokens never appear in
  logs, API responses, or client bundles.
- `Retry-After` and rate-limit headers respected. 403 → `blocked` (no retry).
  401 → `auth_failed` (no retry). 429 → `rate_limited`. 5xx → retry with
  backoff (max 2).
- `curl_cffi` transport is the default; a fake transport is injected in tests so
  no live call is made in CI.
