# Aviasales Search API Contract Notes

Verified: 2026-07-14. Sanitized live checks established that Suggest and exact
start returned schema-valid HTTP 200 responses, one exact poll returned a
schema-valid list, and Explore calendar returned schema-valid rows with
`locale=ru_RU`. The older `locale=ru` value returned HTTP 400 with an invalid
locale classification. No prices, search IDs, result hosts, booking URLs,
credentials or raw payloads were recorded. Search/result/click field provenance
also uses the sanitized 2026-07-04 capture against `tickets-api.aviasales.ru`.

Source: reverse-engineered from Aviasales Android APK `Aviasales_7.24.0` (local
hobby project, not a partner integration). The mobile API endpoints below are
used directly — no authorization, no partner token, no official ToS gating. See
`AGENTS.md` for the project's stance on this.

Local provenance inspected for this release:

- `C:\Users\kiwun\Документы\api finder\aviasales_search.py`;
- `C:\Users\kiwun\Документы\api finder\aviasales_client.py`;
- `C:\Users\kiwun\Документы\api finder\aviasales_work` (APK/decompiled worktree).

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

Reference: the local provenance paths above and sanitized provider fixtures in
`tests/fixtures/providers/aviasales_search/`.

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

The sanitized fixture and live response expose no verified terminal
`complete`/`finished` field. A ticket-bearing poll proves confirmed evidence is
available but does **not** prove the upstream search is complete; the resumable
gateway conservatively reports `complete=false`.

## Request schema — Explore calendar

GET `https://explore-api.aviasales.ru/api/v6/calendar.json` with typed
`origin_iata`/`destination_iata`, matching `origin_type`/`destination_type`,
date bounds, currency and `locale=ru_RU`. Live verification on 2026-07-14
confirmed `ru_RU`; `ru` is no longer accepted by this endpoint.

Calendar rows are mapped to `DiscoverySignal` with source `calendar`, integer
minor-unit money, passenger basis and aware observation time. They remain
`indicative`, require exact live confirmation and can never enter the confirmed
offer ranker. Wrong-route or out-of-range rows are discarded before date-matrix
overlay.

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
  `flights` are **indices** into the chunk's `flight_legs` array
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

## Resumable agent gateway boundary

Exact start returns server-private `ExactSearchContinuation` state only. Its
search ID, result host, cursor and request ID are excluded from `repr` and are
not members of the public poll result. Ticket-bearing chunks map inside the
provider boundary to `ConfirmedOfferEvidence`: hash-only deterministic offer
and segment IDs, provider source, aware observation time, passenger total,
verified seller/segments, unknown protection and `None` for baggage when the
response does not provide it. Public evidence contains no raw DTO, proposal or
click payload, booking URL, signature, marker, cookie or token.

## Purchase URL — `/clicks/{proposal_id}`

GET `https://tickets-api.aviasales.ru/searches/{search_id}/clicks/{proposal_id}?marker=...&host={results_host}&blet_request_id={uuid}`.

`proposal_id` is the proposal `id` field (format `"agent_id:index"`, e.g. `"312:154"`).

Response: `{"url": "https://www.kupibilet.ru/booking/..."}` — direct booking URL
on the gate's site. The adapter resolves this **lazily on user click**, not
preloaded for every offer.

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

Stable failure codes:

| Condition | Direct API HTTP | Code | Retry |
|---|---:|---|---|
| Provider disabled | 503 | `aviasales_search_disabled` | no |
| Credentials missing | 503 | `aviasales_search_credentials_missing` | no |
| Local credential shape invalid | 503 | `aviasales_search_credentials_invalid` | no |
| Upstream HTTP 401 | 502 | `aviasales_search_auth_failed` | no |
| Upstream HTTP 403 | 502 | `aviasales_search_blocked` | no |
| Upstream HTTP 429 | 429 | `aviasales_search_rate_limited` | after `Retry-After` |
| Transport/5xx exhausted | 502 | `aviasales_search_unavailable` | bounded |
| Invalid provider JSON/schema | 502 | `aviasales_search_schema_error` | no |

Aggregate search and date-matrix endpoints keep their successful fake/partial
data and report the same stable code as a provider denial instead of failing the
whole request.

Exact live smoke (summary only):

```powershell
uv run flight-hunter-source-smoke --source aviasales_search --exact-search --origin MOW --destination LED --departure-offset-days 30
```

The output contains only status, code, count, source IDs and freshness values;
it excludes amounts, offer IDs, raw payloads, provider refs and booking URLs.

## Policy (Flight Hunter, local hobby project)

- Adapter disabled until `AVIASALES_SEARCH_ENABLED=true` and
  `AVIASALES_SEARCH_SIGNATURE` / `AVIASALES_SEARCH_MARKER` are set in `.env`.
  Missing credentials → `credentials_missing` denial, no HTTP call.
- Data kind: `LIVE`. Results carry `observed_at` and `Freshness.LIVE`.
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
