# Human-readable places and airlines

Date: 2026-07-17
Status: revised after spec review; user approval pending

## Context

The current exact-search form accepts only three-letter codes. Airport search
returns airport rows only, the demo catalog does not contain Moscow, and result
cards ignore the airline and segment fields already present in the API. This
forces the user to know `DME`, `SVO` or `MOW` and then keeps showing those codes
as primary copy.

The product rule is universal, not Moscow-specific:

- choosing a city means its complete validated set of commercial airports;
- choosing a specific airport means only that airport;
- codes remain canonical internal identifiers and secondary UI metadata;
- names, flags and airline identity come from catalog/provider facts, never an
  LLM guess.

The selected approach is a local place directory now, with a provider suggest
adapter added later when credentials arrive. Provider enrichment must not
change the public UI contract or silently redefine a saved route.

## Goals

1. Accept city, airport or IATA input using source-confirmed Latin names and the
   bundled Russian aliases/translations available offline.
2. Show accessible suggestions with flag, human name, city and secondary code.
3. Preserve city-versus-airport identity through search, watches and agent
   plans, including retries and process restarts.
4. Render human-readable requested routes separately from the concrete airports
   used by an itinerary.
5. Render actual airline names and logos from validated segment evidence, with
   a deterministic local fallback.
6. Work without an external suggest API and become globally richer without a
   frontend rewrite when provider enrichment is enabled later.

## Non-goals

- Do not claim Russian names for every worldwide airport before a source
  provides them.
- Do not manually maintain every airport in the world; the imported airport
  catalog remains the airport source of truth.
- Do not make autocomplete depend on a live provider.
- Do not use an LLM to resolve geography or carrier identity.
- Do not change pricing, ranking or booking behavior.

## Canonical place identity

Identity is the typed pair `(kind, code)`, never a bare code. A city and airport
may legally have the same code without colliding.

```text
PlaceRef
  kind                  city | airport
  code                  uppercase three-letter IATA city/airport code

LocalizedLabel
  text                  source-backed display text
  resolved_locale       ru | en | source | none
  provenance            airport_catalog | bundled_overlay | provider_suggest
  fallback_reason       null | source_locale | country_code_only | code_only

PlaceOption
  ref                   PlaceRef
  display_name          LocalizedLabel
  city_name             LocalizedLabel | null
  country_code          ISO 3166-1 alpha-2 when valid, otherwise null
  country_name          LocalizedLabel | null
  airport_codes         validated immutable airport expansion
  executable            whether airport_codes is non-empty and valid
  identity_provenance   imported_airport | bundled_city_group
  directory_version     checksum of catalog snapshot + bundled overlays
  membership_version    version of the city-membership definition
  membership_observed_at source observation/release date
```

For an airport, `airport_codes` is exactly its own IATA code. For a city it is
the validated city group. `country_code` produces a Unicode flag only when it
is a valid ISO alpha-2 code. Flags are presentation; ISO codes remain facts.

Locale and provenance belong to each label because an option may combine a
Russian airport overlay with a source-language municipality. Versioned bundled
country labels provide Russian and English country names; if a label is absent,
the UI shows the ISO code without inventing a translation. V1 does not perform
automatic transliteration. Russian search works for explicitly bundled aliases
and translations; every imported airport remains searchable by exact IATA and
its source-confirmed Latin/source name.

## City groups and directory snapshots

City groups live in a versioned data file separate from code. A definition has
the city code, Russian/English names, aliases, country, allowed member countries,
a non-empty ordered set of airport codes, `coverage=complete`, membership
version, observation date and provenance. The initial set covers the accepted
demo routes and common metro codes, including Moscow. Airports themselves remain
in the existing reference catalog.

At directory build time every member must resolve in the same airport catalog
snapshot, belong to an explicitly allowed country and satisfy the existing
`Airport.is_searchable` invariant: valid IATA, large/medium commercial airport,
scheduled service and commercial provenance. One missing, closed, duplicate,
unsorted or non-searchable member invalidates the whole group; a partial group
must never masquerade as “all airports”. An invalid group is non-executable and
omitted from normal suggestions; typed lookup still returns its exact reason.

Newly imported airports do not silently join a city. Membership changes only
when a new versioned complete group explicitly includes them. An airport that
becomes non-searchable invalidates that group in newly built snapshots until a
new observed membership version is released. Existing saved search semantics
remain frozen to their previously validated airport set.

