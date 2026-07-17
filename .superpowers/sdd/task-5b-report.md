# Task 5B report

## Result

- Added one shared client-side place cache keyed by
  `kind|code|locale|directory_version`.
- Combobox selections and search `requested_route` options seed the cache.
- Missing typed refs are resolved through `POST /api/v1/places/lookup` in
  unique batches of at most 64 entries.
- Search cards use the human `requested_route` as the main title and show
  concrete segment airport names with IATA codes below it.
- Watch routes use persisted `origin_kind` / `destination_kind` refs.
- External links, browser/live observations, deal candidates, confirmed agent
  candidates and hidden-city segment routes use the same factual formatter.
- Failed or unresolved lookups remain usable as the raw code plus
  `Название не найдено`; route facts are assigned through `textContent`.
- Carrier logos and visual redesign were not included.

## TDD evidence

RED:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_routes_use_shared_typed_place_lookup_and_honest_human_labels -q
1 failed: missing JavaScript function placeCacheKey
```

GREEN:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_routes_use_shared_typed_place_lookup_and_honest_human_labels tests/unit/api/test_web_ui.py::test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads -q
2 passed in 0.37s
```

Diff hygiene:

```text
git diff --check
exit 0
```

Browser QA is intentionally deferred to Task 7 as required by the Task 5B
brief. Full suite, lint and security commands were not run.
