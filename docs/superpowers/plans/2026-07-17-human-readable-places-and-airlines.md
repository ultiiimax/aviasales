# Human-readable Places and Airlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw airport-code entry and display with typed city/airport autocomplete, factual localized place labels, country flags and carrier identities while preserving exact search and durable watch semantics.

**Architecture:** A provider-neutral `PlaceDirectory` builds an immutable snapshot from the existing airport catalog plus versioned city/label overlays. API boundaries resolve `(kind, code)` before search or watch creation, while providers receive the resolved city/airport kind and durable watches persist the frozen airport expansion. The existing server-rendered web shell consumes suggest/lookup endpoints through accessible comboboxes and renders concrete segment airports and carriers from API evidence.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy/Alembic/SQLite, vanilla HTML/CSS/JavaScript, pytest, Ruff, mypy, Playwright Chromium.

## Global Constraints

- New UI requests always send `origin_kind` and `destination_kind`; omitted legacy kinds are catalog-resolved, never defaulted blindly.
- `DME` resolves to `airport`; `MOW` resolves to `city`; typed identity is `(kind, code)`.
- A city is executable only when every member of its versioned complete airport set is present and searchable.
- Place labels, country labels, flags and airline names come from catalog/provider facts; the LLM is not a geography source.
- No live provider calls in automated tests.
- Provider-supplied image URLs never enter the DOM; carrier logos use one fixed HTTPS origin and deterministic monogram fallback.
- Money, ranking, booking, freshness and provider policy behavior remain unchanged.
- Work directly on `main` because the user explicitly requested it.

## File map

- `src/flight_hunter/domain/places.py`: typed place identity and immutable label/option/snapshot values.
- `src/flight_hunter/application/place_directory.py`: snapshot loading, validation, ranking, lookup and legacy resolution.
- `src/flight_hunter/geo/city_groups.v1.json`: complete versioned metro membership definitions.
- `src/flight_hunter/geo/place_labels.v1.json`: source-backed Russian place labels and aliases.
- `src/flight_hunter/geo/demo_repository.py`: offline airports required by bundled executable groups.
- `src/flight_hunter/domain/offers.py`: resolved origin/destination kinds on `SearchIntent`.
- `src/flight_hunter/application/search_service.py`: typed request fields and typed fingerprint material.
- `src/flight_hunter/providers/aviasales_search/adapter.py`: correct provider `is_airport` mapping and endpoint filtering.
- `src/flight_hunter/api/app.py`: place endpoints, typed search/watch schemas and requested-route response.
- `src/flight_hunter/persistence/models.py`: durable watch route snapshot columns.
- `src/flight_hunter/persistence/repositories.py`: serialize and restore typed watch snapshots.
- `src/flight_hunter/application/watch_service.py`: create/update commands carry frozen place snapshots.
- `src/flight_hunter/application/watch_scans.py`: restore kind and include frozen route data in scan identity.
- `migrations/versions/0030_typed_watch_places.py`: additive watch migration with explicit legacy marker.
- `src/flight_hunter/api/web.py`: accessible comboboxes, human route labels, flags and carrier logo/monogram UI.
- `pyproject.toml`: package the two new JSON data files.
- `IMPLEMENTATION_STATUS.md`, `README.md`: record behavior and local release verification.

---

### Task 1: Immutable place directory and offline facts

**Files:**
- Create: `src/flight_hunter/domain/places.py`
- Create: `src/flight_hunter/application/place_directory.py`
- Create: `src/flight_hunter/geo/city_groups.v1.json`
- Create: `src/flight_hunter/geo/place_labels.v1.json`
- Modify: `src/flight_hunter/geo/demo_repository.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/application/test_place_directory.py`

**Interfaces:**
- Consumes: `AirportCatalogSnapshot`, `Airport.is_searchable`, `countries.v1.json`.
- Produces: `PlaceKind`, `PlaceRef`, `PlaceLabel`, `PlaceOption`, `PlaceDirectory.from_snapshot()`, `suggest()`, `lookup()`, `resolve_legacy()` and stable typed exceptions.

