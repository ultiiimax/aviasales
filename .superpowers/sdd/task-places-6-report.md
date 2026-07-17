# Task Places 6 — carrier identity strip

## Result

- Added a carrier strip sourced only from segment `airline_code` and `airline_name` facts.
- Preserved first-seen order, removed duplicates, limited visible carriers to three, and added a `+N` remainder.
- Restricted logo requests to validated two-character carrier codes and the fixed `https://pics.avs.io/80/80/` origin.
- Kept a monogram visible while lazy images load; failed images use a one-shot fallback that removes `src` and hides the image.
- Wired the strip only to priced offers, confirmed agent candidates, and hidden-city candidates that have segments.
- Left place lookup and route-label logic unchanged.

## TDD evidence

RED:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_carrier_logo_uses_fixed_origin_and_one_shot_fallback -q
1 failed: missing JavaScript function appendCarrierStrip
```

GREEN:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_carrier_logo_uses_fixed_origin_and_one_shot_fallback -q
1 passed in 0.14s
```

Targeted regression verification:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_carrier_logo_uses_fixed_origin_and_one_shot_fallback tests/unit/api/test_web_ui.py::test_routes_use_shared_typed_place_lookup_and_honest_human_labels -q
2 passed in 0.29s
```

```text
git diff --check
exit 0
```

## Review correction

The first implementation treated a valid carrier code and carrier name as two
aliases for deduplication. That incorrectly collapsed distinct coded carriers
when their names happened to match. Deduplication is now code-first: a valid
code is the sole identity, while the normalized name is used only when no valid
code exists.

RED:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_carrier_logo_uses_fixed_origin_and_one_shot_fallback -q
1 failed: missing code-first `const identity = safeCode`
```

GREEN:

```text
uv run --no-sync pytest tests/unit/api/test_web_ui.py::test_carrier_logo_uses_fixed_origin_and_one_shot_fallback tests/unit/api/test_web_ui.py::test_routes_use_shared_typed_place_lookup_and_honest_human_labels -q
2 passed in 0.25s
```
