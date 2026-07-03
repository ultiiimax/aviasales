# ADR 0075: Fixture parser CLI

Date: 2026-06-29

## Status

Accepted for the current implementation slice.

## Context

The monster plan includes a fixture parser command for sanitized browser snapshots. Flight Hunter
already had `flight-hunter-observe --fixture-html`, but that command also carries live and
persistence flags. Operators and tests benefit from a smaller fixture-only command that cannot
start Playwright or write to the database.

## Decision

Add `flight-hunter-parse-fixture` and `make parse-fixture`.

The CLI:

- accepts a positional HTML fixture path plus source and search intent fields;
- uses `PersonalObserverRunner.observe(..., fixture_html_path=...)`;
- never starts Playwright because fixture mode supplies the DOM snapshot;
- never persists results;
- prints sanitized JSON with offer summaries, parser warnings and raw price candidate count;
- does not print raw HTML or candidate context.

## Consequences

Positive:

- Parser fixtures can be checked through a dedicated command matching the plan.
- The command reuses the same Personal Browser Observer parser pipeline as API and worker paths.
- The operational command surface is discoverable through `make help`.

Tradeoff:

- Route/date/passenger fields are still required because parser confidence depends on matching the
  fixture to a concrete `SearchIntent`.

## Verification

- `uv run pytest tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py --quiet`
  -> 2 passed.
- `uv run ruff format --check src/flight_hunter/providers/personal_observer/parse_fixture_cli.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py`
  -> 3 files already formatted.
- `uv run ruff check src/flight_hunter/providers/personal_observer/parse_fixture_cli.py tests/unit/providers/personal_observer/test_parse_fixture_cli.py tests/unit/ops/test_makefile_commands.py`
  -> All checks passed.
- `uv run mypy` -> Success: no issues found in 89 source files.
- `uv run flight-hunter-parse-fixture tests/fixtures/browser/tutu/search_result_source_specific.html --source tutu --origin MOW --destination IST --depart 2026-09-10 --return-date 2026-09-20`
  -> `confidence=medium`, `provider_offer_id=tutu-realistic-1`, `amount_minor=1842000`.
