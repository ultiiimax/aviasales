# Task 5A report: typed place combobox and payload

## Result

- Exact-search `origin` and `destination` are accessible text comboboxes backed
  by hidden canonical `code` and `kind` fields.
- Suggestions use `/api/v1/places/suggest`, 180 ms debounce, cancellation,
  keyboard/pointer selection and text-only DOM rendering.
- Editing visible text clears the canonical selection. Search and watch actions
  stop with a Russian error until both typed selections exist.
- Search and create-watch payloads carry `origin_kind` and `destination_kind`.
- Popup options show a validated ISO2 flag, factual name/city, kind and IATA;
  targets are at least 44 px and the popup is viewport-bounded.

## RED

Command:

```powershell
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads -q
```

Result: `1 failed in 1.53s`. The focused assertion failed because the old raw
field had no `origin-place-input` combobox contract.

## GREEN

Focused command:

```powershell
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads -q -x
```

Result: `1 passed in 1.04s`.

Required final command:

```powershell
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads tests/unit/api/test_web_ui.py::test_web_ui_uses_search_first_russian_hierarchy tests/unit/api/test_web_ui.py::test_root_serves_search_screen_without_cached_radar_or_secrets -q -x
```

Result: `3 passed in 1.13s`.

## Diff review

- `git diff --check`: clean.
- Changed scope before this report: only `src/flight_hunter/api/web.py` and
  `tests/unit/api/test_web_ui.py`.
- Full suite, project-wide lint and security suites were intentionally not run,
  as required by the Task 5A brief.

## Reviewer follow-up

- Popup placement now measures both controls, uses the visual viewport when
  available, chooses above/below and caps height to the actual free space on
  every render or keyboard reopen.
- Both comboboxes now use explicit labels outside their listboxes.
- Native `required` was removed only from the visible place inputs, so missing
  canonical selections reach the Russian live validation error.

RED command:

```powershell
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads -q -x
```

Result: `1 failed in 1.93s`; the strengthened contract caught `required` on the
visible place input before production changes.

Focused GREEN: the same command passed: `1 passed in 0.35s`.

Required final command remained the same three-node command above. Result:
`3 passed in 0.80s`. `git diff --check` remained clean. No broader test or lint
command was run.