- [ ] **Step 1: Write failing value-object and directory tests**

```python
def test_moscow_city_and_domodedovo_airport_are_distinct() -> None:
    directory = directory_from_demo()

    city = directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="ru")
    airport = directory.lookup(PlaceRef(PlaceKind.AIRPORT, "DME"), locale="ru")

    assert city.display_name.text == "Москва"
    assert city.airport_codes == ("DME", "SVO", "VKO", "ZIA")
    assert airport.display_name.text == "Домодедово"
    assert airport.airport_codes == ("DME",)
    assert city.country_code == airport.country_code == "RU"


def test_legacy_resolution_does_not_treat_dme_as_city() -> None:
    directory = directory_from_demo()
    assert directory.resolve_legacy("DME", locale="ru").ref.kind is PlaceKind.AIRPORT
    assert directory.resolve_legacy("MOW", locale="ru").ref.kind is PlaceKind.CITY


def test_incomplete_city_group_is_not_executable(tmp_path: Path) -> None:
    groups = write_groups(tmp_path, code="MOW", members=["DME", "XXX"])
    directory = PlaceDirectory.from_snapshot(
        freeze_airport_catalog(DemoAirportRepository().all()),
        city_groups_path=groups,
    )
    with pytest.raises(PlaceUnavailableError, match="city_group_member_missing"):
        directory.lookup(PlaceRef(PlaceKind.CITY, "MOW"), locale="ru")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/application/test_place_directory.py -q`

Expected: collection failure for missing `flight_hunter.application.place_directory`.

- [ ] **Step 3: Add strict typed values and directory implementation**

```python
class PlaceKind(StrEnum):
    CITY = "city"
    AIRPORT = "airport"


@dataclass(frozen=True, slots=True)
class PlaceRef:
    kind: PlaceKind
    code: str

    def __post_init__(self) -> None:
        code = self.code.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("place code must be a three-letter IATA code")
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class PlaceLabel:
    text: str
    resolved_locale: str
    provenance: str
    fallback_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlaceOption:
    ref: PlaceRef
    display_name: PlaceLabel
    city_name: PlaceLabel | None
    country_code: str | None
    country_name: PlaceLabel | None
    airport_codes: tuple[str, ...]
    directory_version: str
    membership_version: str
    membership_observed_at: str
```

Implement `PlaceDirectory` with deterministic Unicode case-folded search,
field-level locale/provenance, complete-group rejection, duplicate typed-key
rejection and a checksum over catalog/groups/labels/countries. Define
`PlaceUnknownError`, `PlaceKindRequiredError` and `PlaceUnavailableError` with
stable `.code` values.

- [ ] **Step 4: Add versioned local facts and demo airports**

`city_groups.v1.json` contains complete ordered groups for:

```json
{
  "version": "city-groups-v1-2026-07-17",
  "groups": [
    {"code":"MOW","country_code":"RU","allowed_member_countries":["RU"],"names":{"ru":"Москва","en":"Moscow"},"aliases":["москва","moscow"],"airport_codes":["DME","SVO","VKO","ZIA"],"coverage":"complete","membership_version":"mow-2026-07-17","observed_at":"2026-07-17","provenance":"bundled_city_group"},
    {"code":"PAR","country_code":"FR","allowed_member_countries":["FR"],"names":{"ru":"Париж","en":"Paris"},"aliases":["париж","paris"],"airport_codes":["BVA","CDG","ORY"],"coverage":"complete","membership_version":"par-2026-07-17","observed_at":"2026-07-17","provenance":"bundled_city_group"}
  ]
}
```

Add factual demo rows for `DME`, `SVO`, `VKO`, `ZIA`, `BVA`, `CDG`, `ORY` and
Russian overlays for those airports plus `LED`, `WAW`, `WMI`, `BCN`, `PVG`,
`SHA`. Package both JSON files in the wheel.

- [ ] **Step 5: Run focused tests and commit**

Run: `uv run pytest tests/unit/application/test_place_directory.py tests/unit/geo -q`

Expected: all selected tests pass.

Commit: `feat: add typed local place directory`

---

