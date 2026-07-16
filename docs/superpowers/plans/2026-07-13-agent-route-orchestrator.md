# Flight Hunter Agent Route Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Flight Hunter `1.1.0` as a local deterministic flight-search agent that turns free text or presets into an immutable visible plan, waits for a version-bound approval, durably searches Aviasales, composes and ranks only evidence-backed routes, and survives reloads, retries, cancellation, and process restarts.

**Architecture:** Keep the modular Python monolith and make the new flow a vertical application slice. Provider-neutral intent/evidence lives in `domain`; scope resolution, planning, lifecycle, execution, composition, analytics, and reporting live in `application`; Aviasales schemas and resumable start/poll work stay behind the provider adapter; SQLAlchemy repositories own immutable household-scoped state; FastAPI and the bundled web UI are thin delivery adapters. The model may parse typed intent and phrase deterministic facts, but never owns search breadth, provider calls, arithmetic, ranking, or booking data.

**Tech Stack:** Python 3.13, FastAPI/Pydantic, SQLAlchemy async, SQLite/Alembic, curl_cffi, pytest, Playwright, Ruff, mypy, uv, Docker Compose.

**Approved design:** `docs/superpowers/specs/2026-07-13-agent-route-orchestrator-design.md`

## Global Constraints

- A chat message or preset creates a plan and performs no provider network I/O.
- Execution requires bearer-session ownership, the exact revision ID/number/hash, a single-use approval, and an idempotency key.
- Clone/rerun requests also require an idempotency key and always create a fresh revision with refreshed volatile snapshots.
- Money is integer minor units plus ISO currency. Datetimes are timezone-aware.
- `DiscoverySignal` is indicative and can shortlist work; it cannot enter confirmed ranking.
- `ConfirmedOfferEvidence` is created only from ticket-bearing exact search.
- Aviasales native open-jaw/multi-city and connection protection remain `unknown` until a sanitized fixture, contract test, and live smoke prove otherwise.
- Hidden-city is isolated, one-way only, final plan leg only, non-watchable, and has no booking action. Unknown baggage makes it research-only.
- Quick mode defaults to 60 logical operations, split as at most 40 calendar and 20 exact, with a 10-minute deadline.
- Full mode defaults to at most 240 logical operations and a 30-minute deadline. The absolute configured ceiling is 1,000 logical operations.
- The provider cost model derives a worst-case HTTP-attempt cap. Start, every poll, and every retry reserve one HTTP attempt before I/O.
- CI uses sanitized fixtures only. Live provider checks are local summary-only checks.
- Every repository query and mutation includes household scope.
- Provider continuations, signatures, markers, signed URLs, cookies, and PII never reach logs, API responses, model context, or client assets.
- Existing migrations remain immutable. New revisions begin at `0022`.
- Each task is red-green-refactor, has focused verification, and ends in a small commit.

---

## Planned File Map

### New domain and application units

- `src/flight_hunter/domain/agent_search.py` — intent, plan, budget, lifecycle, capability, and risk value objects.
- `src/flight_hunter/domain/agent_evidence.py` — discovery, confirmed evidence, composed candidates, FX observations, history keys, and ranking inputs.
- `src/flight_hunter/application/agent_intent.py` — deterministic intent parser and typed optional model overlay.
- `src/flight_hunter/application/agent_scope.py` — finite scope expansion, anywhere rules, region taxonomy, and frozen catalog snapshots.
- `src/flight_hunter/application/agent_capabilities.py` — provider capability and HTTP cost snapshots.
- `src/flight_hunter/application/agent_planning.py` — plan builder, validation, estimation, and automatic finalization.
- `src/flight_hunter/application/agent_lifecycle.py` — immutable revisions, approvals, execute/clone/edit/cancel transitions.
- `src/flight_hunter/application/agent_operations.py` — operation materialization, fingerprints, leases, budgets, retry classification.
- `src/flight_hunter/application/agent_execution.py` — durable run state machine and coverage accounting.
- `src/flight_hunter/application/agent_composition.py` — split, self-transfer, open-jaw, multi-city, and bounded beam composition.
- `src/flight_hunter/application/agent_hidden_city.py` — isolated hidden-city research rules.
- `src/flight_hunter/application/agent_analysis.py` — history, anomaly, and currency comparability policies.
- `src/flight_hunter/application/agent_reporting.py` — deterministic rank snapshots and factual response DTOs.
- `src/flight_hunter/api/agent_schemas.py` and `src/flight_hunter/api/agent_routes.py` — thin HTTP contracts and router.
- `src/flight_hunter/persistence/agent_repositories.py` — focused plan/run/operation/evidence repositories.
- `src/flight_hunter/providers/aviasales_search/gateway.py` — provider-neutral resumable calendar/exact gateway.
- `src/flight_hunter/geo/countries.v1.json` — versioned ISO alpha-2 RU/EN country-name aliases.
- `src/flight_hunter/geo/regions.v1.json` — versioned RU/EN region taxonomy.

### New migrations

- `migrations/versions/0022_airport_commercial_provenance.py` — explicit scheduled-service provenance used for scope ordering.
- `migrations/versions/0023_agent_plan_lifecycle.py` — plans, immutable revisions, approvals, and runs.
- `migrations/versions/0024_agent_execution_ledger.py` — stages, operations, provider-attempt reservations, scope snapshots, evidence, candidates, and ranking snapshots.

### Existing integration units

- `src/flight_hunter/agent/chat.py` and `src/flight_hunter/agent/presets.py` — delegate both entry paths to the same typed plan builder.
- `src/flight_hunter/providers/aviasales_search/client.py`, `adapter.py`, `schemas.py`, and `mapper.py` — typed provider locations and resumable exact search.
- `src/flight_hunter/application/date_matrix.py` and `src/flight_hunter/api/app.py` — stop presenting calendar signals as confirmed offers.
- `src/flight_hunter/api/web.py` — plan card, approval, progress, cancel, expansion, and result sections.
- `src/flight_hunter/persistence/models.py` — Core metadata for all forward migrations.
- `src/flight_hunter/ops/worker.py` — `agent` worker role and operation processing.
- `src/flight_hunter/config.py`, `.env.example`, `compose.yaml` — bounded runtime configuration.
- `src/flight_hunter/ops/release_check.py`, `README.md`, `docs/ARCHITECTURE.md`, `docs/provider-contracts/aviasales-search.md`, `CHANGELOG.md`, and `IMPLEMENTATION_STATUS.md` — verified release truth.

---

### Task 1: Add Provider-Neutral Intent, Plan, and Evidence Contracts

**Files:**
- Create: `src/flight_hunter/domain/agent_search.py`
- Create: `src/flight_hunter/domain/agent_evidence.py`
- Create: `tests/unit/domain/test_agent_search.py`
- Create: `tests/unit/domain/test_agent_evidence.py`

**Interfaces:**
- Produces: `TravelIntent`, `LocationScope`, `TravelLeg`, `DateConstraint`, `PlanBudget`, `ProviderCapabilitySnapshot`.
- Produces: `DiscoverySignal`, `ConfirmedOfferEvidence`, `ComposedRouteCandidate`, `ProtectionStatus`, `ConfirmationState`.
- Consumes: existing `Money` and normalized `FlightSegmentSummary` only; imports no framework/provider packages.

- [ ] **Step 1: Write failing lifecycle and evidence-separation tests**

Add tests that instantiate every scope/trip/date/strategy enum, reject naive timestamps, reject a negative budget, and prove the ranker protocol cannot accept calendar evidence:

```python
def test_discovery_signal_is_not_confirmed_rank_input() -> None:
    signal = DiscoverySignal(
        id=uuid4(),
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 10),
        return_date=None,
        observed_amount=Money(1_230_000, "RUB"),
        observed_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
        source_kind=DiscoverySource.CALENDAR,
    )

    with pytest.raises(TypeError, match="confirmed evidence required"):
        require_confirmed_rank_input(signal)
```

Add a second test proving a complete `TravelIntent` preserves ordered multi-city legs and complete passenger mix.

- [ ] **Step 2: Run the new tests and confirm imports fail**

```powershell
uv run pytest tests/unit/domain/test_agent_search.py tests/unit/domain/test_agent_evidence.py -q
```

Expected: collection fails because both domain modules are absent.

- [ ] **Step 3: Implement frozen domain types and invariants**

Use closed enums and frozen dataclasses. The evidence split must be structural, not a flag on one shared offer:

```python
class LocationScopeKind(StrEnum):
    AIRPORT = "airport"
    CITY = "city"
    COUNTRY = "country"
    REGION = "region"
    ANYWHERE = "anywhere"


class ConfirmationState(StrEnum):
    INDICATIVE = "indicative"
    CONFIRMED = "confirmed"


@dataclass(frozen=True, slots=True)
class PlanBudget:
    logical_operations: int
    http_attempts: int
    deadline_seconds: int

    def __post_init__(self) -> None:
        if min(self.logical_operations, self.http_attempts, self.deadline_seconds) <= 0:
            raise ValueError("plan budgets must be positive")


def require_confirmed_rank_input(
    value: ConfirmedOfferEvidence | ComposedRouteCandidate,
) -> ConfirmedOfferEvidence | ComposedRouteCandidate:
    if not isinstance(value, (ConfirmedOfferEvidence, ComposedRouteCandidate)):
        raise TypeError("confirmed evidence required")
    return value
```

Every evidence record validates aware `observed_at`, a passenger count greater than zero, ISO currency through `Money`, and immutable ordered segment IDs.

- [ ] **Step 4: Verify domain contracts**

```powershell
uv run pytest tests/unit/domain/test_agent_search.py tests/unit/domain/test_agent_evidence.py -q
uv run mypy src/flight_hunter/domain/agent_search.py src/flight_hunter/domain/agent_evidence.py
```

Expected: both commands pass.

- [ ] **Step 5: Commit**

```powershell
git add src/flight_hunter/domain/agent_search.py src/flight_hunter/domain/agent_evidence.py tests/unit/domain/test_agent_search.py tests/unit/domain/test_agent_evidence.py
git commit -m "feat: add agent search domain contracts"
```

---

### Task 2: Freeze Generic Geographic Scopes with Commercial Provenance