`directory_version` is a stable checksum over the airport-catalog snapshot,
city-group file and localization overlays. One canonical resolver builds the
snapshot used by exact search, watches and agent plans; no flow maintains a
second city map. Integrity checks run at startup and in tests.

## API and data flow

Expose provider-neutral endpoints:

- `GET /api/v1/places/suggest?q=...&locale=ru&limit=10` returns ranked local
  city and airport options. V1 has no live provider dependency. Empty and
  one-character queries return no matches without a catalog scan.
- `POST /api/v1/places/lookup` accepts at most 64 ordered, unique typed refs:

```json
{
  "locale": "ru",
  "places": [
    {"kind": "city", "code": "MOW"},
    {"kind": "airport", "code": "DME"}
  ]
}
```

  The response preserves order and returns one result per input with either a
  resolved option or a stable unresolved reason; it never resolves a bare code
  by guessing its kind.

Both endpoints use the same response envelope from V1 onward:

```text
catalog_status       ready | unavailable
enrichment_status    disabled | ready | partial | unavailable
directory_version    checksum or null when unavailable
items                 ordered results, each resolved or explicitly unresolved
```

This keeps the public response stable when provider enrichment arrives. In the
current release `enrichment_status=disabled`.

Autocomplete ranking is deterministic: exact code, exact alias/name, city-name
prefix, airport-name prefix, alias prefix, then substring. Results are stable by
kind and code. Future local/provider duplicates collapse only by `(kind, code)`.

New UI requests always send `origin_kind` and `destination_kind`. The public
request fields remain optional for legacy clients only; the application
boundary resolves an omitted kind before constructing `SearchIntent`:

1. exactly one executable typed identity for the code: use it;
2. both a city and airport exist: reject with `place_kind_required` (HTTP 422);
3. neither exists: reject with `place_unknown` (HTTP 422).

Therefore legacy `DME` resolves to airport and `MOW` resolves to city. There is
no default-to-city behavior. `SearchIntent`, `SearchRequest` and provider
location mapping carry the resolved kinds. The request fingerprint includes
kind, concrete frozen airport sets and directory/membership versions.

For exact Aviasales search, the provider receives a city code with
`is_airport=false` or an airport code with `is_airport=true`. Returned endpoint
airports are checked against the frozen expansion before being presented as a
match. Agent route planning continues to expand cities into explicit airport
pairs; selecting one airport expands to one code only.

The search response separates intent from evidence:

```text
requested_route.origin/destination   typed PlaceRef + localized display facts
itinerary.segments[*].origin/destination
                                     concrete airport PlaceRef(kind=airport)
```

This lets the title say `Москва → Париж`, while details truthfully show
`Домодедово (DME) → Шарль-де-Голль (CDG)`.

The synchronous exact-search snapshot lives for the request, participates in
its fingerprint and is echoed as `requested_route`; it has no restart boundary.
Any future persisted search record must store the same frozen structure used by
watches rather than resolving a bare code again.

## Persistence boundaries

A migration adds the following durable watch fields for both route ends:
`kind`, frozen ordered `airport_codes`, `directory_version` and
`membership_version`. Creation and a route-changing update resolve and freeze a
new snapshot atomically; date, passenger, currency and provider-only updates
retain the existing place snapshot. Watch idempotency keys and scan fingerprints
include all frozen route fields. Restored/retried scans use the stored snapshot,
not today's city definition.

Durable agent plans already freeze airport sets and checksums. Their resolver
must use the same `PlaceDirectory`, store the typed requested refs and retain the
existing frozen airport lists. Plans created before this slice are read through
the legacy resolver once; ambiguous/unknown plans fail visibly instead of being
silently reinterpreted.

Confirmed offers, browser observations, candidates and price snapshots describe
concrete itineraries. Their segment endpoints are therefore explicitly typed as
`airport`; they do not store a city kind. Their parent search/watch/agent plan
owns the requested route. Any standalone display lookup for those records sends
`PlaceRef(kind=airport, code=...)`.

## Web UX

Replace the two three-character inputs with accessible comboboxes. Example:

```text
🇷🇺 Москва                    Все аэропорты · MOW
🇷🇺 Домодедово                Москва · DME
🇫🇷 Шарль-де-Голль            Париж · CDG
```

Required behavior:

- debounce input and cancel stale requests;
- support arrows, Enter, Escape and pointer selection;
- expose proper combobox/listbox roles, active descendant and status text;
- keep explicit loading, empty and unavailable states;
- reject submit until both visible values have canonical typed selections;
- accept a raw IATA code only after exact local lookup resolves it;
- clear the canonical selection if the visible value is edited;
- keep codes as small secondary chips, never primary labels;
- on mobile, keep suggestions inside the viewport and preserve 44 px targets.