### Task 2: Provider-neutral place API and typed exact search

**Files:**
- Modify: `src/flight_hunter/domain/offers.py`
- Modify: `src/flight_hunter/application/search_service.py`
- Modify: `src/flight_hunter/providers/aviasales_search/adapter.py`
- Modify: `src/flight_hunter/api/app.py`
- Test: `tests/unit/api/test_places_api.py`
- Test: `tests/unit/api/test_api_app.py`
- Test: `tests/unit/application/test_search_service.py`
- Test: `tests/unit/providers/aviasales_search/test_adapter.py`

**Interfaces:**
- Consumes: Task 1 `PlaceDirectory` and typed values.
- Produces: `GET /api/v1/places/suggest`, `POST /api/v1/places/lookup`, typed search request fields, typed requested-route response and correct provider location flags.

- [ ] **Step 1: Write failing API and adapter tests**

```python
def test_places_suggest_returns_human_moscow_and_airports(client: TestClient) -> None:
    response = client.get("/api/v1/places/suggest", params={"q": "москва", "locale": "ru"})
    assert response.status_code == 200
    body = response.json()
    assert body["catalog_status"] == "ready"
    assert body["enrichment_status"] == "disabled"
    assert body["items"][0]["ref"] == {"kind": "city", "code": "MOW"}
    assert body["items"][0]["display_name"]["text"] == "Москва"


def test_search_resolves_legacy_airport_and_rejects_unknown(client: TestClient) -> None:
    request = valid_search_json(origin="DME", destination="CDG")
    response = client.post("/api/v1/searches", json=request)
    assert response.status_code == 201
    assert response.json()["requested_route"]["origin"]["ref"]["kind"] == "airport"

    request["origin"] = "XXX"
    response = client.post("/api/v1/searches", json=request)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "place_unknown"


def test_adapter_marks_selected_airport_as_airport(fake_client: FakeClient) -> None:
    adapter = enabled_adapter(fake_client)
    adapter.search(search_intent(origin="DME", origin_kind=PlaceKind.AIRPORT), request_fingerprint="fp")
    assert fake_client.start_params.origin.is_airport is True
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/api/test_places_api.py tests/unit/providers/aviasales_search/test_adapter.py -q`

Expected: route and schema assertions fail because typed endpoints/fields do not exist.

- [ ] **Step 3: Add place response schemas and endpoints**

Add typed Pydantic schemas for refs, labels, options, lookup items and the stable
envelope:

```python
class PlaceEnvelopeResponse(BaseModel):
    catalog_status: Literal["ready", "unavailable"]
    enrichment_status: Literal["disabled", "ready", "partial", "unavailable"]
    directory_version: str | None
    items: list[PlaceLookupItemResponse]
```

Load a request directory from `AirportReferenceRepository.catalog_snapshot()`
when an import exists; otherwise use the immutable demo snapshot. The lookup
body accepts at most 64 unique typed refs and preserves input order.

- [ ] **Step 4: Carry resolved kinds through search**

Add `origin_kind` and `destination_kind` to `SearchIntent` and `SearchRequest`.
The API fields are optional only for legacy input; resolve them with the request
directory before constructing `SearchRequest`. Return `place_kind_required` or
`place_unknown` as the existing coded 422 envelope. Include kinds, frozen airport
sets and versions in `_fingerprint()`.

Map provider locations exactly:

```python
origin=ProviderLocation(
    kind=LocationScopeKind.AIRPORT
    if intent.origin_kind is PlaceKind.AIRPORT
    else LocationScopeKind.CITY,
    code=intent.origin,
)
```

Filter returned first/last concrete endpoints against the request's frozen
airport sets only when those sets are non-empty.

- [ ] **Step 5: Return requested route separately from segment airports**

Add `requested_route.origin` and `.destination` as full `PlaceOption` responses.
Leave `OfferResponse.segments[*].origin/destination` as concrete airport codes;
the web layer will batch-resolve them with `kind=airport`.

- [ ] **Step 6: Run focused tests and commit**

