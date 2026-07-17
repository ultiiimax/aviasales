# Task 4 report: freeze typed routes in watches

Baseline: `main@b25a6aa7c3a8700cab78456e3d91b5b1b2ff2378`.

## Result

- Watch create resolves both route ends through the canonical async place directory and persists
  kind, ordered airport expansion, directory version and both membership versions.
- A route-changing PATCH resolves only the changed end(s), carries every changed route fact in
  the same optimistic-lock update and retains the unchanged endpoint snapshot. A legacy PATCH
  that changes a code without a kind resolves the new code instead of reusing the old kind.
- Non-route updates do not touch frozen route columns.
- `WatchRecord`, normal watch responses and privacy exports expose the durable route facts.
- Watch scans reconstruct the complete typed `SearchIntent`; the scan idempotency key now hashes
  route codes, kinds, ordered expansions and versions as well as the scheduled time.
- Additive migration `0030_typed_watch_places` backfills historical rows as explicit provider-city
  semantics: `city`, empty JSON arrays, `legacy-provider-city-v1`, and `NULL` membership versions.
  It removes temporary server defaults so migrated schema writes must provide route facts.

## TDD evidence

RED was observed before each production change:

- 2 failures: `WatchRecord` lacked all seven route-snapshot fields and `_intent_from_watch`
  restored `DME` as `city` while losing expansions and versions.
- 1 failure: a created `MOW(city) -> DME(airport)` watch restored destination kind as `city`.
- 1 failure: partial update `DME(airport) -> PAR(city)` retained the stale airport snapshot.
- 1 failure: a legacy code-only update from `MOW` to `WAW` returned 422 instead of resolving the
  new airport kind.
- 1 failure: identical schedule keys stayed equal after changing the frozen Moscow membership.
- 1 failure: the pre-v1 temporary database had none of the seven `0030` columns.

Each focused RED turned GREEN before the next behavior was implemented. The first combined
regression run then exposed three old watch API fixtures using catalog-unknown `NRT`; those
fixtures were changed to source-backed demo airport `CDG`, after which the same focused gate
passed.

## Fresh verification

All commands used `uv run --no-sync` because the running local worker held the generated worker
executable open; no dependency state was changed.

```text
pytest test_watch_api.py + test_watch_scans.py + pre-v1 upgrade + 4 affected nodes
  21 passed in 23.98s

ruff format --check <9 changed Python files>
  9 files already formatted

ruff check <9 changed Python files>
  All checks passed

mypy <5 changed source files>
  Success: no issues found in 5 source files

git diff --check
  exit 0

alembic heads
  0030_typed_watch_places (head)
```

The migration verification upgraded only pytest temporary databases. The active user database was
not opened or migrated. No live provider call was made.

## Compatibility note

Legacy service/repository constructors retain explicit `legacy-provider-city-v1` defaults for
historical fixtures and the offline seed path. Public watch create and every route-changing public
update always resolve complete current snapshots.