A shared client cache is keyed by
`(kind, code, locale, directory_version)`. Selections and batch lookup populate
it. The same formatter is used by exact results, watches, agent summaries,
confirmed candidates and live observations. An unresolved code remains visible
as the code with an explicit missing-label state; no fabricated name appears.

## Airline identity

The API already exposes segment `airline_code` and `airline_name`. Result cards
render unique carriers in first-segment appearance order:

- normalize a carrier logo code only when it matches `^[A-Z0-9]{2}$`;
- derive the image URL from one compile-time trusted HTTPS base; never accept a
  provider-supplied image URL or arbitrary redirect origin;
- allow only that exact host in image CSP;
- show the provider-confirmed airline name and code as secondary metadata;
- use a local monogram tile when the code is unsupported, the name is absent,
  the image source is unavailable or loading fails.

The image error handler is one-shot: it removes/hides the failed image and
reveals the already-rendered monogram, so it cannot loop and causes no layout
shift. Images load lazily and have useful alternative text. Multi-carrier
itineraries show up to three logos and a count for the rest. Fake/demo offers use
the same component and deterministic fallback.

Partial facts stay honest: code without name displays the code and code
monogram; name without a valid code displays the name and name monogram; neither
displays the generic label. If one normalized code has conflicting non-empty
names, the first segment's provider fact wins for that itinerary and a
diagnostic is recorded; names are never merged or guessed.

## Future provider boundary

When credentials arrive, a `ProviderPlaceEnrichment` port supplies both query
suggestions and typed batch lookup. It may contribute source-backed labels and
aliases only after mapping to a known local `(kind, code)`. The local directory
owns identity, kind, executability and city membership. Runtime provider data
cannot replace `airport_codes`, change a kind or mutate a saved snapshot.

A provider city without a complete validated local membership is display-only
and is omitted from executable search suggestions. If a future complete
membership feed is adopted, it is imported, validated and released as a new
versioned directory source rather than merged ad hoc at request time. Provider
failure remains nonfatal because local results are complete for the installed
catalog.

## Failure behavior

- Local catalog unavailable: return a typed empty result/status, not fake places.
- Invalid or unavailable typed selection: stable 422 machine-readable error.
- Missing localization: show source name, ISO country code and IATA as needed.
- Invalid country code: no flag and no guessed country.
- Missing carrier evidence: show `Авиакомпания не указана`.
- Broken logo: replace it with the monogram without layout shift.
- Later provider suggest failure: keep local results and expose nonfatal
  enrichment status.

## Testing

Implementation follows red-green TDD:

1. Directory tests for Moscow aliases, exact city/airport code collisions,
   commercial-airport validation, missing/closed members, directory checksums,
   group version updates and honest locale/country fallback.
2. API tests for ranked suggest, bounded typed batch lookup, ordered unresolved
   entries and stable error codes.
3. Legacy tests proving `DME` resolves as airport, `MOW` as city, collisions are
   rejected and unknown codes are rejected.
4. Adapter tests proving city/airport provider flags and filtering of concrete
   endpoint airports against the frozen expansion.
5. Migration/repository/scheduler tests proving typed watch restore, frozen
   membership across directory updates and fingerprint changes.
6. Agent tests proving a city expands to all frozen airports and a selected
   airport expands to exactly one.
7. Web contract tests for combobox semantics, flags, secondary codes, requested
   versus concrete route labels, trusted logo URL construction and one-shot
   monogram fallback.
8. Chromium tests that select `Москва · все аэропорты`, then `Домодедово · DME`,
   submit both flows and verify a 390 px viewport.
9. No live provider calls in automated tests; future enrichment uses sanitized
   fixtures.

## Delivery stages

### Now, without new API credentials

- local `PlaceDirectory`, versioned city groups and country labels;
- Moscow/demo airports and every imported searchable airport;
- typed suggest/lookup and legacy resolution;
- exact-form comboboxes, flags and human labels;
- city/airport correctness through search, watches and agent plans;
- requested-route versus concrete-itinerary formatting;
- airline logo component with deterministic fallback;
- migration, tests, documentation and local restart.

### Later, after credentials arrive

- implement and enable `ProviderPlaceEnrichment` suggest/lookup enrichment;
- cache provider suggestions for a bounded TTL without changing membership;
- add sanitized contract fixtures and update provider verification date.