Run: `uv run pytest tests/unit/api/test_places_api.py tests/unit/api/test_api_app.py tests/unit/application/test_search_service.py tests/unit/providers/aviasales_search/test_adapter.py -q`

Expected: all selected tests pass with no live provider calls.

Commit: `feat: add typed place search API`

---

### Task 3: Use the canonical directory in agent city expansion

**Files:**
- Modify: `src/flight_hunter/application/agent_scope.py`
- Test: `tests/unit/application/test_agent_scope.py`
- Test: `tests/unit/application/test_agent_planning.py`
- Test: `tests/unit/api/test_agent_api.py`

**Interfaces:**
- Consumes: Task 1 `PlaceDirectory` and the existing `AirportCatalogSnapshot` already loaded by `ScopeResolver`.
- Produces: city text and metro codes resolve through the same complete membership used by exact search; frozen agent plans retain concrete airport codes and checksums.

- [ ] **Step 1: Write failing Moscow resolution tests**

```python
async def test_city_text_moscow_resolves_complete_group() -> None:
    resolver = ScopeResolver(repository=StaticAirportCatalog(moscow_airports()))
    choice = await resolver.resolve_city_text("Москва")
    assert isinstance(choice, GeographyChoice)
    assert choice.scope == LocationScope(LocationScopeKind.CITY, "MOW")
    assert choice.airport_codes == ("DME", "SVO", "VKO", "ZIA")


async def test_finite_mow_scope_freezes_all_group_airports() -> None:
    resolver = ScopeResolver(repository=StaticAirportCatalog(moscow_airports()))
    frozen = await resolver.resolve_finite(
        LocationScope(LocationScopeKind.CITY, "MOW"),
        coverage=CoverageMode.FULL,
    )
    assert isinstance(frozen, FrozenAirportScope)
    assert frozen.airport_codes == ("DME", "SVO", "VKO", "ZIA")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/application/test_agent_scope.py -q`

Expected: Moscow text returns unknown geography and `MOW` freezes no airports.

- [ ] **Step 3: Resolve bundled cities through PlaceDirectory**

Build the directory from the exact snapshot already returned by the repository.
For city text, prefer one executable `PlaceKind.CITY` suggestion whose exact
name or alias matches and emit a `GeographyChoice` with its canonical city code
and full airport set. For finite city scopes, lookup the typed city ref and map
its frozen codes back to airports in the same snapshot. Preserve the current
municipality-anchor fallback for source cities that have no bundled metro group,
so existing worldwide agent behavior does not regress.

- [ ] **Step 4: Run agent tests and commit**

Run: `uv run pytest tests/unit/application/test_agent_scope.py tests/unit/application/test_agent_planning.py tests/unit/api/test_agent_api.py -q`

Expected: all selected agent tests pass and the frozen plan contains all Moscow airports.

Commit: `fix: resolve agent metro city scopes`

---

### Task 4: Freeze typed routes in watches

**Files:**
- Create: `migrations/versions/0030_typed_watch_places.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Modify: `src/flight_hunter/persistence/repositories.py`
- Modify: `src/flight_hunter/application/watch_service.py`
- Modify: `src/flight_hunter/application/watch_scans.py`
- Modify: `src/flight_hunter/api/app.py`
- Test: `tests/unit/api/test_watch_api.py`
- Test: `tests/unit/application/test_watch_scans.py`
- Test: `tests/integration/test_upgrade_from_pre_v1.py`

**Interfaces:**
- Consumes: typed place snapshots from Task 1 and search kinds from Task 2.
- Produces: durable watch fields for kind, airport expansion and directory/membership versions; restored scans preserve those fields.

- [ ] **Step 1: Write failing repository/API/scan tests**

```python
async def test_watch_restores_frozen_city_membership(session_factory) -> None:
    created = await create_watch(origin="MOW", origin_kind="city")
    restored = await repository.get_watch(created.household_id, created.id)
    assert restored is not None
    assert restored.origin_kind is PlaceKind.CITY
    assert restored.origin_airport_codes == ("DME", "SVO", "VKO", "ZIA")
    assert restored.origin_membership_version == "mow-2026-07-17"


