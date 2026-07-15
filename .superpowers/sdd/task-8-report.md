# Task 8 report — resumable Aviasales search gateway

Status: implementation complete on 2026-07-15 and pending independent review.
Task 9 worker execution was not started.

## Scope delivered

- Added typed `ProviderLocation` values for explicit airport/city semantics.
- Added a single-attempt async gateway for exact-search start, one poll and
  calendar discovery. Every gateway operation authorizes provider policy and
  checks frozen capabilities before I/O.
- Required an Aviasales client configured with zero internal retries so one
  gateway attempt always means one transport attempt.
- Preserved the airport/city flags in both normal and reverse exact-search
  directions. Unsupported city semantics fail before transport; supported city
  capability is covered positively.
- Added private, repr-redacted continuation state. Public outcomes expose only
  confirmed evidence, the monotonic cursor and conservative
  `complete=false`; the provider contract has no proven terminal field.
- Mapped exact ticket rows to `ConfirmedOfferEvidence` with hash-only public
  provider identifiers, integer-minor-unit money, passenger basis, segments,
  seller, optional baggage and unknown protection.
- Mapped calendar rows to `DiscoverySignal`, not `FlightOffer`. Date-matrix and
  standalone calendar responses mark these rows as indicative and requiring
  live confirmation.
- Defaulted calendar calls to the verified `ru_RU` locale and filtered
  wrong-route/out-of-window rows before overlay.
- Rejected malformed typed parameters, schema violations and provider parsing
  failures with stable errors and without leaking provider-controlled text into
  tracebacks.

## TDD evidence

The required RED command was run before production changes:

```text
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py -q
28 failed, 30 passed
```

The failures demonstrated the missing provider location type, gateway,
one-poll client operation, evidence mappers, indicative matrix/API fields and
`ru_RU` locale. Smaller RED checks also preceded validation for malformed exact
and calendar inputs, date-cell/signal mismatches, standalone calendar evidence
markers and passenger basis, route/date filtering and traceback privacy.

Final GREEN evidence:

```text
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py -q
72 passed in 1.10s

uv run pytest tests/unit/api/test_aviasales_mobile_api.py -q
12 passed in 1.52s

uv run pytest tests/unit -q
943 passed, 8 warnings in 122.81s

uv run pytest tests/integration -q
4 passed in 3.85s

uv run mypy
Success: no issues found in 116 source files

uv run ruff format --check .
283 files already formatted

uv run ruff check .
All checks passed

git diff --check
passed
```

The eight full-unit warnings are unrelated to this slice: six aiosqlite
closed-event-loop teardown warnings in existing admin/Telegram tests and two
existing lxml `strip_cdata` deprecations.

## Provider-contract and privacy notes

`docs/provider-contracts/aviasales-search.md` records only sanitized facts from
the 2026-07-14 contract verification: schema-valid Suggest/start/poll/calendar
responses, the required `ru_RU` locale, and the absence of a proven poll
terminal field. It contains no price, search ID, result URL, signature, marker,
token, booking URL, cookie, PII or raw provider payload.

All automated provider verification in this slice is fixture/fake based. No
test makes a live Aviasales request. No persistence schema changed, so no
migration is required.

## Files changed

- `src/flight_hunter/providers/aviasales_search/{schemas,client,adapter,mapper,gateway}.py`
- `src/flight_hunter/providers/aviasales_search/__init__.py`
- `src/flight_hunter/application/date_matrix.py`
- `src/flight_hunter/api/app.py`
- focused provider, application and API unit tests
- `docs/provider-contracts/aviasales-search.md`
- `IMPLEMENTATION_STATUS.md`

Independent review must inspect the committed diff and rerun the gates before
Task 8 can be accepted.