**Files:**
- Create: `migrations/versions/0022_airport_commercial_provenance.py`
- Create: `src/flight_hunter/application/agent_scope.py`
- Create: `src/flight_hunter/geo/countries.v1.json`
- Create: `src/flight_hunter/geo/regions.v1.json`
- Modify: `src/flight_hunter/geo/airports.py`
- Modify: `src/flight_hunter/geo/ourairports_importer.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Modify: `src/flight_hunter/persistence/repositories.py`
- Modify: `pyproject.toml`
- Modify: `tests/unit/geo/test_ourairports_importer.py`
- Modify: `tests/unit/persistence/test_airport_reference_repository.py`
- Create: `tests/unit/application/test_agent_scope.py`
- Modify: `tests/unit/persistence/test_alembic_upgrade.py`

**Interfaces:**
- Produces: `ScopeResolver.resolve_finite(scope, nearby_radius_km) -> FrozenAirportScope`.
- Produces: `AnywhereDiscoveryRule` without inventing destinations before provider discovery.
- Consumes: `AirportReferenceRepository.catalog_snapshot()` and versioned `regions.v1.json`.

- [ ] **Step 1: Write failing migration, importer, and resolver tests**

Cover:

- `scheduled_service=yes` persists with provenance `ourairports.scheduled_service`;
- closed, small, missing-IATA, and no-scheduled-service rows do not enter searchable scope;
- country `FR` expands deterministically to all searchable French airports;
- a region alias resolves through JSON, not model knowledge;
- `Франция` and `France` resolve to `FR` through versioned country data;
- quick ordering is deterministic and full scope includes the whole frozen catalog selection;
- catalog checksum stays in the frozen result after a later import.

The core assertion is:

```python
resolved = await resolver.resolve_finite(
    LocationScope(LocationScopeKind.COUNTRY, "FR"),
    coverage=CoverageMode.FULL,
)

