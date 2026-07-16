# Human-readable places and airlines

Date: 2026-07-17
Status: approved direction, implementation pending

## Context

The current exact-search form accepts only three-letter codes. Airport search
returns airport rows only, the demo catalog does not contain Moscow, and result
cards ignore the airline and segment fields already present in the API. This
forces the user to know `DME`, `SVO` or `MOW` and then keeps showing those codes
as primary copy.

The product rule is universal, not Moscow-specific:

- choosing a city means all commercial airports in that city;
- choosing a specific airport means only that airport;
- codes remain canonical internal identifiers and secondary UI metadata;
- names and flags come from catalog/provider facts, never from an LLM guess.

The selected approach is a hybrid place directory: local data works now and a
provider suggest adapter can enrich the same contract after credentials arrive.

## Goals

1. Let users enter city, airport or IATA text in Russian or Latin script.
2. Show accessible suggestions with flag, human name, city and secondary code.
3. Preserve city-versus-airport semantics through the search boundary.
4. Render human-readable routes everywhere the bundled UI currently shows raw
   airport codes.
5. Render the actual airline name and logo when segment evidence contains a
   validated carrier code, with a deterministic local fallback.
6. Work without an external API and become globally richer without changing the
   UI or public contract when the provider suggest source is enabled later.

## Non-goals

- Do not invent worldwide Russian translations before a source provides them.
- Do not bundle or manually maintain every airport in the world in this slice.
- Do not make autocomplete depend on a live provider.
- Do not use an LLM to resolve geography or carrier identity.
- Do not change pricing, ranking or booking behavior.

## Canonical place contract

Add an application-level `PlaceOption` that does not expose provider DTOs:

```text
code             canonical three-letter city/airport code
kind             city | airport
name             localized display name from the selected source
city_name        localized municipality/city when known
country_code     ISO 3166-1 alpha-2
airport_codes    immutable airport set for a city; one code for an airport
source           local_catalog | provider_suggest
localized        whether the chosen locale is source-confirmed
```

`country_code` produces a Unicode flag and a Russian country label at the UI
boundary. The flag is presentation only; the ISO code remains authoritative.

City groups live in a versioned data file, separate from code. Each group has a
city code, Russian/English names, aliases, country and explicit airport codes.
The initial offline data covers the accepted local/demo routes and common metro
groups, including Moscow. Airports still come from the existing reference
catalog. Adding a city later is a data change, not another parser branch.

Without provider credentials, the local directory supports every imported
airport plus the bundled city groups. It must honestly fall back to a source
name or IATA code when a localized name is unavailable. Aviasales Suggest later
implements a `ProviderPlaceSuggest` port and enriches the same `PlaceOption`;
it does not require frontend changes.

## API and data flow

Expose provider-neutral endpoints:

- `GET /api/v1/places/suggest?q=...&locale=ru` returns ranked city and airport
  options from the local directory. Provider enrichment is optional and
  disabled for this slice.
- `GET /api/v1/places/lookup?codes=...&locale=ru` returns display metadata for
  result, watch and plan codes without one request per code.

Autocomplete ranks an exact code first, then city-name prefix, airport-name
prefix, alias prefix and substring matches. Duplicate local/provider options
collapse by `(kind, code)` with localized provider facts winning only when the
provider path is enabled and valid.

Search requests gain typed `origin_kind` and `destination_kind`, defaulting to
`city` for backward compatibility. The Aviasales legacy adapter must pass these
kinds into `ProviderLocation`; it must no longer mark a selected airport as a
city. The durable agent path keeps its existing explicit airport expansion:
city selection freezes the whole city group's airport set, while airport
selection freezes exactly one airport.

The visible text is never trusted as the canonical search value. A combobox
selection stores code, kind and source-confirmed display metadata separately.
If the user edits the visible value after selection, the canonical selection is
cleared.

## Web UX

Replace the two three-character inputs with accessible comboboxes. Example
options:

```text
🇷🇺 Москва                    Все аэропорты · MOW
🇷🇺 Домодедово                Москва · DME
🇫🇷 Шарль-де-Голль            Париж · CDG
```

Required behavior:

- debounce input and cancel stale requests;
- support arrows, Enter, Escape and pointer selection;
- keep an explicit loading, empty and unavailable state;
- reject submit until both visible values have canonical selections;
- accept a raw IATA code only after exact local lookup resolves it;
- keep the code as a small chip, never the primary label;
- on mobile, keep suggestions inside the viewport and preserve 44 px targets.

A shared client-side place cache is populated by selections and batch lookup.
Route titles use `City` or `Airport` names with flags; secondary text carries
codes and the concrete airport path. The helper is used by exact results,
agent plan summaries, confirmed agent candidates, watches and live observations.
An unresolved code remains visible as `DME`, explicitly without a fabricated
name.

## Airline identity

The API already exposes validated segment `airline_code` and `airline_name`.
Result cards must render the unique carriers from those segments:

- a logo image derived only from a validated carrier code and an allowlisted
  static logo base;
- the provider-confirmed airline name;
- the two-character code as secondary metadata;
- a local monogram tile when the image fails or no logo source is available.

No provider-supplied image URL enters the DOM. Images load lazily and have useful
alternative text. Multi-carrier itineraries show up to three logos and a count
for the rest. Fake/demo offers use the same component and fallback behavior.

## Failure behavior

- Empty or one-character query: no request.
- Local catalog unavailable: return a typed empty local result, not fake places.
- Provider suggest unavailable later: keep local results and expose a nonfatal
  enrichment status.
- Missing localization: show the source name and code.
- Invalid country code: no flag; keep the country unknown.
- Missing carrier evidence: show `Авиакомпания не указана`, not a guessed brand.
- Broken logo: replace it with the monogram without layout shift.

## Testing

Implementation follows red-green TDD:

1. Domain/application tests for city groups, Moscow aliases, city-versus-airport
   airport sets, ranking, deduplication and honest localization fallback.
2. API tests for provider-neutral suggest/lookup and typed search location kinds.
3. Adapter contract test proving `MOW` is sent as city and `DME` as airport.
4. Web contract tests for combobox markup, flags, secondary codes, airline
   identity and no raw-code-only primary route.
5. Chromium tests that type `Москва`, select all airports, then type
   `Домодедово` and select only `DME`, including a 390 px viewport.
6. No live provider calls in automated tests; future provider enrichment uses a
   sanitized fixture.

## Delivery stages

### Now, without new API credentials

- local `PlaceDirectory` and versioned city groups;
- Moscow and other bundled groups plus every imported airport;
- exact-form comboboxes, flags and human labels;
- city/airport kind correctness through search;
- result/watch/agent route formatting;
- airline logo component with deterministic fallback.

### Later, after credentials arrive

- enable the provider suggest port;
- expand worldwide localized aliases and city codes from provider facts;
- cache provider suggestions for a bounded TTL;
- add sanitized contract fixtures and update the provider verification date.