def test_watch_scan_intent_restores_airport_kind(watch_record: WatchRecord) -> None:
    watch = replace(
        watch_record,
        origin="DME",
        origin_kind=PlaceKind.AIRPORT,
        origin_airport_codes=("DME",),
    )
    assert _intent_from_watch(watch).origin_kind is PlaceKind.AIRPORT
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/api/test_watch_api.py tests/unit/application/test_watch_scans.py -q`

Expected: assertions fail because watch route snapshot fields are missing.

- [ ] **Step 3: Add migration and model columns**

Add non-null `origin_kind`, `destination_kind`, JSON-text airport-code arrays,
directory version and two membership versions. Existing rows receive
`kind=city`, empty airport arrays and `directory_version=legacy-provider-city-v1`
to preserve their historical provider-city behavior without fabricating a
resolved membership. New rows always receive complete snapshots.

- [ ] **Step 4: Persist, restore and fingerprint route snapshots**

Extend `NewWatch`, `WatchRecord`, repository insert/update/row mapping and API
responses. Route-changing updates must carry both new typed snapshots in one
optimistic-lock update; non-route updates retain old values. `_intent_from_watch`
passes both kinds. `_scan_idempotency_key` hashes kind, frozen airport lists and
versions in addition to schedule time.

- [ ] **Step 5: Run migration and focused tests, then commit**

Run: `uv run alembic upgrade head`

Expected: current revision is `0030_typed_watch_places`.

Run: `uv run pytest tests/unit/api/test_watch_api.py tests/unit/application/test_watch_scans.py tests/integration/test_upgrade_from_pre_v1.py -q`

Expected: all selected tests pass.

Commit: `feat: persist typed watch routes`

---

### Task 5: Accessible place comboboxes and factual route rendering

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Test: `tests/unit/api/test_web_ui.py`
- Test: `tests/e2e/test_local_v1_browser.py`

**Interfaces:**
- Consumes: Task 2 suggest/lookup/search response contracts and Task 4 typed watch response.
- Produces: keyboard-accessible city/airport selection, flags, human route labels and shared place cache.

- [ ] **Step 1: Write failing web contract tests**

```python
def test_exact_search_uses_typed_accessible_place_comboboxes() -> None:
    html = TestClient(create_app()).get("/").text
    assert 'role="combobox"' in html
    assert 'data-place-role="origin"' in html
    assert 'name="origin_kind"' in html
    assert "/api/v1/places/suggest" in html
    assert 'aria-activedescendant' in html


def test_results_render_requested_and_concrete_place_names() -> None:
    html = TestClient(create_app()).get("/").text
    assert "formatPlaceLabel" in html
    assert "lookupAirportPlaces" in html
    assert "requested_route" in html
```

- [ ] **Step 2: Run tests and verify RED**

Run: `uv run pytest tests/unit/api/test_web_ui.py -q`

Expected: new combobox and route-format assertions fail.

- [ ] **Step 3: Replace raw code fields with combobox markup and CSS**

Each field keeps a visible text input plus hidden canonical `code` and `kind`.
Use `role=combobox`, `aria-autocomplete=list`, `aria-expanded`,
`aria-controls`, a listbox, live status and 44-pixel options. Suggestions show:

```text
🇷🇺 Москва                 Все аэропорты · MOW
🇷🇺 Домодедово             Москва · DME
```

- [ ] **Step 4: Implement deterministic client behavior**

Debounce by 180 ms, abort the previous fetch, support ArrowUp/ArrowDown/Enter/
Escape, clear canonical values after text edits, require both selections before
submit and resolve an exact raw IATA through typed lookup. Cache place options by
`kind|code|locale|directory_version`. Include both kinds in search, watch and
manual-observer payloads.

- [ ] **Step 5: Render requested route and concrete itinerary names**

After a result arrives, batch lookup all segment endpoints as airport refs.
Render the requested city/airport names as the card title and the concrete
airport path with codes below it. Use the same formatter for watches, external
links, live results and confirmed agent candidates. Unresolved codes remain
visible as codes with `Название не найдено`.

- [ ] **Step 6: Run desktop/mobile browser tests and commit**

Run: `uv run pytest tests/unit/api/test_web_ui.py tests/e2e/test_local_v1_browser.py -q`

Expected: unit and browser flows pass, including the 390-pixel viewport.

Commit: `feat: add human place comboboxes`

---

### Task 6: Carrier names, logos and deterministic fallback

**Files:**
- Modify: `src/flight_hunter/api/web.py`
- Test: `tests/unit/api/test_web_ui.py`
- Test: `tests/e2e/test_local_v1_browser.py`

**Interfaces:**
- Consumes: existing `OfferResponse.segments[*].airline_code/airline_name`.
- Produces: unique carrier strip ordered by first segment, trusted logo URL and one-shot monogram fallback.

- [ ] **Step 1: Write failing carrier rendering tests**

```python
def test_carrier_logo_uses_fixed_origin_and_one_shot_fallback() -> None:
    html = TestClient(create_app()).get("/").text
    assert "https://pics.avs.io/80/80/" in html
    assert "carrierCodePattern" in html
    assert "carrier-logo-failed" in html
    assert "offer.segments" in html