assert resolved.airport_codes == ("CDG", "LYS", "NCE", "ORY")
assert resolved.catalog_checksum == original_checksum
assert resolved.commercial_provenance == "ourairports.scheduled_service"
```

- [ ] **Step 2: Run focused tests and confirm the missing schema/interfaces**

```powershell
uv run pytest tests/unit/geo/test_ourairports_importer.py tests/unit/persistence/test_airport_reference_repository.py tests/unit/application/test_agent_scope.py tests/unit/persistence/test_alembic_upgrade.py -q
```

Expected: failures for missing columns, taxonomy package data, and `ScopeResolver`.

- [ ] **Step 3: Add forward migration and Core metadata**

Add non-null columns with safe legacy defaults, then remove server defaults after backfill where SQLite permits:

```python
def upgrade() -> None:
    with op.batch_alter_table("airports") as batch:
        batch.add_column(
            sa.Column("scheduled_service", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(
            sa.Column(
                "commercial_provenance",
                sa.String(length=120),
                nullable=False,
                server_default="legacy_import_filter",
            )
        )
```

Mirror both columns in `airports_table` and in repository mapping. Existing v1 rows remain searchable with explicit legacy provenance; every new OurAirports import writes the exact source field.

- [ ] **Step 4: Add taxonomy and deterministic catalog hashing**

Package `regions.v1.json` with a top-level version and mappings such as:

```json
{
  "version": "regions-v1-2026-07-13",
  "regions": {
    "western_europe": {
      "country_codes": ["AT", "BE", "CH", "DE", "FR", "LI", "LU", "MC", "NL"],
      "aliases": ["western europe", "западная европа"]
    }
  }
}
```

Package `countries.v1.json` with every ISO 3166 alpha-2 code used by the
catalog, deterministic RU/EN names and aliases, plus the exact upstream
ISO/Unicode CLDR source version and import checksum. Country names are resolved
from this file; unknown or ambiguous text returns clarification choices instead
of model-supplied geography. City text resolves against normalized local
municipality/name/keyword fields and likewise asks for a choice when ambiguous.

Hash the canonical sorted airport fields used by search:

```python
payload = [
    {
        "iata": airport.iata_code,
        "country": airport.country_code,
        "type": airport.airport_type.value,
        "scheduled_service": airport.scheduled_service,
        "active": airport.active,
    }
    for airport in sorted(airports, key=lambda item: item.iata_code)
]
checksum = sha256(
    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
```

- [ ] **Step 5: Implement finite and anywhere scope contracts**

`ScopeResolver` freezes airport codes for airport/city/country/region. For `ANYWHERE` it returns:

```python
AnywhereDiscoveryRule(
    origin_airports=frozen_origins.airport_codes,
    date_start=date_start,
    date_end=date_end,
    allowed_country_codes=allowed_country_codes,
    excluded_country_codes=excluded_country_codes,
    discovery_source_ids=("aviasales_calendar", "aviasales_hot_offers"),
    max_destination_seeds=max_destination_seeds,
    exact_verification_limit=exact_verification_limit,
    catalog_checksum=frozen_origins.catalog_checksum,
    taxonomy_version=taxonomy.version,
)
```

No anywhere destination code is created in this step.

- [ ] **Step 6: Verify scope and migration behavior**

```powershell
uv run pytest tests/unit/geo/test_ourairports_importer.py tests/unit/persistence/test_airport_reference_repository.py tests/unit/application/test_agent_scope.py tests/unit/persistence/test_alembic_upgrade.py -q
uv run mypy src/flight_hunter/geo src/flight_hunter/application/agent_scope.py
```

Expected: all focused checks pass.

- [ ] **Step 7: Commit**

```powershell
git add migrations/versions/0022_airport_commercial_provenance.py src/flight_hunter/application/agent_scope.py src/flight_hunter/geo src/flight_hunter/persistence/models.py src/flight_hunter/persistence/repositories.py pyproject.toml tests/unit/geo/test_ourairports_importer.py tests/unit/persistence/test_airport_reference_repository.py tests/unit/application/test_agent_scope.py tests/unit/persistence/test_alembic_upgrade.py
git commit -m "feat: resolve frozen geographic scopes"
```

---

### Task 3: Build Typed Intent Parsing, Capability Snapshots, and Plan Estimation

**Files:**
- Create: `src/flight_hunter/application/agent_intent.py`
- Create: `src/flight_hunter/application/agent_capabilities.py`
- Create: `src/flight_hunter/application/agent_planning.py`
- Modify: `src/flight_hunter/domain/policy.py`
- Modify: `src/flight_hunter/config.py`
- Modify: `.env.example`
- Create: `tests/unit/application/test_agent_intent.py`
- Create: `tests/unit/application/test_agent_capabilities.py`
- Create: `tests/unit/application/test_agent_planning.py`
- Modify: `tests/unit/application/test_provider_registry.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/unit/test_env_example.py`

**Interfaces:**
- Produces: `IntentParser.parse(text, preset, selections) -> ParsedIntent`.
- Produces: `ProviderCapabilityRegistry.snapshot() -> ProviderCapabilitySnapshot`.
- Produces: `AgentPlanBuilder.build(parsed, coverage) -> ProposedPlanRevision`.
- Produces: `PlanEstimator.estimate(surface, cost_model) -> PlanEstimate`.

- [ ] **Step 1: Write failing parser and budget-boundary tests**

Cover:

- `СПб → Франция` without a date returns `date_constraint` clarification plus rolling-90-days action;
- airport/city/country/region/anywhere and RU/EN aliases;
- exact, ±3, range, rolling 90 days;
- one-way, round-trip, open-jaw, and ordered multi-city;
- all seven existing preset IDs produce the same `TravelIntent` type;
- native multi-city and connection protection are `UNKNOWN`;
- the legacy provider-policy summary no longer advertises native multi-city support;
- quick estimate at 40 calendar + 20 exact succeeds;
- 61 quick logical operations fails;
- full plan over 240 requires a new revision/budget, and over 1,000 always fails;
- HTTP attempt estimate includes every start/poll retry.

Use this cost assertion:

```python
cost = ProviderHttpCostModel(
    version="aviasales-v1",
    start_attempts=3,
    poll_rounds=8,
    attempts_per_poll=3,
)

assert cost.worst_case_exact_http_attempts == 27
assert estimator.estimate_http_attempts(exact_searches=2, calendar_searches=1) == 57
```

- [ ] **Step 2: Run focused tests and confirm the modules are absent**

```powershell
uv run pytest tests/unit/application/test_agent_intent.py tests/unit/application/test_agent_capabilities.py tests/unit/application/test_agent_planning.py tests/unit/application/test_provider_registry.py tests/unit/test_config.py tests/unit/test_env_example.py -q
```

Expected: collection or assertion failures for new contracts and settings.

- [ ] **Step 3: Add bounded settings**

Add validated settings and env keys:

```text
AGENT_PLAN_TTL_SECONDS=86400
AGENT_QUICK_LOGICAL_LIMIT=60
AGENT_QUICK_CALENDAR_LIMIT=40
AGENT_QUICK_EXACT_LIMIT=20
AGENT_FULL_LOGICAL_LIMIT=240
AGENT_ABSOLUTE_LOGICAL_LIMIT=1000
AGENT_QUICK_DEADLINE_SECONDS=600
AGENT_FULL_DEADLINE_SECONDS=1800
AGENT_OPERATION_LEASE_SECONDS=120
AGENT_MAX_LAYOVER_SECONDS=64800
AGENT_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=5
AGENT_PROVIDER_CIRCUIT_COOLDOWN_SECONDS=120
```

Reject non-positive limits and any configured default above the absolute ceiling in `AppSettings.from_env`.

- [ ] **Step 4: Implement deterministic parsing and typed optional overlay**

The deterministic parser owns aliases and safe fallback. The optional model may return only a validated overlay:

```python
class IntentOverlay(BaseModel):
    origin_text: str | None = None
    destination_text: str | None = None
    trip_shape: TripShape | None = None
    date_mode: DateMode | None = None
    requested_strategy_ids: tuple[RouteStrategy, ...] = ()


def merge_overlay(base: ParsedIntent, overlay: IntentOverlay) -> ParsedIntent:
    return replace(
        base,
        trip_shape=overlay.trip_shape or base.trip_shape,
        date_mode=overlay.date_mode or base.date_mode,
        requested_strategies=overlay.requested_strategy_ids or base.requested_strategies,
    )
```

The overlay cannot supply airport facts, prices, capabilities, budgets, or route candidates.
`DateMode.ROLLING_90_DAYS` has the stable serialized value
`rolling_90_days` and computes its end date from the injected plan-builder
clock.

- [ ] **Step 5: Implement snapshot and estimator**

Publish Aviasales capabilities as tri-state values:

```python
ProviderCapabilitySnapshot(
    provider_id="aviasales_search",
    version="mobile-contract-2026-07-13",
    one_way=CapabilityState.SUPPORTED,
    round_trip=CapabilityState.SUPPORTED,
    native_open_jaw=CapabilityState.UNKNOWN,
    native_multi_city=CapabilityState.UNKNOWN,
    explicit_connection_protection=CapabilityState.UNKNOWN,
    airport_location_semantics=CapabilityState.SUPPORTED,
    city_location_semantics=CapabilityState.UNKNOWN,
    cost_model=cost_model,
)
```

`AgentPlanBuilder` automatically moves a complete, frozen, validated, estimated draft to `AWAITING_APPROVAL`. An incomplete result stays `DRAFT` and returns structured clarification fields.

Change the old boolean `ProviderPolicy.aviasales_search_live().supports_multi_city`
to `False` so legacy provider-status output cannot contradict the verified
contract. The orchestrator uses the richer tri-state snapshot as the
authoritative planning input.

- [ ] **Step 6: Verify planning**

```powershell
uv run pytest tests/unit/application/test_agent_intent.py tests/unit/application/test_agent_capabilities.py tests/unit/application/test_agent_planning.py tests/unit/application/test_provider_registry.py tests/unit/test_config.py tests/unit/test_env_example.py -q
uv run mypy src/flight_hunter/application/agent_intent.py src/flight_hunter/application/agent_capabilities.py src/flight_hunter/application/agent_planning.py
```

Expected: all focused tests and types pass.

- [ ] **Step 7: Commit**

```powershell
git add src/flight_hunter/application/agent_intent.py src/flight_hunter/application/agent_capabilities.py src/flight_hunter/application/agent_planning.py src/flight_hunter/domain/policy.py src/flight_hunter/config.py .env.example tests/unit/application/test_agent_intent.py tests/unit/application/test_agent_capabilities.py tests/unit/application/test_agent_planning.py tests/unit/application/test_provider_registry.py tests/unit/test_config.py tests/unit/test_env_example.py
git commit -m "feat: build bounded agent search plans"
```

---

### Task 4: Persist Immutable Plans, Approvals, and Runs

**Files:**
- Create: `migrations/versions/0023_agent_plan_lifecycle.py`
- Create: `src/flight_hunter/persistence/agent_repositories.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Create: `tests/unit/persistence/test_agent_plan_repository.py`
- Create: `tests/unit/persistence/test_agent_run_repository.py`
- Modify: `tests/unit/persistence/test_alembic_upgrade.py`
- Modify: `tests/integration/test_upgrade_from_pre_v1.py`

**Interfaces:**
- Produces: household-scoped repositories for plan aggregate, revision, approval, and run.
- Enforces: immutable revision content, one active run per plan, one approval per run, execution and clone idempotency.

- [ ] **Step 1: Write failing persistence and upgrade tests**

Prove:

- household A cannot read/edit/execute household B's plan;
- revision numbers are monotonic and old content is unchanged;
- concurrent successor creation has one winner;
- `(household_id, execute_idempotency_key)` returns the original run;
- `(household_id, clone_idempotency_key)` returns the original cloned revision;
- one plan cannot have two active runs;
- a consumed approval cannot bind a second run;
- latest run ordering is `(created_at, id)`;
- upgrading a populated revision-0021 database preserves all existing rows.

- [ ] **Step 2: Run persistence tests and confirm missing tables**

```powershell
uv run pytest tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
```

Expected: failures because migration `0023` and repositories do not exist.

- [ ] **Step 3: Create lifecycle tables and constraints**

The migration creates:

- `agent_search_plans`;
- `agent_search_plan_revisions`;
- `agent_plan_execution_approvals`;
- `agent_plan_runs`.

Critical constraints include:

```python
sa.UniqueConstraint("plan_id", "revision_number", name="uq_agent_plan_revision_number")
sa.UniqueConstraint("plan_id", "content_hash", name="uq_agent_plan_revision_hash")
sa.UniqueConstraint(
    "household_id",
    "execute_idempotency_key",
    name="uq_agent_run_execute_idempotency",
)
sa.UniqueConstraint("run_id", name="uq_agent_approval_run")
```

Add a nullable `clone_idempotency_key` to revisions and a unique partial index on `(household_id, clone_idempotency_key)` when non-null. Add a unique partial index on `plan_id` for statuses `queued`, `running`, and `cancel_requested`.

Store canonical plan JSON, scope JSON, capability JSON, cost model JSON, parser/planner versions, estimates, hashes, expiry, and supersession timestamps. Do not store raw prompt text.

- [ ] **Step 4: Implement atomic repositories**

Use compare-and-swap updates:

```python
result = await self._session.execute(
    update(agent_search_plan_revisions_table)
    .where(agent_search_plan_revisions_table.c.id == str(source_revision_id))
    .where(agent_search_plan_revisions_table.c.household_id == str(household_id))
    .where(agent_search_plan_revisions_table.c.state.in_(("draft", "awaiting_approval")))
    .where(agent_search_plan_revisions_table.c.superseded_at.is_(None))
    .values(state="superseded", superseded_at=now)
)
if cast(CursorResult[Any], result).rowcount != 1:
    raise AgentPlanConflict("agent_plan_stale")
```

Execute writes approval, run, and consumed revision within one transaction. Repositories do not commit internally; the lifecycle service owns the transaction boundary.

- [ ] **Step 5: Verify migrations and repositories**

```powershell
uv run pytest tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
uv run mypy src/flight_hunter/persistence/agent_repositories.py
```

Expected: all checks pass and existing v1 data remains intact.

- [ ] **Step 6: Commit**

```powershell
git add migrations/versions/0023_agent_plan_lifecycle.py src/flight_hunter/persistence/models.py src/flight_hunter/persistence/agent_repositories.py tests/unit/persistence/test_agent_plan_repository.py tests/unit/persistence/test_agent_run_repository.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py
git commit -m "feat: persist agent plan lifecycle"
```

---

### Task 5: Expose Approval-Gated Plan Lifecycle API

**Files:**
- Create: `src/flight_hunter/application/agent_lifecycle.py`
- Create: `src/flight_hunter/api/agent_schemas.py`
- Create: `src/flight_hunter/api/agent_routes.py`
- Modify: `src/flight_hunter/api/app.py`
- Create: `tests/unit/application/test_agent_lifecycle.py`
- Create: `tests/unit/api/test_agent_plan_api.py`
- Modify: `tests/unit/api/conftest.py`

**Interfaces:**
- Produces all `/api/v1/agent/search-plans` endpoints from the approved design.
- Requires bearer session for every persisted plan/run endpoint.
- Returns stable machine-readable agent error codes.

The router surface is exactly:

```text
POST   /api/v1/agent/search-plans
GET    /api/v1/agent/search-plans/{plan_id}
PATCH  /api/v1/agent/search-plans/{plan_id}
POST   /api/v1/agent/search-plans/{plan_id}/revisions
POST   /api/v1/agent/search-plans/{plan_id}/execute
GET    /api/v1/agent/search-plans/{plan_id}/runs
GET    /api/v1/agent/search-plans/{plan_id}/runs/{run_id}
POST   /api/v1/agent/search-plans/{plan_id}/runs/{run_id}/cancel
GET    /api/v1/agent/search-plans/{plan_id}/runs/latest
GET    /api/v1/agent/search-plans/{plan_id}/runs/{run_id}/results
```

- [ ] **Step 1: Write failing lifecycle and API tests**

Cover:

- POST complete input returns `awaiting_approval` and an executable plan card;
- POST missing date returns `draft`, clarification fields, and rolling-90-day action;
- PATCH supersedes and creates revision `N+1`;
- clone works for consumed/expired/superseded source and is idempotent;
- execute rejects stale version/hash, missing approval data, expired/consumed revisions, cross-household access, and missing hidden-city warning;
- execute retry with same idempotency key returns the original run;
- cancel targets the explicit run ID;
- latest and list endpoints are deterministic;
- a counting provider gateway records zero calls across every plan/edit/clone operation.

Use a real auth session fixture, not legacy household headers, for execute:

```python
response = client.post(
    f"/api/v1/agent/search-plans/{plan_id}/execute",
    headers={
        "Authorization": f"Bearer {session_token}",
        "Idempotency-Key": "execute-plan-001",
    },
    json={
        "revision_id": revision_id,
        "expected_revision": 1,
        "content_hash": content_hash,
        "hidden_city_warning_version": None,
    },
)
assert response.status_code == 202
assert provider.calls == 0
```

- [ ] **Step 2: Run tests and confirm routes/services are absent**

```powershell
uv run pytest tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py -q
```

Expected: import failures and HTTP 404 responses.

- [ ] **Step 3: Implement lifecycle transitions**

Expose typed `create_plan`, `edit_plan`, `clone_revision`, `execute_plan`, and
`cancel_run` methods. The execute transaction follows this concrete order:

```python
async def execute_plan(self, command: ExecuteAgentPlan) -> RunView:
    revision = await self._plans.get_revision_for_update(
        command.household_id,
        command.plan_id,
        command.revision_id,
    )
    self._approval_policy.validate(revision, command)
    run = await self._plans.consume_revision_and_create_run(
        command=command,
        revision=revision,
        approved_at=self._clock(),
    )
    await self._session.commit()
    return run_view(run)
```

The service expires stale awaiting revisions before transitions, recalculates
clone snapshots, and commits each transition atomically.

- [ ] **Step 4: Add thin schemas and router**

`agent_schemas.py` contains request/response models only. `agent_routes.py` maps typed service errors:

```python
ERROR_STATUS = {
    "agent_plan_incomplete": 409,
    "agent_plan_stale": 409,
    "agent_plan_consumed": 409,
    "agent_plan_expired": 410,
    "agent_plan_budget_too_large": 422,
    "agent_plan_approval_required": 403,
    "agent_hidden_city_ack_required": 403,
    "agent_run_already_active": 409,
}
```

Register the router from `create_app` with the existing session factory and bearer authentication dependency. API DTOs exclude private continuation, provider refs, and canonical raw plan internals.

- [ ] **Step 5: Verify API lifecycle and OpenAPI**

```powershell
uv run pytest tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_auth_api.py -q
uv run mypy src/flight_hunter/application/agent_lifecycle.py src/flight_hunter/api/agent_schemas.py src/flight_hunter/api/agent_routes.py src/flight_hunter/api/app.py
```

Expected: all checks pass; OpenAPI contains all plan/run paths.

- [ ] **Step 6: Commit**

```powershell
git add src/flight_hunter/application/agent_lifecycle.py src/flight_hunter/api/agent_schemas.py src/flight_hunter/api/agent_routes.py src/flight_hunter/api/app.py tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/conftest.py
git commit -m "feat: expose agent plan lifecycle"
```

---

### Task 6: Make Free Text, Presets, and the Web Plan Card Use One Builder

**Files:**
- Modify: `src/flight_hunter/agent/chat.py`
- Modify: `src/flight_hunter/agent/presets.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `src/flight_hunter/api/web.py`
- Modify: `tests/unit/agent/test_chat.py`
- Modify: `tests/unit/agent/test_presets.py`
- Modify: `tests/unit/api/test_agent_api.py`
- Modify: `tests/unit/api/test_web_ui.py`

**Interfaces:**
- Preserves existing preset IDs and compatibility endpoints.
- Changes `/api/v1/agent/chat/turn` to return a proposed plan reference instead of live results.
- Adds plan-card UI actions without calling the provider before approval.

- [ ] **Step 1: Write failing compatibility and UI tests**

Assert:

- all seven presets delegate to `AgentPlanBuilder` and return the same revision schema;
- free text `Найди самый дешёвый вариант из СПб во Францию` returns missing-date clarification;
- selecting rolling 90 days returns a plan card with estimate, source, deadline, strategies, and approval button;
- only the explicit execute button calls the execute endpoint;
- quick-to-full uses clone endpoint and a fresh idempotency key;
- reload fetches the current plan/run;
- HTML contains accessible plan status, progress, cancel, risky-results, and partial-error regions.

- [ ] **Step 2: Run focused tests and confirm old one-shot behavior**

```powershell
uv run pytest tests/unit/agent/test_chat.py tests/unit/agent/test_presets.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
```

Expected: new assertions fail because chat currently runs `DemoSearchService` and the UI has no durable plan card.

- [ ] **Step 3: Delegate both entry paths**

Keep preset metadata but translate it into typed edits:

```python
PRESET_EDITS: dict[str, PlanEdits] = {
    "buy_timing": PlanEdits(analysis_modes=(AnalysisMode.BUY_TIMING,)),
    "flexible_dates": PlanEdits(default_flex_days=3),
    "nearby_airports": PlanEdits(nearby_radius_km=150),
    "hidden_city": PlanEdits(strategies=(RouteStrategy.HIDDEN_CITY,)),
    "split_ticket": PlanEdits(strategies=(RouteStrategy.SPLIT_TICKET,)),
    "error_fare_sources": PlanEdits(analysis_modes=(AnalysisMode.ERROR_FARE,)),
    "geo_currency": PlanEdits(analysis_modes=(AnalysisMode.CURRENCY_COMPARE,)),
}
```

Chat and preset endpoints call the same create-plan use case. Delete their live search/date-matrix execution branches.

- [ ] **Step 4: Render the durable plan card**

The card displays revision, frozen scope, date mode, passengers, quick/full coverage, strategies, hidden-city state, logical/HTTP estimates, RPM, deadline, source, and expiry. It posts exact revision/hash/version on execute and polls `runs/{run_id}` with backoff while queued/running.

Render status text for `partial`, `failed`, `cancelled`, and typed provider errors. Never render unknown baggage, protection, transfer cost, or visa state as false/zero.

- [ ] **Step 5: Verify compatibility and UI contract**

```powershell
uv run pytest tests/unit/agent/test_chat.py tests/unit/agent/test_presets.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py -q
uv run mypy src/flight_hunter/agent src/flight_hunter/api/app.py src/flight_hunter/api/web.py
```

Expected: all focused checks pass and no provider call occurs before execute.

- [ ] **Step 6: Commit**

```powershell
git add src/flight_hunter/agent/chat.py src/flight_hunter/agent/presets.py src/flight_hunter/api/app.py src/flight_hunter/api/web.py tests/unit/agent/test_chat.py tests/unit/agent/test_presets.py tests/unit/api/test_agent_api.py tests/unit/api/test_web_ui.py
git commit -m "feat: render approval gated agent plans"
```

---

### Task 7: Add the Durable Operation and Evidence Ledger

**Files:**
- Create: `migrations/versions/0024_agent_execution_ledger.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Modify: `src/flight_hunter/persistence/agent_repositories.py`
- Create: `src/flight_hunter/application/agent_operations.py`
- Create: `tests/unit/persistence/test_agent_operation_repository.py`
- Create: `tests/unit/persistence/test_agent_evidence_repository.py`
- Create: `tests/unit/application/test_agent_operations.py`
- Modify: `tests/unit/persistence/test_alembic_upgrade.py`
- Modify: `tests/integration/test_upgrade_from_pre_v1.py`

**Interfaces:**
- Produces: stages, operations, provider-attempt reservations, scope snapshots, discovery signals, confirmed evidence, composed candidates, and ranking snapshots.
- Enforces: unique operation fingerprint, lease recovery, attempt reservation before I/O, append-only evidence, and delivery-safe records.

- [ ] **Step 1: Write failing ledger, concurrency, and secrecy tests**

Cover:

- two concurrent claimers cannot lease the same operation;
- expired lease returns to retryable state;
- identical `(run_id, fingerprint)` materializes once;
- HTTP attempt reservation is atomic and refuses an exhausted budget;
- the rolling provider RPM check counts every actual start/poll/retry across runs;
- start and all poll rows share one logical-operation fingerprint so poll rounds do not inflate the logical budget;
- repeated transient failures open one persistent provider circuit and allow only one half-open probe after cooldown;
- a crash after reservation leaves the unit consumed;
- candidate retry deduplicates on deterministic fingerprint;
- discovery ID cannot be inserted into a ranking snapshot;
- evidence append never updates an old observation;
- household A cannot read B's operation or evidence;
- public records contain no `private_continuation_json` field.

- [ ] **Step 2: Run tests and confirm missing migration/repository behavior**

```powershell
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
```

Expected: failures for missing tables and interfaces.

- [ ] **Step 3: Add execution tables and indexes**

Create:

- `agent_plan_stages`;
- `agent_run_operations`;
- `agent_provider_rate_locks`;
- `agent_provider_http_attempts`;
- `agent_provider_circuit_state`;
- `agent_run_scope_snapshots`;
- `agent_discovery_signals`;
- `agent_confirmed_offer_evidence`;
- `agent_composed_route_candidates`;
- `agent_ranking_snapshots`.

The operation uniqueness, logical workflow, and lease index are:

```python
sa.UniqueConstraint(
    "run_id",
    "operation_fingerprint",
    name="uq_agent_run_operation_fingerprint",
)
op.create_index(
    "uq_agent_run_logical_root",
    "agent_run_operations",
    ["run_id", "logical_operation_fingerprint"],
    unique=True,
    sqlite_where=sa.text("consumes_logical_unit = 1"),
)
op.create_index(
    "ix_agent_operation_claim",
    "agent_run_operations",
    ["status", "next_retry_at", "lease_expires_at", "created_at"],
)
```

Use JSON text only for canonical sanitized inputs/results. Keep `private_continuation_json` server-side. Evidence tables store source, aware `observed_at`, confirmation/freshness, passenger basis, and deterministic fingerprints. `agent_provider_http_attempts` is append-only, contains no request payload, and is indexed by `(provider_id, reserved_at)` for the rolling RPM gate. `agent_provider_rate_locks` has one row per provider and serializes the sliding-window count/insert transaction across local workers. `agent_provider_circuit_state` stores consecutive transient failures, open/cooldown timestamps, and a single half-open probe lease.

- [ ] **Step 4: Implement lease, retry, and attempt reservation**

Use a typed result so RPM wait and exhausted approved budget cannot collapse
into the same failure:

```python
class AttemptReservationStatus(StrEnum):
    RESERVED = "reserved"
    RATE_LIMITED = "rate_limited"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class AttemptReservationResult:
    status: AttemptReservationStatus
    retry_at: datetime | None = None
```

```python
async def reserve_http_attempt(
    self,
    household_id: UUID,
    run_id: UUID,
    operation_id: UUID,
    provider_id: str,
    provider_rpm: int,
    now: datetime,
) -> AttemptReservationResult:
    await self._session.execute(
        insert(agent_provider_rate_locks_table)
        .values(provider_id=provider_id, touched_at=now)
        .prefix_with("OR IGNORE")
    )
    await self._session.execute(
        update(agent_provider_rate_locks_table)
        .where(agent_provider_rate_locks_table.c.provider_id == provider_id)
        .values(touched_at=now)
    )
    recent_rows = (
        await self._session.execute(
            select(agent_provider_http_attempts_table.c.reserved_at)
            .select_from(agent_provider_http_attempts_table)
            .where(agent_provider_http_attempts_table.c.provider_id == provider_id)
            .where(
                agent_provider_http_attempts_table.c.reserved_at
                >= now - timedelta(minutes=1)
            )
            .order_by(agent_provider_http_attempts_table.c.reserved_at)
        )
    ).scalars().all()
    if len(recent_rows) >= provider_rpm:
        return AttemptReservationResult(
            status=AttemptReservationStatus.RATE_LIMITED,
            retry_at=recent_rows[0] + timedelta(minutes=1)
        )
    result = await self._session.execute(
        update(agent_plan_runs_table)
        .where(agent_plan_runs_table.c.id == str(run_id))
        .where(agent_plan_runs_table.c.household_id == str(household_id))
        .where(
            agent_plan_runs_table.c.http_attempts_consumed
            < agent_plan_runs_table.c.http_attempt_budget
        )
        .values(
            http_attempts_consumed=agent_plan_runs_table.c.http_attempts_consumed + 1,
            updated_at=now,
        )
    )
    if cast(CursorResult[Any], result).rowcount != 1:
        return AttemptReservationResult(
            status=AttemptReservationStatus.BUDGET_EXHAUSTED
        )
    await self._session.execute(
        insert(agent_provider_http_attempts_table).values(
            id=str(uuid4()),
            provider_id=provider_id,
            run_id=str(run_id),
            operation_id=str(operation_id),
            reserved_at=now,
        )
    )
    await self._session.execute(
        update(agent_run_operations_table)
        .where(agent_run_operations_table.c.id == str(operation_id))
        .values(http_attempts_consumed=agent_run_operations_table.c.http_attempts_consumed + 1)
    )
    return AttemptReservationResult(status=AttemptReservationStatus.RESERVED)
```

The lock-row update occurs before the sliding-window read, and all statements
execute in one SQLite write transaction. `OperationScheduler`
creates a stable row fingerprint from operation kind plus canonical immutable
input and a separate logical-workflow fingerprint shared by exact start/poll
rows. Only the root consumes one logical unit. Retry policy treats
auth/403/schema as terminal, 429 according to `Retry-After`, and network/5xx as
bounded retry. A persistent `AgentProviderCircuitBreaker` opens after the
configured transient-failure threshold; while open it permits no new provider
I/O, and after cooldown a compare-and-swap probe lease admits one attempt.
Success closes and resets it. Maintenance deletes old provider-attempt rows
only after they fall outside every configured RPM/audit window.

- [ ] **Step 5: Verify ledger and migration upgrade**

```powershell
uv run pytest tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py -q
uv run mypy src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py
```

Expected: all focused checks pass.

- [ ] **Step 6: Commit**

```powershell
git add migrations/versions/0024_agent_execution_ledger.py src/flight_hunter/persistence/models.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/application/agent_operations.py tests/unit/persistence/test_agent_operation_repository.py tests/unit/persistence/test_agent_evidence_repository.py tests/unit/application/test_agent_operations.py tests/unit/persistence/test_alembic_upgrade.py tests/integration/test_upgrade_from_pre_v1.py
git commit -m "feat: add agent execution ledger"
```

---

### Task 8: Make Aviasales Exact Search Resumable and Calendar Data Indicative

**Files:**
- Create: `src/flight_hunter/providers/aviasales_search/gateway.py`
- Modify: `src/flight_hunter/providers/aviasales_search/client.py`
- Modify: `src/flight_hunter/providers/aviasales_search/adapter.py`
- Modify: `src/flight_hunter/providers/aviasales_search/schemas.py`
- Modify: `src/flight_hunter/providers/aviasales_search/mapper.py`
- Modify: `src/flight_hunter/application/date_matrix.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `docs/provider-contracts/aviasales-search.md`
- Modify: `tests/unit/providers/aviasales_search/test_client.py`
- Modify: `tests/unit/providers/aviasales_search/test_adapter.py`
- Modify: `tests/unit/providers/aviasales_search/test_mapper.py`
- Create: `tests/unit/providers/aviasales_search/test_gateway.py`
- Modify: `tests/unit/application/test_date_matrix.py`
- Modify: `tests/unit/api/test_date_matrix_api.py`

**Interfaces:**
- Produces: `ProviderLocation(kind, code)` with explicit airport/city semantics.
- Produces: one HTTP call per `start_exact`, `poll_exact_once`, and `calendar` gateway method.
- Produces: private `ExactSearchContinuation` and public `ConfirmedOfferEvidence`.
- Changes date-matrix prices to `DiscoverySignal` semantics.

- [ ] **Step 1: Write failing provider-contract and date-matrix tests**

Cover:

- airport requests set `is_origin_airport=true` and `is_destination_airport=true`;
- city codes are used only when capability says supported;
- `poll_results_once` makes exactly one transport call and returns cursor/ticket state;
- orchestrator start/poll methods disable client-internal retries so one gateway call equals one reserved HTTP attempt;
- every network/5xx retry is a newly leased operation attempt with a fresh budget/RPM reservation;
- parsed exact ticket maps to confirmed evidence with source, observed time, passengers, seller, segments, baggage unknowns, and protection `unknown`;
- search IDs and result URLs exist only in the private continuation;
- calendar amounts return `evidence_kind=discovery_signal` and `requires_live_confirmation=true`;
- calendar signals cannot be transformed into `FlightOffer`.

The date-matrix regression assertion is:

```python
priced = next(cell for cell in body["cells"] if cell["amount_minor"] is not None)
assert priced["evidence_kind"] == "discovery_signal"
assert priced["confirmation_state"] == "indicative"
assert priced["requires_live_confirmation"] is True
```

- [ ] **Step 2: Run provider/date tests and confirm current contract violations**

```powershell
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py -q
```

Expected: failures because polling is a loop, location flags are guessed as cities, and calendar cells are marked as live-confirmed.

- [ ] **Step 3: Add one-call start/poll contracts**

Add explicit location fields to `SearchStartParams` and a single-round result:

```python
@dataclass(frozen=True, slots=True)
class PollSearchResult:
    chunks: tuple[dict[str, object], ...]
    last_update_timestamp: int
    has_tickets: bool


def poll_results_once(
    self,
    results_url: str,
    search_id: str,
    *,
    last_update_timestamp: int,
    limit: int,
    request_id: str,
) -> PollSearchResult:
    response = self._poll_request(
        results_url=results_url,
        search_id=search_id,
        last_update_timestamp=last_update_timestamp,
        limit=limit,
        request_id=request_id,
    )
    chunks = _validated_chunks(response)
    cursor = max(
        (int(chunk.get("last_update_timestamp", 0)) for chunk in chunks),
        default=last_update_timestamp,
    )
    return PollSearchResult(
        chunks=chunks,
        last_update_timestamp=cursor,
        has_tickets=any(bool(chunk.get("tickets")) for chunk in chunks),
    )
```

Keep the existing synchronous `poll_results` as a compatibility wrapper built from repeated `poll_results_once` calls. The orchestrator uses only the one-call methods.

Construct the orchestrator's Aviasales client with `max_retries=0`. Existing
non-orchestrator callers may retain bounded client retries, but they cannot be
used inside an approved run. Execute the synchronous curl_cffi call through
`asyncio.to_thread` in the async gateway so network I/O does not block the
worker event loop.

- [ ] **Step 4: Implement the provider-neutral gateway**

`AviasalesSearchGateway`:

- accepts only frozen typed inputs;
- authorizes every operation through provider policy;
- returns calendar `DiscoverySignal`;
- persists start/poll cursor only through the private operation repository;
- maps exact ticket chunks to `ConfirmedOfferEvidence`;
- emits no booking URL and no raw provider DTO.

The public result type contains:

```python
@dataclass(frozen=True, slots=True)
class ExactPollOutcome:
    evidence: tuple[ConfirmedOfferEvidence, ...]
    next_cursor: int
    complete: bool
```

- [ ] **Step 5: Correct date-matrix semantics**

Remove the temporary `FlightOffer` wrapping in `_calendar_price_offer`. Store the provider amount directly in a typed discovery cell and return `Freshness.LIVE` only as observation recency, never as ticket confirmation. Add `evidence_kind` and `confirmation_state` to the response schema.

- [ ] **Step 6: Verify fixture contract and update provenance**

Read the user-supplied helper scripts only for schema/protocol comparison:

- `C:\Users\kiwun\Документы\api finder\aviasales_search.py`
- `C:\Users\kiwun\Документы\api finder\aviasales_client.py`
- `C:\Users\kiwun\Документы\api finder\aviasales_work`

Do not copy credentials, markers, signatures, cookies, or signed URLs. Record sanitized field provenance and the fixture verification date in `docs/provider-contracts/aviasales-search.md`.

Run:

```powershell
uv run pytest tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py -q
uv run mypy src/flight_hunter/providers/aviasales_search src/flight_hunter/application/date_matrix.py
```

Expected: all fixture-only checks pass; no network call occurs.

- [ ] **Step 7: Commit**

```powershell
git add src/flight_hunter/providers/aviasales_search src/flight_hunter/application/date_matrix.py src/flight_hunter/api/app.py docs/provider-contracts/aviasales-search.md tests/unit/providers/aviasales_search tests/unit/application/test_date_matrix.py tests/unit/api/test_date_matrix_api.py
git commit -m "feat: add resumable aviasales search gateway"
```

---

### Task 9: Execute Calendar and Exact Search Durably in the Worker

**Files:**
- Create: `src/flight_hunter/application/agent_execution.py`
- Modify: `src/flight_hunter/application/agent_operations.py`
- Modify: `src/flight_hunter/ops/worker.py`
- Modify: `src/flight_hunter/api/agent_routes.py`
- Modify: `src/flight_hunter/api/agent_schemas.py`
- Modify: `compose.yaml`
- Create: `tests/unit/application/test_agent_execution.py`
- Modify: `tests/unit/ops/test_worker_command.py`
- Modify: `tests/unit/api/test_agent_plan_api.py`
- Modify: `tests/unit/ops/test_compose_config.py`

**Interfaces:**
- Adds worker role `agent`.
- Materializes scope/calendar/exact-start/exact-poll/rank/report operations.
- Produces durable run progress and partial results.

- [ ] **Step 1: Write failing vertical execution tests**

Use a fake gateway that behaves like start/poll, not a fake final response. Prove:

- approved one-way exact plan transitions `queued → running → completed`;
- a flexible plan creates calendar signals, shortlists bounded date pairs, exact-verifies them, and ranks only exact evidence;
- restart after exact start resumes poll from persisted cursor;
- restart after a saved candidate does not duplicate evidence;
- cancellation before the next claim performs no new provider call;
- deadline and HTTP budget stop new calls and preserve confirmed evidence;
- 403/schema is terminal per operation;
- 429 schedules `next_retry_at` from `Retry-After`;
- network/5xx retry is bounded;
- open circuit makes no provider call, and a successful half-open probe closes it;
- useful evidence plus failed operations ends `partial`;
- no evidence plus terminal failures ends `failed`.

- [ ] **Step 2: Run tests and confirm the worker has no agent role**

```powershell
uv run pytest tests/unit/application/test_agent_execution.py tests/unit/ops/test_worker_command.py tests/unit/api/test_agent_plan_api.py tests/unit/ops/test_compose_config.py -q
```

Expected: failures for absent executor, role, progress, and result behavior.

- [ ] **Step 3: Implement the run state machine**

The worker handles one leased operation at a time:

```python
async def run_claimed_operation(self, operation: AgentRunOperationRecord) -> None:
    if await self._runs.is_cancel_requested(operation.household_id, operation.run_id):
        await self._operations.mark_skipped(
            operation.household_id,
            operation.id,
            code="agent_run_cancelled",
            finished_at=self._clock(),
        )
        return
    reservation = await self._operations.reserve_http_attempt_if_required(
        operation.household_id,
        operation.run_id,
        operation.id,
        now=self._clock(),
    )
    if reservation.status is AttemptReservationStatus.RATE_LIMITED:
        await self._operations.mark_retry_wait(
            operation.household_id,
            operation.id,
            code="agent_provider_rate_wait",
            next_retry_at=reservation.retry_at,
        )
        return
    if reservation.status is AttemptReservationStatus.BUDGET_EXHAUSTED:
        await self._operations.mark_failed(
            operation.household_id,
            operation.id,
            code="agent_http_budget_exhausted",
            finished_at=self._clock(),
        )
        return
    outcome = await self._dispatch(operation)
    await self._persist_outcome(operation, outcome)
```

Non-network compose/rank/report operations do not consume HTTP units. Stage and run counters are derived after each operation outcome.

Before every provider reservation, check the persistent circuit state. A
provider-disabled, credential, or circuit denial becomes typed operation
evidence and does not loop. On graceful shutdown, finish or safely release the
currently owned database transaction and leave unstarted operations pending;
an unexpected process exit is recovered by lease expiry.

- [ ] **Step 4: Materialize exact and flexible workflows**

For exact input, materialize `exact_start` directly. For flexible/range/90-day input, materialize bounded calendar operations first; after they succeed, shortlist by observed amount and recency and materialize at most the approved exact limit. Poll operations carry private cursor state and stop at ticket evidence or approved poll-round cap.

- [ ] **Step 5: Wire worker, progress API, and Compose**

Add `agent` to `DEFAULT_WORKER_ROLES`, parsing, heartbeat role, idle detection, summary counters, drain control, and Compose command. `GET run` returns stage counts, operations attempted/succeeded/failed/skipped, actual logical/HTTP consumption, deadline, cancellation, and stable errors.

- [ ] **Step 6: Verify the first production vertical**

```powershell
uv run pytest tests/unit/application/test_agent_execution.py tests/unit/ops/test_worker_command.py tests/unit/api/test_agent_plan_api.py tests/unit/ops/test_compose_config.py -q
uv run mypy src/flight_hunter/application/agent_execution.py src/flight_hunter/application/agent_operations.py src/flight_hunter/ops/worker.py
```

Expected: exact and flexible fake-gateway flows complete durably; restart and cancellation tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src/flight_hunter/application/agent_execution.py src/flight_hunter/application/agent_operations.py src/flight_hunter/ops/worker.py src/flight_hunter/api/agent_routes.py src/flight_hunter/api/agent_schemas.py compose.yaml tests/unit/application/test_agent_execution.py tests/unit/ops/test_worker_command.py tests/unit/api/test_agent_plan_api.py tests/unit/ops/test_compose_config.py
git commit -m "feat: execute agent searches durably"
```

---

### Task 10: Complete Quick, Full, Nearby, Country, Region, and Anywhere Coverage

**Files:**
- Modify: `src/flight_hunter/application/agent_scope.py`
- Modify: `src/flight_hunter/application/agent_planning.py`
- Modify: `src/flight_hunter/application/agent_execution.py`
- Modify: `src/flight_hunter/application/agent_operations.py`
- Modify: `src/flight_hunter/persistence/agent_repositories.py`
- Modify: `src/flight_hunter/api/agent_schemas.py`
- Create: `tests/unit/application/test_agent_coverage.py`
- Modify: `tests/unit/application/test_agent_scope.py`
- Modify: `tests/unit/application/test_agent_execution.py`
- Modify: `tests/unit/api/test_agent_plan_api.py`

**Interfaces:**
- Finite scopes freeze every approved airport before execution.
- Anywhere freezes a bounded rule before approval and an immutable destination snapshot after discovery.
- Produces explicit coverage report for attempted/succeeded/failed/skipped pairs.

- [x] **Step 1: Write failing scope-coverage tests**

Cover:

- `LED → FR` quick selects deterministic bounded airports and dates;
- full includes every frozen searchable French airport or fails preflight with `agent_plan_budget_too_large`;
- nearby radius defaults to 150 km and records distance, but no savings before exact confirmation;
- region expansion stores taxonomy version;
- any destination seeds after the first `RunScopeSnapshot` are ignored;
- duplicate city/airport aliases collapse to one code;
- later airport import cannot change an approved finite scope;
- `full` status is impossible when any frozen pair was silently skipped;
- coverage response lists each pair and stable failure reason.

- [x] **Step 2: Run focused tests and confirm incomplete breadth handling**

```powershell
uv run pytest tests/unit/application/test_agent_coverage.py tests/unit/application/test_agent_scope.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py -q
```

Expected: failures for anywhere snapshot and complete coverage accounting.

- [x] **Step 3: Implement deterministic quick ordering**

Order quick candidates by a stable tuple:

```python
def quick_scope_key(candidate: ScopeAirportCandidate) -> tuple[int, int, int, str]:
    return (
        -candidate.discovery_evidence_count,
        -candidate.commercial_relevance,
        candidate.nearby_distance_km or 0,
        candidate.airport.iata_code,
    )
```

Unknown nearby ground cost remains `None` and contributes an uncertainty flag; it is never added as zero.

- [x] **Step 4: Freeze anywhere discovery once**

On first successful discovery stage, atomically insert one scope snapshot containing ordered destination codes and source signal IDs. Later calendar/exact stages read only that snapshot. Concurrent workers use a unique `run_id` constraint so only one snapshot wins.

- [x] **Step 5: Build honest coverage reporting**

Report frozen input, catalog/taxonomy version, planned pairs, attempted, succeeded, failed, skipped, and reason counts. A full run with failures may be `partial` but never relabeled as complete coverage.

- [x] **Step 6: Verify all scope modes**

```powershell
uv run pytest tests/unit/application/test_agent_coverage.py tests/unit/application/test_agent_scope.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py -q
uv run mypy src/flight_hunter/application/agent_scope.py src/flight_hunter/application/agent_planning.py src/flight_hunter/application/agent_execution.py
```

Expected: all generic scope and coverage tests pass.

- [x] **Step 7: Commit**

```powershell
git add src/flight_hunter/application/agent_scope.py src/flight_hunter/application/agent_planning.py src/flight_hunter/application/agent_execution.py src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/api/agent_schemas.py tests/unit/application/test_agent_coverage.py tests/unit/application/test_agent_scope.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py
git commit -m "feat: report complete agent search coverage"
```

---

### Task 11: Compose Split, Self-Transfer, Open-Jaw, and Multi-City Routes

**Files:**
- Create: `src/flight_hunter/application/agent_composition.py`
- Create: `src/flight_hunter/application/agent_reporting.py`
- Modify: `src/flight_hunter/domain/agent_evidence.py`
- Modify: `src/flight_hunter/application/agent_execution.py`
- Modify: `src/flight_hunter/application/agent_operations.py`
- Modify: `src/flight_hunter/persistence/agent_repositories.py`
- Modify: `src/flight_hunter/api/agent_schemas.py`
- Create: `tests/unit/application/test_agent_composition.py`
- Create: `tests/unit/application/test_agent_reporting.py`
- Modify: `tests/unit/application/test_agent_execution.py`
- Modify: `tests/unit/api/test_agent_plan_api.py`

**Interfaces:**
- Produces confirmed composed candidates only when every priced component is confirmed.
- Uses per-leg exact search for open-jaw/multi-city while native capability is unknown.
- Produces separate cheapest, fastest, balanced, low-risk, and risky views.

- [x] **Step 1: Write failing composer and ranker tests**

Cover:

- direct/multi-segment provider ticket remains one ticket with protection `unknown`;
- normal confirmed results expose only the existing short-lived booking-action token, never a raw provider ref or URL;
- split/self-transfer uses confirmed components only;
- same-airport self-transfer below 180 minutes is rejected;
- airport change below 360 minutes is rejected;
- layover above 18 hours is rejected by default;
- overlapping segments are rejected;
- airport change shows unknown transfer cost and cannot beat a fully priced route solely because of that unknown;
- mixed currency without fresh deterministic FX is non-comparable;
- open-jaw and multi-city preserve all ordered legs and passenger mix;
- unknown native multi-city capability materializes per-leg searches;
- beam width bounds candidate combinations;
- tie-breaking is stable;
- ranking snapshots reference only confirmed/composed IDs and do not rewrite evidence.

- [x] **Step 2: Run focused tests and confirm composition is absent**

```powershell
uv run pytest tests/unit/application/test_agent_composition.py tests/unit/application/test_agent_reporting.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py -q
```

Expected: import failures and missing result views.

- [x] **Step 3: Implement feasibility and integer price composition**

```python
def connection_is_feasible(
    inbound: ConfirmedOfferEvidence,
    outbound: ConfirmedOfferEvidence,
    policy: ConnectionPolicy,
) -> bool:
    if inbound.arrival_airport != outbound.departure_airport:
        required = policy.airport_change_minimum
    else:
        required = policy.same_airport_minimum
    connection = outbound.depart_at - inbound.arrive_at
    return required <= connection <= policy.maximum_layover
```

Add prices only when currencies/bases are comparable. Every candidate stores component evidence IDs, ticket boundaries, protection, connection assumptions, known total, unknown costs, and rejection/ranking reasons.

- [x] **Step 4: Implement bounded multi-leg beam composition**

After each ordered leg, retain a configured beam of non-dominated candidates by known total, elapsed duration, airport changes, ticket count, and uncertainty flags. Stable fingerprint and IATA/date ordering break ties. Do not expand an unbounded Cartesian product.

- [x] **Step 5: Implement deterministic result views**

`CandidateRanker` creates immutable rankings:

- cheapest confirmed known total;
- fastest elapsed journey;
- lowest known risk;
- balanced with displayed integer weights;
- split/self-transfer;
- risky alternatives.

`FactReportBuilder` receives the ranking snapshot and typed facts. It formats explanations but performs no price arithmetic.

For normal confirmed Aviasales evidence, keep the existing lazy booking-action
path: the server stores the private provider reference, the result serializer
may issue a short-lived signed action token, and only an explicit click resolves
the provider URL. Composed candidates expose booking only when their exact
ticket structure has an unambiguous supported action. Hidden-city overrides
this to unavailable.

- [x] **Step 6: Verify composition and API results**

```powershell
uv run pytest tests/unit/application/test_agent_composition.py tests/unit/application/test_agent_reporting.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py -q
uv run mypy src/flight_hunter/application/agent_composition.py src/flight_hunter/application/agent_reporting.py
```

Expected: all route-shape, feasibility, ranking, and result tests pass.

- [x] **Step 7: Commit**

```powershell
git add src/flight_hunter/domain/agent_evidence.py src/flight_hunter/application/agent_composition.py src/flight_hunter/application/agent_reporting.py src/flight_hunter/application/agent_execution.py src/flight_hunter/application/agent_operations.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/api/agent_schemas.py tests/unit/application/test_agent_composition.py tests/unit/application/test_agent_reporting.py tests/unit/application/test_agent_execution.py tests/unit/api/test_agent_plan_api.py
git commit -m "feat: compose and rank confirmed routes"
```

---

### Task 12: Isolate Hidden-City Research Behind a Second Approval

**Files:**
- Create: `src/flight_hunter/application/agent_hidden_city.py`
- Modify: `src/flight_hunter/domain/agent_search.py`
- Modify: `src/flight_hunter/domain/agent_evidence.py`
- Modify: `src/flight_hunter/application/agent_planning.py`
- Modify: `src/flight_hunter/application/agent_lifecycle.py`
- Modify: `src/flight_hunter/application/agent_execution.py`
- Modify: `src/flight_hunter/application/agent_result_records.py`
- Modify: `src/flight_hunter/providers/aviasales_search/mapper.py`
- Modify: `src/flight_hunter/api/agent_schemas.py`
- Modify: `src/flight_hunter/api/web.py`
- Modify: `src/flight_hunter/persistence/agent_repositories.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Create: `migrations/versions/0027_agent_hidden_city_research.py`
- Create: `tests/unit/application/test_agent_hidden_city.py`
- Modify: `tests/unit/application/test_agent_execution.py`
- Create: `tests/unit/application/test_agent_result_records.py`
- Modify: `tests/unit/application/test_agent_lifecycle.py`
- Modify: `tests/unit/api/test_agent_plan_api.py`
- Modify: `tests/unit/api/test_web_ui.py`
- Modify: `tests/unit/providers/aviasales_search/test_mapper.py`

**Interfaces:**
- Produces hidden-city research candidates in a separate result section.
- Requires exact `HIDDEN_CITY_WARNING_VERSION` acknowledgement bound to revision.
- Disables booking action and watch creation.

- [x] **Step 1: Write failing eligibility and approval tests**

Prove:

- hidden-city cannot execute without the current warning-version acknowledgement;
- acknowledgement for an old revision/version is rejected;
- only a one-way ticket on the final overall plan leg is eligible;
- desired airport must be an intermediate segment;
- no later plan leg may rely on the skipped final segment;
- round-trip/native multi tickets are rejected;
- known checked baggage is rejected;
- unknown baggage is `research_only_not_actionable`;
- every hidden-city candidate has `booking_action_available=false`;
- hidden-city candidates never enter normal ranking or watches;
- cancellation/contract/baggage warnings render before approval.

- [x] **Step 2: Run focused tests and confirm missing isolation**

```powershell
uv run pytest tests/unit/application/test_agent_hidden_city.py tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py -q
```

Expected: failures for missing warning gate and hidden-city service.

- [x] **Step 3: Implement strict eligibility**

```python
def classify_hidden_city(
    ticket: ConfirmedOfferEvidence,
    desired_airport: str,
    context: HiddenCityContext,
) -> HiddenCityDecision:
    if context.plan_leg_index != context.final_plan_leg_index:
        return HiddenCityDecision.rejected("not_final_plan_leg")
    if ticket.ticket_shape is not TicketShape.ONE_WAY:
        return HiddenCityDecision.rejected("one_way_ticket_required")
    if desired_airport not in ticket.intermediate_airports:
        return HiddenCityDecision.rejected("desired_airport_not_intermediate")
    if ticket.checked_baggage is BaggageState.INCLUDED:
        return HiddenCityDecision.rejected("checked_baggage_known")
    if ticket.checked_baggage is BaggageState.UNKNOWN:
        return HiddenCityDecision.research_only("baggage_unknown")
    return HiddenCityDecision.eligible()
```

- [x] **Step 4: Bind the second approval and isolate output**

Store warning version in `PlanExecutionApproval`. Changing hidden-city strategy creates a successor revision and invalidates old approval. The executor uses a distinct operation kind and candidate risk class. API serializers force booking/watch actions off.

- [x] **Step 5: Verify hidden-city flow**

```powershell
uv run pytest tests/unit/application/test_agent_hidden_city.py tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py -q
uv run mypy src/flight_hunter/application/agent_hidden_city.py
```

Expected: all hidden-city safety and isolation tests pass.

- [x] **Step 6: Commit**

```powershell
git add src/flight_hunter/application/agent_hidden_city.py src/flight_hunter/domain/agent_search.py src/flight_hunter/domain/agent_evidence.py src/flight_hunter/application/agent_planning.py src/flight_hunter/application/agent_lifecycle.py src/flight_hunter/application/agent_execution.py src/flight_hunter/api/agent_schemas.py src/flight_hunter/api/web.py tests/unit/application/test_agent_hidden_city.py tests/unit/application/test_agent_lifecycle.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py
git commit -m "feat: gate hidden city research"
```

Accepted on 2026-07-16 at `cabeeeb`. Independent review returned `ACCEPT`
with zero Critical, Important or Minor findings. The fresh full release check
passes 1,445 tests, Ruff format/lint, mypy over 122 source files, migrations,
pre-v1 upgrade, security with zero findings, Compose validation and health.
No live provider call or user database access was performed.

---

### Task 13: Add Evidence-Gated Buy Timing, Anomaly, and Currency Analysis

**Files:**
- Create: `src/flight_hunter/application/agent_analysis.py`
- Modify: `src/flight_hunter/domain/agent_evidence.py`
- Modify: `src/flight_hunter/application/agent_planning.py`
- Modify: `src/flight_hunter/application/agent_operations.py`
- Modify: `src/flight_hunter/application/agent_execution.py`
- Modify: `src/flight_hunter/application/agent_result_records.py`
- Modify: `src/flight_hunter/application/agent_reporting.py`
- Modify: `src/flight_hunter/persistence/agent_repositories.py`
- Modify: `src/flight_hunter/persistence/models.py`
- Modify: `src/flight_hunter/api/agent_schemas.py`
- Modify: `src/flight_hunter/api/agent_routes.py`
- Modify: `src/flight_hunter/api/web.py`
- Create: `migrations/versions/0028_agent_fare_analysis_history.py`
- Create: `tests/unit/application/test_agent_analysis.py`
- Modify: `tests/unit/application/test_agent_execution.py`
- Modify: `tests/unit/application/test_agent_operations.py`
- Modify: `tests/unit/application/test_agent_planning.py`
- Create: `tests/unit/persistence/test_agent_history_repository.py`
- Modify: `tests/unit/persistence/test_agent_evidence_repository.py`
- Modify: `tests/unit/persistence/test_alembic_upgrade.py`
- Modify: `tests/unit/api/test_agent_plan_api.py`
- Modify: `tests/unit/api/test_web_ui.py`
- Modify: `tests/integration/test_upgrade_from_pre_v1.py`

**Interfaces:**
- Produces: `HistorySeriesKey`, `BuyTimingAssessment`, `AnomalyAssessment`, `CurrencyComparison`.
- Reads exact confirmed append-only evidence only.
- Uses typed fresh `FxRateObservation` and explicit card-fee assumptions.

- [x] **Step 1: Write failing history comparability tests**

Prove distinct history series for differences in:

- ordered legs and every date window;
- return date, stay length/band, trip shape;
- cabin and complete passenger mix;
- ticket structure/risk;
- baggage state;
- currency basis and aggregation mode;
- provider/seller/fare product in `same_product` mode.

Also cover all evidence gates:

- general history needs 40 observations, 21 days, and 14 distinct dates;
- weekday/four-hour comparison needs 8 observations per compared bucket across 4 weeks and matched days-to-departure bands;
- recommendation difference must be at least 5%;
- buy-now requires current price at or below the 20th percentile and says `historically_low`;
- anomaly needs 20 observations across 7 dates, ratio at most 60%, and MAD z-score at most -3;
- MAD zero still requires non-zero range and ratio rule;
- FX older than 24 hours or missing fee provenance returns `not_comparable`;
- missing FX provider returns `fx_provider_unavailable`;
- mismatched flight/seller/fare/baggage/rules returns `not_comparable`.
- each market/currency provider query is materialized as an approved logical operation and reserves all real HTTP attempts.
- legacy confirmed evidence with no canonical series hash is excluded rather than guessed;
- analysis snapshots are append-only, idempotent and household-isolated.

- [x] **Step 2: Run focused tests and confirm analysis is absent**

```powershell
uv run pytest tests/unit/application/test_agent_analysis.py tests/unit/persistence/test_agent_history_repository.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py -q
```

Expected: import and behavior failures.

- [x] **Step 3: Implement exact history keys and repository query**

```python
@dataclass(frozen=True, slots=True)
class HistorySeriesKey:
    ordered_leg_keys: tuple[HistoryLegKey, ...]
    trip_shape: TripShape
    cabin: str
    passenger_mix: PassengerMix
    ticket_structure: TicketStructure
    risk_class: RiskClass
    baggage_key: BaggageKey
    currency_basis: CurrencyBasis
    aggregation_mode: HistoryAggregationMode
    product_key: ProductKey | None
```

Migration `0028_agent_fare_analysis_history` adds a nullable canonical series
hash to confirmed evidence for forward compatibility, indexes
`(household_id, history_series_hash, observed_at, id)`, and adds immutable
analysis snapshots. New exact evidence stores the hash; legacy `NULL` rows are
not backfilled from incomplete facts and are excluded from analysis.
`market_minimum` and `same_product` queries never mix.

- [x] **Step 4: Implement robust deterministic assessments**

Use integer/`Decimal` calculations. Publish sample count, dates, weeks, span, percentile/median, days-to-departure bands, timezone, thresholds, and calculation version. Failed evidence gates produce `insufficient_data` and a separate explicit watch action.

Anomaly wording is always `suspected_anomaly`. External feed/search text may be displayed as untrusted research references but never contributes price evidence.

The executor stores one deterministic analysis snapshot per run after confirmed
evidence is durable. Reads return that snapshot and never silently recompute an
old run against newer history.

- [x] **Step 5: Implement currency comparability**

Stable flight fingerprint includes airports, ordered segments, carrier/flight number, local departure timestamps, and cabin. Require equivalent seller/gate, fare code/family, baggage, ticket structure, and known refund/change rules. Without all material equivalence plus fresh FX and fee assumptions, show side-by-side amounts without a savings claim.

Currency/market searches execute only when their exact variants were frozen in
the approved plan and budget. Until an FX provider/config is enabled, the
production result is `fx_provider_unavailable`; no default market list, FX rate,
card fee or savings amount is invented.

- [x] **Step 6: Verify analytics and UI wording**

```powershell
uv run pytest tests/unit/application/test_agent_analysis.py tests/unit/persistence/test_agent_history_repository.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py -q
uv run mypy src/flight_hunter/application/agent_analysis.py src/flight_hunter/application/agent_reporting.py
```

Expected: all threshold boundaries and honest fallback states pass.

Accepted verification on 2026-07-16: the exact four-file gate passes 114 tests;
analysis/executor passes 196; lifecycle/API/web passes 102; persistence passes
313; migration/history upgrade checks pass 18; full mypy passes 123 source
files; Ruff and `git diff --check` pass. Independent read-only review returned
`APPROVE` with zero Critical, Important or Minor findings after two hardening
cycles. Generic watches remain explicitly separate from canonical analysis
history. No live provider call or user database access was performed.

- [x] **Step 7: Commit**

```powershell
git add src/flight_hunter/application/agent_analysis.py src/flight_hunter/domain/agent_evidence.py src/flight_hunter/application/agent_execution.py src/flight_hunter/application/agent_reporting.py src/flight_hunter/persistence/agent_repositories.py src/flight_hunter/api/agent_schemas.py src/flight_hunter/api/web.py tests/unit/application/test_agent_analysis.py tests/unit/persistence/test_agent_history_repository.py tests/unit/api/test_agent_plan_api.py tests/unit/api/test_web_ui.py
git commit -m "feat: add evidence gated fare analysis"
```

---

### Task 14: Prove the Full Browser Flow, Recovery, and Observability

**Files:**
- Modify: `tests/e2e/conftest.py`
- Create: `tests/e2e/test_agent_route_orchestrator.py`
- Create: `tests/integration/test_agent_worker_recovery.py`
- Modify: `src/flight_hunter/ops/release_check.py`
- Modify: `src/flight_hunter/ops/application_metrics.py`
- Modify: `src/flight_hunter/application/worker_health.py`
- Modify: `src/flight_hunter/api/app.py`
- Modify: `tests/unit/ops/test_release_check.py`
- Modify: `tests/unit/ops/test_application_metrics.py`
- Modify: `tests/unit/application/test_worker_health.py`
- Modify: `tests/unit/api/test_admin_worker_health_api.py`
- Modify: `src/flight_hunter/api/web.py`

**Interfaces:**
- Exercises real FastAPI, migrated SQLite, bundled UI, and worker against a deterministic fixture gateway.
- Adds an agent acceptance stage to the credential-free release check.
- Adds sanitized agent queue/circuit/run metrics and admin health without raw requests.

- [ ] **Step 1: Write browser and restart acceptance scenarios**

Automate:

1. `СПб → Франция` without date asks for a period and offers rolling 90 days.
2. Rolling 90 days shows a quick plan and makes zero provider calls before click.
3. Execute survives reload, shows phases, and returns separate confirmed and risky sections.
4. Full France creates a new revision with a larger estimate and fresh approval.
5. Anywhere freezes a destination snapshot.
6. Open-jaw/multi-city preserves ordered legs and ticket boundaries.
7. Rate limit yields retry/partial state without losing evidence.
8. Missing history says `Недостаточно данных` and offers a watch.
9. Hidden-city cannot execute before warning acknowledgement.
10. Mobile viewport exposes plan, cancel, progress, partial error, and results.

The integration test stops the worker after exact start, constructs a new worker instance, and proves poll resumes from persisted continuation without duplicating evidence.

Add metric/health assertions for queued/leased/retry-wait/failed operation
counts, oldest due operation, circuit state, run completion/partial/failure
counts, estimate-versus-actual operations, HTTP attempts per useful candidate,
provider denials, duration, and recovery count. Audit events include plan,
revision, run, approval, cancellation, parser/planner/ranker versions, and
stable status codes but exclude free text and private provider state.

- [ ] **Step 2: Run new acceptance tests and confirm missing end-to-end behavior**

```powershell
uv run pytest tests/integration/test_agent_worker_recovery.py -q
uv run pytest tests/e2e/test_agent_route_orchestrator.py -q
```

Expected: scenario failures before final UI/recovery wiring.

- [ ] **Step 3: Finish UI accessibility and polling behavior**

Use semantic status regions with `aria-live=polite`, disable duplicate execute clicks, preserve active plan/run IDs in local storage, reconcile them from the server on load, and stop polling on terminal state. Cancellation always includes explicit plan and run IDs.

- [ ] **Step 4: Add the release-check stage**

The stage runs agent unit/integration/browser tests with a fixture gateway and verifies:

- no live network in CI mode;
- migration head is `0024_agent_execution_ledger`;
- no private continuation or provider secret in HTTP/browser output;
- every actual provider attempt has a durable reservation and respects the rolling RPM limit;
- no calendar signal in confirmed ranking;
- no cross-household visibility.

- [ ] **Step 5: Verify browser and recovery**

```powershell
uv run pytest tests/integration/test_agent_worker_recovery.py -q
uv run pytest tests/e2e/test_agent_route_orchestrator.py -q
uv run pytest tests/unit/ops/test_release_check.py tests/unit/ops/test_application_metrics.py tests/unit/application/test_worker_health.py tests/unit/api/test_admin_worker_health_api.py -q
```

Expected: all acceptance scenarios pass.

- [ ] **Step 6: Commit**

```powershell
git add tests/e2e/conftest.py tests/e2e/test_agent_route_orchestrator.py tests/integration/test_agent_worker_recovery.py src/flight_hunter/ops/release_check.py src/flight_hunter/ops/application_metrics.py src/flight_hunter/application/worker_health.py src/flight_hunter/api/app.py tests/unit/ops/test_release_check.py tests/unit/ops/test_application_metrics.py tests/unit/application/test_worker_health.py tests/unit/api/test_admin_worker_health_api.py src/flight_hunter/api/web.py
git commit -m "test: prove agent route orchestration"
```

---

### Task 15: Harden, Document, Verify Live Contract, and Finish Local v1.1.0

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/provider-contracts/aviasales-search.md`
- Create: `docs/runbooks/agent-route-search.md`
- Modify: `CHANGELOG.md`
- Modify: `IMPLEMENTATION_STATUS.md`
- Modify: `Makefile`
- Modify: `tests/unit/test_readme_contract.py`
- Modify: `tests/unit/ops/test_makefile_commands.py`
- Modify: `tests/unit/ops/test_security_scan.py`

**Interfaces:**
- Bumps local release to `1.1.0` after all feature gates pass.
- Documents install, migration, worker, search, recovery, cancellation, backup, and provider-failure behavior.
- Finishes on local `main` without pushing.

- [ ] **Step 1: Write failing release-documentation contracts**

Assert README/runbook include exact commands for:

- `make bootstrap`, `make migrate`, `make dev`, and `make release-check`;
- starting an `agent` worker;
- creating, approving, monitoring, cancelling, cloning, and resuming a plan;
- quick/full budgets and hidden-city warning;
- backup before upgrade and restore;
- offline/demo behavior and typed Aviasales errors;
- no claim that train/bus prices or every world itinerary are covered.

Security tests scan logs, OpenAPI examples, bundled JS, fixture summaries, and release artifacts for signature, marker, continuation, signed URL, bearer token, and PII leakage.

- [ ] **Step 2: Run contract tests and confirm docs/version lag**

```powershell
uv run pytest tests/unit/test_readme_contract.py tests/unit/ops/test_makefile_commands.py tests/unit/ops/test_security_scan.py -q
```

Expected: failures until version, commands, runbook, and security cases are updated.

- [ ] **Step 3: Update release docs and status**

Set package/API release version to `1.1.0`. Document:

- deterministic plan/approval/execution architecture;
- exact API examples without secrets;
- capability `unknown` semantics;
- indicative versus confirmed evidence;
- local budget tuning with hard ceiling;
- SQLite worker recovery and operation leases;
- hidden-city restrictions;
- analytics evidence thresholds;
- provider outage and partial-result behavior;
- explicit flight-only boundary.

Mark the implementation slice complete only after fresh verification evidence exists.

- [ ] **Step 4: Run fixture and local live provider checks**

First run fixture contracts:

```powershell
make provider-contracts
```

Then, only when local Aviasales credentials are configured, run summary-only live calendar and exact smoke:

```powershell
uv run flight-hunter-source-smoke --source aviasales_search --summary-only
```

Expected live output contains only operation status, result count, provider ID, freshness, and observed timestamp. It contains no price, signature, marker, search ID, result URL, proposal ID, or booking URL. If external access is blocked, record the typed `network_error`, `blocked`, or auth result and continue fixture/offline release validation without inventing success.

- [ ] **Step 5: Run the complete quality gate**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -q
uv run pytest tests/integration -q
uv run pytest tests/e2e -q
make security
make release-check
```

Expected:

- formatting, lint, types, unit, integration, browser, migration, security, Compose, and release stages pass;
- no live provider call occurs in ordinary pytest/CI;
- migration upgrade preserves v1 data;
- all seven presets and free text use the same plan engine;
- no placeholder implementation remains in the touched flow.

- [ ] **Step 6: Scan touched production code for unfinished stubs and secret terms**

```powershell
rg.exe -n "NotImplementedError|^[[:space:]]*pass[[:space:]]*$|fake return|private_continuation_json|X-Signature|signed booking" src/flight_hunter
```

Expected: no unfinished stub; private/secret identifiers appear only in their guarded server-side definitions/tests and never in delivery serializers, logs, or web assets.

- [ ] **Step 7: Commit the release**

```powershell
git add pyproject.toml README.md docs/ARCHITECTURE.md docs/provider-contracts/aviasales-search.md docs/runbooks/agent-route-search.md CHANGELOG.md IMPLEMENTATION_STATUS.md Makefile tests/unit/test_readme_contract.py tests/unit/ops/test_makefile_commands.py tests/unit/ops/test_security_scan.py
git commit -m "release: flight hunter 1.1.0"
```

- [ ] **Step 8: Merge locally to main after a clean final gate**

```powershell
git status --short
git switch main
git merge --no-ff codex/agent-route-orchestrator -m "merge: agent route orchestrator"
git status --short
```

Expected: the feature branch merges cleanly, `main` is clean, and no push occurs.

---

## Final Acceptance Matrix

| Requirement | Owning tasks | Fresh proof |
|---|---:|---|
| Free text and presets share one engine | 3, 5, 6 | agent/API/browser tests |
| Visible immutable plan before network | 3–6 | zero-call regression |
| Generic destination and date scopes | 2, 3, 10 | scope/coverage tests |
| Durable start/poll/retry/cancel/restart | 7–9, 14 | ledger/recovery tests |
| Confirmed-only ranking | 1, 8, 11 | type/repository/ranker tests |
| Split/self/open-jaw/multi-city | 11 | composer/API tests |
| Isolated hidden-city | 12 | approval/eligibility/UI tests |
| Buy timing/error fare/currency honesty | 13 | threshold boundary tests |
| Household isolation and idempotency | 4, 5, 7 | persistence/API tests |
| Provider contract and secret safety | 8, 15 | fixtures, smoke, security |
| Local release and main merge | 14, 15 | release-check and Git status |

## Execution Notes

- Check off each item only after its exact command passes on fresh output.
- If a task uncovers a provider schema fact not present in the sanitized fixture, stop that provider branch, add a sanitized fixture/contract test from a local live observation, update the provider contract, and only then map the field.
- A task may split into a smaller commit when tests expose an independent bug, but the task acceptance command must still pass before advancing.
- Preserve unrelated user changes in a dirty worktree.
