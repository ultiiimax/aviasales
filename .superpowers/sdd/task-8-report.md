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

## Independent review fix cycle

The independent review of `a00de1a..ca44fdb` found that the first Task 8
implementation had correct high-level slicing but incomplete trust-boundary and
evidence invariants. The concrete root causes were:

- a provider-returned result host was interpolated as a URL host without a
  contract suffix allowlist;
- transport/decoder errors were translated inside active handlers, retaining
  provider-controlled exception context, while opaque DTO dataclass reprs
  exposed private state;
- poll accepted passenger labeling separately from its continuation, and the
  continuation did not bind every expected exact-search fact;
- evidence UUIDs used a process-wide namespace instead of a caller operation
  namespace;
- proposal currency had an unsafe fallback, direction groups were not fully
  structural, and trip class/ASCII provider codes were too open;
- calendar/date-matrix validation covered cells but not the complete typed
  route, currency, passenger and trip-shape context;
- generic upstream HTTP failures did not expose body-free typed terminal versus
  retryable metadata.

All review regressions were added before production changes. The exact required
tests-only RED command was:

```text
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py tests/unit/api/test_aviasales_mobile_api.py -q
98 failed, 66 passed in 6.80s
```

An additional safe endpoint-name logging regression was independently driven
RED (`1 failed`) and GREEN (`1 passed in 0.13s`) after the main batch. No live
provider call was used in either cycle.

The fix adds one strict bare-host normalizer at all result-host boundaries,
repr-redacts client and gateway continuation DTOs, and raises stable transport
and decoder errors only after leaving their source handlers. Exact continuation
state now immutably binds route, dates, currency, passengers and a
caller-supplied operation UUID; poll derives all expectations from it. Exact
and calendar observation UUIDs are stable for the same operation/content and
distinct for a new operation, while public provider IDs remain stable hash-only
identities. Exact proposal money/direction validation and the closed trip-class
enum reject invented facts.

Calendar publication now uses one shared validator for route, inclusive dates,
currency, non-negative money and trip shape. Matrix overlay requires a frozen
typed discovery context, contradictory passenger inputs fail before provider
I/O, and every published indicative row/cell states provider, source, aware
observation time, passenger basis and live-confirmation requirement. Generic
non-special 4xx/5xx errors are body-free and carry status class plus retryability
without changing 401/403/429 behavior or one-call gateway accounting.

Final review-fix GREEN evidence:

```text
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py tests/unit/api/test_aviasales_mobile_api.py -q
165 passed in 4.53s

uv run pytest tests/unit -q
1024 passed, 23 warnings in 115.98s

uv run pytest tests/integration -q
4 passed in 4.10s

uv run mypy
Success: no issues found in 116 source files

uv run ruff format --check .
283 files already formatted

uv run ruff check .
All checks passed!

git diff --check
passed
```

The unit warnings are pre-existing teardown/deprecation warnings outside the
changed Task 8 flow. Review-fix verification is fixture/fake only: it contains
no live Aviasales request, secret, provider response body, raw result host,
booking URL or PII. No persistence schema changed, so no migration is required.
Task 9 remains unstarted, and Task 8 remains pending a fresh independent
re-review rather than being marked accepted by its implementer.