```

- [ ] **Step 2: Run test and verify RED**

Run: `uv run pytest tests/unit/api/test_web_ui.py -q`

Expected: carrier component assertions fail.

- [ ] **Step 3: Add carrier component and styles**

Accept logo codes only when `/^[A-Z0-9]{2}$/` matches. Build
`https://pics.avs.io/80/80/${encodeURIComponent(code)}.png` in local code only.
Render a fixed-size monogram before the lazy image; on the first image error,
mark `carrier-logo-failed`, remove `src`, hide the image and leave the monogram.
Never consume an image URL from API data.

Deduplicate by normalized code, keep first-segment order and show at most three
logos plus `+N`. Code without name shows code; name without code shows a name
monogram; neither shows `Авиакомпания не указана`.

- [ ] **Step 4: Run web tests and commit**

Run: `uv run pytest tests/unit/api/test_web_ui.py tests/e2e/test_local_v1_browser.py -q`

Expected: carrier rendering and fallback tests pass.

Commit: `feat: show airline identity in results`

---

### Task 7: Release verification, documentation and local restart

**Files:**
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify: `README.md`
- Modify: affected tests only when a verified regression exposes an inaccurate expectation.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: verified local v1, clean repository, documented commands and running API/worker.

- [ ] **Step 1: Run focused behavior gate**

Run:

```powershell
uv run pytest tests/unit/application/test_place_directory.py tests/unit/api/test_places_api.py tests/unit/providers/aviasales_search/test_adapter.py tests/unit/api/test_watch_api.py tests/unit/application/test_watch_scans.py tests/unit/api/test_web_ui.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run complete quality gate**

Run: `uv run pytest tests/unit tests/integration -q`

Expected: zero failures.

Run: `uv run ruff format --check .`

Expected: exit 0.

Run: `uv run ruff check .`

Expected: exit 0.

Run: `uv run mypy`

Expected: exit 0 with no errors.

- [ ] **Step 3: Run migration and browser gate**

Run: `uv run alembic upgrade head`

Expected: exit 0 at `0030_typed_watch_places`.

Run: `uv run pytest tests/e2e/test_local_v1_browser.py -q`

Expected: browser test passes or reports only the documented missing-browser skip;
when skipped, run `uv run flight-hunter-browser-bootstrap` and repeat.

- [ ] **Step 4: Update release docs and status**

Document human place input, city-versus-airport behavior, offline coverage,
carrier fallback and the fact that provider suggest credentials remain optional.
Mark the current slice complete only after the commands above produce fresh
passing output.

- [ ] **Step 5: Commit, restart and smoke-test**

Commit: `feat: release human-readable flight search v1`

Restart the local API and worker using the repository's existing hidden-process
workflow, then run:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
Invoke-WebRequest 'http://127.0.0.1:8000/api/v1/places/suggest?q=москва&locale=ru' -UseBasicParsing
```

Expected: HTTP 200, `status=ok`, and the first executable suggestion is
`Москва / MOW / city`.
