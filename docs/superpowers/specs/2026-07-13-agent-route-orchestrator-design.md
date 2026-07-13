# Agent Route Orchestrator — Design

Date: 2026-07-13  
Status: user-approved design, pending implementation plan  
Target: Flight Hunter local release after v1.0.0

## 1. Objective

Turn the existing Flight Hunter agent from a plan-only assistant into a
deterministic, approval-gated route-search orchestrator.

A user can write requests such as:

- `Найди самый дешёвый способ улететь из СПб во Францию`;
- `Куда дешевле всего улететь из СПб в ближайшие 90 дней`;
- `СПб → Париж → Рим → СПб`;
- `Туда в Париж, обратно из Ниццы`;
- `Проверь соседние даты, nearby, split-ticket и скрытый город`.

The agent must produce an explicit plan, estimate provider work, wait for a
user click, execute the approved plan durably, and explain only results backed
by provider/reference/history data.

## 2. Product boundary

### 2.1 In scope

- airport, city, country, region and `anywhere` geographic scopes;
- one-way, round-trip, open-jaw and multi-city trips;
- exact dates, `±N` flexible dates, explicit ranges and rolling 90-day search;
- quick shortlist and user-selected full-scope scan;
- direct and multi-segment single-ticket results returned by Aviasales, with
  protection status `unknown` unless explicit provider evidence exists;
- split-ticket and self-transfer composition from confirmed segment offers;
- nearby origin and destination airports;
- hidden-city research behind a second explicit approval;
- cheapest, fastest, balanced and low-risk result views;
- price-history, suspected error-fare and currency-comparison presets with
  strict evidence thresholds;
- durable execution, progress, partial success, cancellation and restart;
- deterministic fallback when no model is configured.

### 2.2 Out of scope

- purchasing or reserving a ticket;
- automatic navigation through airline checkout;
- rail, coach, taxi or other ground-transport prices until a typed provider is
  added;
- claiming mathematical enumeration of every itinerary in the world;
- inventing visa, baggage, airport-transfer, FX or card-fee facts;
- treating an anomalous fare as guaranteed or ticketable;
- mixing hidden-city results into the normal ranking;
- public/multi-host deployment.

Flight-only results may mention an unpriced ground transfer when an airport
change is required, but an unknown ground cost is never converted to zero and
is never used to claim that a route is cheapest overall.

## 3. Core principles

1. The model parses intent and writes explanations. Application code owns
   route expansion, provider calls, arithmetic, composition and ranking.
2. Every external price or schedule fact has source, `observed_at` and
   freshness.
3. A chat message creates a plan; it does not start a live scan.
4. Execution requires a version-bound user confirmation.
5. Hidden-city requires an additional explicit opt-in.
6. Provider failure produces typed per-stage evidence and partial results.
7. Plans and runs are household-scoped, idempotent and resumable.
8. Search breadth is bounded and visible before execution.

## 4. User flow

### 4.1 Natural-language entry

The user writes a request or chooses a preset. Both paths call the same intent
parser and plan builder.

The parser extracts:

- origin/destination scopes;
- trip shape and ordered legs;
- date mode and stay constraints;
- passenger mix and currency;
- requested route strategies;
- ranking preference;
- whether the user requested monitoring.

If information is missing, the agent asks for it and offers bounded shortcuts.
For a missing date it asks for a month/range and also offers
`Проверить ближайшие 90 дней`. Neither choice starts provider calls.

### 4.2 Plan card

The proposed plan shows:

```text
СПб → любая точка Франции
Trip: round-trip
Dates: 2026-09-01..2026-11-29
Passengers: 1 adult
Coverage: quick shortlist
Strategies: direct, through-ticket, split, self-transfer
Hidden-city: disabled
Estimate: 42 calendar + 18 exact calls
Provider limit: 20 rpm
Deadline: 10 minutes
```

Actions:

- `Изменить план`;
- `Запустить быстрый поиск`;
- `Проверить всю область`;
- `Добавить hidden-city`;
- `Отмена`.

The execute request includes `expected_version` and an idempotency key. A stale
plan cannot be run silently.

### 4.3 Execution and progress

The UI renders durable phases:

1. resolving geographic scopes;
2. calendar shortlist;
3. exact live verification;
4. through-ticket extraction and protection classification;
5. split/self-transfer composition;
6. optional hidden-city research;
7. ranking and report generation.

Closing the page does not stop the job. The UI can resume from the saved run.
Cancellation prevents new provider calls and preserves completed evidence.

### 4.4 Results

Results are presented in separate sections:

1. cheapest low-risk itinerary;
2. cheapest confirmed itinerary overall;
3. fastest;
4. balanced price/time/risk;
5. split-ticket and self-transfer;
6. hidden-city research.

Each candidate exposes:

- complete ordered segments;
- local and timezone-aware timestamps;
- connection duration and airport changes;
- ticket structure and protection status;
- passengers and total fare;
- seller, baggage state and unknown fields;
- source, `observed_at`, freshness and confirmation state;
- warnings and exclusion/ranking reasons.

## 5. Domain model

### 5.1 Travel intent

```python
class LocationScopeKind(StrEnum):
    AIRPORT = "airport"
    CITY = "city"
    COUNTRY = "country"
    REGION = "region"
    ANYWHERE = "anywhere"

class TripShape(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    OPEN_JAW = "open_jaw"
    MULTI_CITY = "multi_city"

class DateMode(StrEnum):
    EXACT = "exact"
    FLEXIBLE = "flexible"
    RANGE = "range"
    ROLLING_90_DAYS = "rolling_90_days"

class RouteStrategy(StrEnum):
    DIRECT = "direct"
    THROUGH_TICKET = "through_ticket"
    SPLIT_TICKET = "split_ticket"
    SELF_TRANSFER = "self_transfer"
    HIDDEN_CITY = "hidden_city"
```

`TravelIntent` is provider-neutral and contains ordered requested legs. Each
leg has origin/destination `LocationScope` and a `DateConstraint`. Multi-city
and open-jaw are represented as explicit ordered legs instead of special
provider DTO fields.

### 5.2 Plan aggregate and immutable revisions

`AgentSearchPlan` is a stable household-owned aggregate ID. Its content lives
in immutable `AgentSearchPlanRevision` rows. A revision contains:

- monotonically increasing revision number and canonical content hash;
- normalized intent and unresolved choices;
- frozen airport scope or a bounded frozen discovery rule;
- airport-catalog checksum, region-taxonomy version and provider-capability
  snapshot;
- coverage mode: `quick` or `full`;
- enabled strategies and risk gates;
- ranking profile;
- logical-operation, HTTP-attempt and deadline budgets;
- estimated calendar/exact operations and worst-case HTTP attempts;
- prompt/parser and deterministic plan-builder versions;
- `created_at`, `expires_at` and `superseded_at`.

Revision states are deliberately separate from execution:

```text
draft --finalize(valid + estimated)--> awaiting_approval
draft --edit-------------------------> superseded + new draft
awaiting_approval --edit-------------> superseded + new draft
awaiting_approval --execute----------> consumed
awaiting_approval -------------------> expired
consumed/superseded/expired --clone--> unchanged old row + new draft
```

POST initially writes a draft. The plan builder automatically finalizes it to
`awaiting_approval` only when required choices are resolved, scope/capability
inputs are frozen, validation passes and both budget estimates are available.
Only an awaiting revision renders an executable plan card.

PATCH may address the current `draft` or `awaiting_approval` revision but never
mutates it. It marks that revision superseded, writes a successor draft, applies
the requested edit, then runs the same automatic finalize step. An incomplete
successor remains draft and returns clarification fields; a complete successor
becomes awaiting approval and renders a new card. Existing runs continue to
reference their immutable consumed revision. An awaiting revision expires
after the configured plan TTL, initially 24 hours.

Rerun/expansion uses an explicit clone operation, not PATCH. It accepts any
visible terminal revision as `source_revision_id`, leaves that source unchanged,
writes a new draft under the same plan aggregate, refreshes catalog/capability/
cost-model inputs, applies optional edits such as `quick → full`, and runs the
same automatic finalize step. The new revision requires a new execute click.

### 5.3 Approval and run lifecycle

The execute click atomically writes a `PlanExecutionApproval` and one
`AgentPlanRun`. The approval records revision ID/hash, user/session, approval
timestamp, approved budgets/strategies, risk-warning versions and the run ID
that consumed it. It cannot be reused.

`POST .../execute` requires the exact revision ID, content hash, expected
revision number and an idempotency key. If the current revision changed,
expired, was consumed, or belongs to another household, execution is rejected.
A rerun always requires a newly displayed estimate and a new execute click; it
creates a new revision when volatile capability/catalog inputs changed.

Run states are independent:

```text
queued -> running -> completed | partial | failed
queued  -> cancel_requested -> cancelled
running -> cancel_requested -> cancelled
```

Cancellation always targets an explicit `run_id`; it never means “whatever is
latest.” Only one non-terminal run per plan is allowed. The convenience
`runs/latest` endpoint means the greatest `(created_at, run_id)` visible to the
household, while all mutation endpoints require an explicit run ID.

### 5.4 Per-operation execution ledger

Fan-out work is durable at operation granularity, not only phase granularity.
`AgentRunOperation` stores:

- run/stage/provider IDs;
- deterministic operation fingerprint and typed operation kind;
- sanitized immutable input and private server-only continuation state;
- `pending | leased | retry_wait | succeeded | failed | skipped` status;
- lease owner/expiry, attempts and `next_retry_at`;
- reserved and consumed HTTP-attempt units;
- result evidence reference or stable error code.

`(run_id, operation_fingerprint)` is unique. The worker claims operations with
a lease, records an attempt reservation before network I/O and recovers expired
leases. Aviasales exact search is decomposed into durable start and poll work;
the opaque search continuation is persisted server-side and never sent to the
client/model/logs. A crash in the narrow window after a read-only upstream call
may repeat that call, so execution is at-least-once, but budget reservation,
candidate fingerprint dedupe and append-only observations make retries safe.

`AgentPlanStage` is an aggregate progress view derived from operations, not the
unit of resumability.

### 5.5 Evidence and capability types

Indicative and confirmed values are different types:

- `DiscoverySignal`: calendar/hot-offer evidence used only for shortlist;
- `ConfirmedOfferEvidence`: a ticket-bearing exact-search result;
- `ComposedRouteCandidate`: uses only confirmed component evidence;
- `ProviderCapabilitySnapshot`: versioned support and semantics used by a plan.

The ranker accepts only `ConfirmedOfferEvidence` and confirmed composed
candidates. `DiscoverySignal` cannot implement that input protocol and is
stored separately, so calendar amounts cannot enter final ranking by accident.
The current date-matrix code that wraps calendar values as `FlightOffer` must be
refactored before the orchestrator ranker is connected.

Capability values are `supported | unsupported | unknown`, not booleans that
default to false certainty. Protection is likewise
`explicitly_protected | self_transfer | unknown`. A multi-segment ticket in the
current Aviasales response has no verified PNR/protection field and therefore
uses `unknown`, never an invented “protected” label.

Candidate observations are append-only. Re-ranking creates a new ranking
snapshot without rewriting normalized evidence.

## 6. Geographic expansion

Location scopes resolve through a provider-neutral airport catalog:

- airport → one IATA airport;
- city → all relevant commercial airports for that city;
- country → commercial airports in that country;
- region → countries and their commercial airports;
- anywhere → destinations discoverable from calendar/hot-offer/reference
  sources, followed by exact verification.

Country expansion uses ISO 3166 alpha-2 values from a specific imported airport
catalog revision. Region expansion uses a versioned project-owned taxonomy
mapping region IDs to ISO country codes; RU/EN aliases are data in that same
version, not model knowledge. The airport catalog must be extended with
documented commercial-relevance provenance before that value affects ordering.

A quick scan orders airports by route coverage, commercial relevance, nearby
distance and discovery evidence. A full scan freezes every searchable
commercial airport in the approved scope into the plan revision.

Country/city/airport expansion is completed and frozen before approval. The
revision stores codes plus catalog/taxonomy checksums, so a later airport import
cannot change an approved surface.

`anywhere` is a bounded discovery rule because destinations are not known until
provider work starts. Its revision freezes origin scopes, date bounds, allowed
and excluded countries/regions, discovery source IDs, maximum destination
seeds and exact-verification budget. The run persists the first discovery
output as an immutable `RunScopeSnapshot`; later stages cannot silently add
destinations. The estimate uses the frozen maximum seed count.

Origin scopes use the same mechanism, so `Москва и аэропорты рядом → Южная
Европа` is not a special case.

Every result includes a coverage report: frozen input scope, destinations/dates
attempted, succeeded, failed, skipped, and the explicit reason for anything not
searched. “Full” means the entire frozen local scope completed; if a hard
budget prevents that, the plan must be revised before execution rather than
quietly returning a truncated result.

## 7. Search algorithm

### 7.1 Phase A — scope and budget

Resolve scopes, remove impossible/closed/non-commercial airports, deduplicate
city and airport aliases, calculate the Cartesian search surface and estimate
work before approval.

Budget units are explicit:

- `provider_operation`: one logical calendar query, exact-search workflow,
  suggest/discovery query or booking-free comparison;
- `http_attempt`: one actual upstream HTTP request, including start, every poll
  round and every retry;
- `exact_search`: one logical ticket search for one frozen provider request;
- `calendar_search`: one logical calendar query.

The provider adapter publishes a versioned cost model with maximum start
attempts, poll rounds, attempts per poll and retry policy. `PlanEstimator`
calculates both expected operations and worst-case HTTP attempts. RPM is
enforced against actual HTTP attempts, not logical searches. Every retry and
poll consumes the run's HTTP-attempt budget.

Initial configurable defaults:

| Mode | Calendar operations | Exact operations | Logical-operation default | Deadline |
|---|---:|---:|---:|---:|
| quick | up to 40 | up to 20 | 60 | 10 minutes |
| full | frozen-scope estimate | frozen-scope estimate | up to 240 | 30 minutes |

The revision also stores the derived worst-case HTTP-attempt cap. Provider RPM,
retry and circuit-breaker policies can only reduce work; they cannot override a
run budget upward. Reservations are atomic and a request is not started when
the remaining budget cannot cover its next HTTP attempt.

`240` is the initial default full-scan logical-operation limit, not an absolute
system claim. The application has a separate configured absolute ceiling,
initially 1,000 logical operations and its derived HTTP cap. Increasing a plan
above 240 creates a new revision and requires a new approval; exceeding the
system ceiling is rejected. A full scan that does not fit its approved budget
is `budget_too_large` before execution, never silently truncated.

### 7.2 Phase B — calendar shortlist

For range/flexible/90-day requests, calendar endpoints gather indicative date
and airport candidates. Calendar values never become final ticket results.
Candidates are ordered by observed amount and data recency, then the best
airport/date pairs move to exact search.

Exact-date requests skip this phase when no scope discovery is required.

### 7.3 Phase C — exact live search

The Aviasales adapter performs exact searches for approved pairs. Provider
responses supply direct flights and multi-segment single-ticket results.
Mapping stays inside the provider boundary. Because the verified response has
no explicit PNR/protection field, connection protection remains `unknown`
unless a future contract supplies direct evidence.

Only exact ticket-bearing results can become confirmed priced candidates.
Calendar-only rows remain indicative and visibly unconfirmed.

### 7.4 Phase D — split-ticket and self-transfer

Candidate hubs come from:

- connection airports observed in through-ticket results;
- the local route/airport catalog;
- high-coverage commercial hubs inside the approved geographic search graph.

The executor searches origin→hub and hub→destination legs separately. A
composed candidate is accepted only when every priced segment is confirmed,
currencies are comparable and timestamps form a feasible ordered journey.

Initial deterministic connection constraints:

- same-airport self-transfer: at least 180 minutes;
- airport change: at least 360 minutes plus an explicit unknown transfer cost
  unless deterministic transfer data exists;
- maximum layover: configurable, default 18 hours;
- no overlapping segments;
- no claim about visa/entry feasibility when rules are unavailable.

Price addition uses integer minor units. Mixed currencies require a
deterministic FX observation with timestamp; otherwise the candidate is shown
as non-comparable rather than converted by the model.

### 7.5 Phase E — open-jaw and multi-city

The current verified Aviasales adapter supports one-way and round-trip only.
Open-jaw and multi-city therefore use confirmed per-leg exact searches and the
composer. Native multi-direction search may be enabled only after a new
sanitized fixture, contract test and live smoke prove its schema, and the
capability snapshot records `supported`. `unknown` is treated as unsupported.

Provider request locations distinguish airport codes from provider-supported
city codes with typed `ProviderLocation(kind, code)`. The adapter controls
`is_origin_airport` / `is_destination_airport`; the planner never guesses these
flags. When city semantics are not contract-proven, scope expansion fans out to
frozen airport codes.

The composer keeps journey order, passenger mix, currency evidence, connection
constraints and ticket boundaries explicit.

The number of legs and candidate combinations is part of the approved budget.
Beam search keeps the best bounded candidates after every leg using stable
price/time/risk dominance rules; an unbounded Cartesian product is forbidden.

### 7.6 Phase F — hidden-city research

Hidden-city is disabled in normal plans. Enabling it requires a second
version-bound approval containing the baggage, cancellation and contract-risk
warning.

Research searches candidate onward destinations and accepts a result only when
the user's desired airport is an intermediate segment. These candidates:

- are stored and ranked separately;
- are built only from a separately searched one-way ticket; current
  round-trip/native-multi-ticket products are ineligible;
- may use only the final overall plan leg, with no later journey leg depending
  on completion of the skipped ticket segment;
- require the desired airport to occur before at least one skipped segment and
  forbid any intended later segment on the same ticket;
- are excluded when checked baggage is known to be included/required;
- are marked `research_only_not_actionable` when baggage is unknown;
- always set `booking_action_available=false` in this release;
- warn that checked baggage may continue to the ticketed destination;
- warn that later/return segments may be cancelled;
- are not described as safe or recommended.

The second approval stores the exact hidden-city warning version. Hidden-city
operations are not generated for open-jaw/multi-city intermediate legs, are not
watchable, and cannot be promoted into normal, split or self-transfer results.
Supporting broader cases requires a new design revision, not a relaxed warning.

## 8. Ranking and factual reporting

Ranking is deterministic. It produces separate Pareto-style views instead of
one opaque score:

- cheapest confirmed total fare;
- shortest elapsed journey;
- fewest/lowest-risk connections;
- balanced profile with displayed weights;
- risky alternatives outside normal results.

The ranker accounts for known fare, known baggage cost, duration, airport
changes, overnight waits, ticket protection and freshness. Unknown costs or
rules add uncertainty flags and cannot improve a route's rank by pretending to
be zero.

The report builder receives only typed facts and ranking explanations. It may
summarize why one candidate won, but cannot calculate prices or create route
facts.

## 9. Preset behavior

Existing preset identifiers remain compatible and use the same planner.

### 9.1 Flexible dates

Builds an exact plan with default `±3` days, shows the estimated calls and
requires confirmation before calendar/live work.

### 9.2 Nearby airports

Expands origin and destination scopes to the configured radius, default 150
km. Savings are stated only after exact comparison and only with known ground
cost assumptions.

### 9.3 When to buy

Uses stored price history only. Until the route/date window has sufficient
coverage, the result is `insufficient_data` and the agent offers to create a
watch. It does not recommend a weekday or hour from generic folklore.

Comparable observations share a typed `HistorySeriesKey` containing:

- every ordered airport leg and trip shape;
- departure-date window for every leg, including the return leg;
- exact stay duration or an explicitly approved `±1 night` stay band for
  round-trip/open-jaw;
- cabin and complete passenger mix;
- ticket structure/risk class;
- equivalent baggage inclusion/count/weight state (unknown baggage is a
  separate series);
- normalized currency/FX basis;
- aggregation mode.

`market_minimum` mode records the minimum confirmed offer in each observation
snapshot only among offers with that same key. `same_product` additionally keys
provider, seller/gate and fare-family/product fingerprint. The modes are never
mixed. Ordered multi-city dates and legs must all match their configured
windows; materially different return dates, stays, baggage or fare products
cannot share a series.

Observations are stratified by days-to-departure bands (`0–6`, `7–13`,
`14–29`, `30–59`, `60+`) before comparing booking time, so approaching
departure is not confused with a weekday/hour effect.

Initial evidence gates:

- general current-price percentile: at least 40 confirmed observations over at
  least 21 days and 14 distinct observation dates;
- weekday or four-hour booking-time bucket: at least 8 observations in every
  compared bucket, spread across at least 4 distinct weeks, with matching
  days-to-departure bands;
- recommendation difference: at least 5% between robust bucket medians;
- `buy_now` evidence: current confirmed price at or below the historical 20th
  percentile; wording remains “historically low,” never a prediction.

If any gate fails, that claim is omitted and the output is
`insufficient_data`. Every result publishes sample count, distinct dates/weeks,
history span, percentile/median, timezone and calculation version.

### 9.4 Error fare

A fare is labelled `suspected_anomaly`, never guaranteed error fare. Comparable
samples use the same key as buy-timing and exact confirmed evidence only. The
initial detector requires at least 20 observations across at least 7 distinct
dates. It flags a fare only when it is no more than 60% of the rolling median
and its robust MAD z-score is at most `-3`; when MAD is zero, both a non-zero
range and the 60% ratio rule are still required. Thresholds and detector
version are returned with the finding.

External forums/bots/channels may be researched through configured web-search
connectors, but their text is untrusted data and is not a price source.

### 9.5 Country site and currency

Comparison requires a stable same-flight fingerprint built from airports,
carrier/flight numbers, local departure timestamps, cabin and ordered segments;
provider proposal IDs alone are not identity. It also requires equivalent
seller/gate, fare family/code, baggage allowance, ticket structure and known
refund/change rules. An unknown or mismatched material field yields
`not_comparable`; it cannot support a saving claim. Every currency query is an
approved provider operation and contributes to both operation/HTTP budgets.

Conversion requires a typed `FxRateObservation` with source, base/quote,
observed timestamp and rate, no older than 24 hours by default. Card fees come
from an explicit user/configured assumption with provenance and effective date.
Without fresh FX or fee assumptions, the UI shows side-by-side amounts and
`not_comparable`; no saving is claimed. Until an FX provider/config is actually
enabled, the stable result is `fx_provider_unavailable`. The agent never
bypasses geo/access controls and never buys.

## 10. Application components

- `IntentParser`: deterministic parser plus optional typed model overlay.
- `AgentPlanBuilder`: validates intent and creates provider-neutral plans.
- `ScopeResolver`: expands airport/city/country/region/anywhere.
- `PlanEstimator`: computes logical operations, worst-case HTTP attempts and
  deadline estimate from a versioned provider cost model.
- `PlanApprovalService`: validates ownership, plan version and risk gates.
- `PlanExecutor`: durable orchestration state machine.
- `OperationScheduler`: materializes, leases and resumes per-operation fan-out.
- `ProviderSearchGateway`: policy-checked exact/calendar provider port.
- `ProviderCapabilityRegistry`: produces the frozen tri-state capability/cost
  snapshot used by a revision.
- `RouteComposer`: split/self-transfer/open-jaw/multi-city candidates.
- `HiddenCityResearchService`: isolated high-risk expansion.
- `CandidateRanker`: deterministic ranking snapshots.
- `FactReportBuilder`: final user-facing factual explanation.

Delivery adapters remain thin. Provider DTOs do not enter these contracts.

## 11. Persistence

Add forward-only migrations for:

- `agent_search_plans`;
- `agent_search_plan_revisions` (immutable, unique plan/revision and hash);
- `agent_plan_execution_approvals` (single-use, bound to revision and run);
- `agent_plan_runs`;
- `agent_plan_stages`;
- `agent_run_operations` (unique run/fingerprint, lease and attempt budget);
- `agent_run_scope_snapshots`;
- `agent_discovery_signals` (indicative-only);
- `agent_confirmed_offer_evidence`;
- `agent_composed_route_candidates`;
- `agent_ranking_snapshots`.

Every query includes household scope. Runs have unique `(household_id,
idempotency_key)` and one-active-run-per-plan constraints. Approval has a unique
`run_id` and cannot be reused. Operation claims use the existing worker
lock/retry conventions with lease expiry and unique fingerprints.

Discovery and confirmed evidence use distinct tables and repository return
types. Ranking snapshots may reference only confirmed-offer/composed-candidate
IDs; a database/application invariant rejects discovery-signal IDs. Candidate
evidence is append-only and may reference normalized existing offers instead of
copying secret provider refs. Private upstream continuations are encrypted or
server-only and never returned by repositories used in delivery/model context.

## 12. API contracts

Proposed endpoints:

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

`POST`/`PATCH` return clarification fields while the successor is an incomplete
draft and return an executable plan card after automatic finalization. `PATCH`
accepts the current draft or awaiting revision and always writes a successor as
defined in section 5.2. `execute` accepts only `awaiting_approval` and requires
bearer session, household ownership,
`revision_id`, `content_hash`, `expected_revision`, an idempotency key and the
exact hidden-city warning version when applicable. It records a single-use
approval and queues the run atomically. Repeating the same idempotency key
returns the original run; a different key against a consumed revision is
rejected and requires a refreshed revision/approval.

`POST .../{plan_id}/revisions` is that refresh path. It requires
`source_revision_id`, may include typed edits, clones even a consumed/expired
revision into a new draft, refreshes frozen volatile inputs, and never reuses an
old approval. It is the only rerun path after a terminal run.

`POST /api/v1/agent/chat/turn` remains compatible but returns a proposed plan
reference instead of executing live searches. `/api/v1/agent/plan` and presets
delegate to the new builder during migration.

API errors use stable codes such as:

- `agent_plan_incomplete`;
- `agent_plan_stale`;
- `agent_plan_consumed`;
- `agent_plan_expired`;
- `agent_plan_budget_too_large`;
- `agent_plan_approval_required`;
- `agent_provider_capability_unknown`;
- `agent_hidden_city_ack_required`;
- `agent_run_already_active`;
- `agent_run_deadline_exceeded`;
- `agent_run_partial`;
- `agent_run_cancelled`.

## 13. Reliability and errors

Every run has:

- idempotency key;
- deadline, logical-operation budget and worst-case HTTP-attempt budget;
- durable attempts and next retry;
- per-operation SQLite-safe lease and unique fingerprint;
- graceful cancellation;
- per-stage partial success;
- bounded retry respecting `Retry-After` and circuit breakers;
- restart recovery;
- sanitized trace events.

An HTTP-attempt unit is reserved before every start/poll/retry. Unused
reservation is reconciled after a completed attempt, while a process crash
leaves it consumed so restart cannot exceed the approved cap. Stage/run
counters are derived from the operation ledger.

403/auth/schema errors are terminal for the affected provider operation. 429
uses `Retry-After`. Network/5xx retries are bounded. A failed scope/date pair is
recorded without destroying successful candidates.

The final status is:

- `completed`: all approved phases finished;
- `partial`: useful candidates exist but one or more operations failed or the
  approved budget/deadline ended;
- `failed`: no useful result and a terminal reason exists.

## 14. Permissions and safety

| Action | Policy |
|---|---|
| Parse request and draft plan | allowed |
| Read airport/history/cache data | allowed within household scope |
| Execute provider search | explicit plan confirmation |
| Expand from quick to full scan | new confirmation/version |
| Enable hidden-city | second explicit acknowledgement |
| Create watch | explicit request or separate click |
| Resolve booking URL | existing explicit booking action |
| Purchase/reserve | forbidden |

Provider/feed/web text is untrusted data. It cannot modify instructions or
enable tools. Secrets, provider refs, raw signed URLs and PII never enter model
context, client bundles or audit summaries.

## 15. Observability

Record operational events without hidden reasoning:

- plan/run/stage IDs and versions;
- parser and planner versions;
- scopes and strategies, excluding sensitive free text;
- estimated and actual call counts;
- provider operation, status code class, retry and latency;
- candidate counts per phase;
- ranker version and selected profile;
- approval/cancellation state;
- final status and stable error codes.

Metrics include completion/partial/failure rate, estimate error, calls per useful
candidate, cache hit rate, provider denials, run duration, recovery count and
household isolation failures.

## 16. Testing strategy

### 16.1 Domain and application

- country scope expands to its commercial airports;
- quick and full modes produce different deterministic budgets;
- estimator distinguishes logical operations from start/poll/retry HTTP
  attempts and never exceeds either cap;
- complete draft auto-finalizes, while editing an awaiting revision supersedes
  it and produces a new immutable successor;
- airport/city/country/region/anywhere scopes;
- catalog/taxonomy versions and frozen scope survive later imports;
- anywhere discovery cannot add seeds after the run scope snapshot;
- exact/flexible/range/90-day constraints;
- one-way/round-trip/open-jaw/multi-city plans;
- single-ticket connections map with protection `unknown` when the provider has
  no explicit evidence;
- unsupported/unknown native multi-city capability uses per-leg composition;
- discovery signals cannot satisfy the confirmed-ranker input contract;
- split price is accepted only with every segment confirmed;
- infeasible or overlapping self-transfers are rejected;
- airport-change buffer and unknown ground cost are visible;
- mixed-currency routes require deterministic FX;
- hidden-city is isolated and approval-gated;
- hidden-city rejects round-trip/native-multi tickets, known checked baggage
  and all booking actions;
- unknown baggage/visa/transfer values remain unknown;
- buy-timing under any sample/date/week threshold returns `insufficient_data`;
- history series reject mismatched return date, stay, baggage, seller or fare
  product according to aggregation mode;
- error fare threshold boundary is `suspected_anomaly`, never guarantee;
- stale/missing FX or fee provenance returns `not_comparable`.

### 16.2 Persistence and worker

- household A cannot read/run/cancel household B's plan;
- execute idempotency prevents duplicate runs;
- consumed approval cannot start a different run and rerun requires a new
  revision/approval;
- cloning a consumed/expired revision creates a refreshed successor without
  mutating the source and can be executed only after a new approval;
- plan version mismatch rejects stale approval;
- concurrent edit supersedes the old revision without mutating its run;
- cancel targets an explicit run and latest-run ordering is deterministic;
- per-operation lease/retry does not duplicate candidates or lose budget;
- start/poll continuation resumes without exposing provider refs;
- worker restart resumes the next durable phase;
- cancellation stops new provider calls;
- partial results survive provider 403/429/timeout;
- migration upgrade preserves existing v1 data.

### 16.3 API and browser E2E

- free text → clarification → plan card;
- preset → same plan schema;
- plan edit increments version;
- approve → queued → running → completed results;
- quick result → explicit full-scan expansion;
- hidden-city acknowledgement flow;
- progress survives reload;
- partial provider error remains readable;
- mobile layout exposes plan, cancel and result sections.

### 16.4 Provider contracts

CI uses sanitized fixtures only. A separate summary-only Aviasales smoke checks
calendar and exact search without prices, refs, signatures, markers or booking
URLs in output.

## 17. Acceptance scenarios

1. `СПб → Франция`, no date: asks for period and offers rolling 90 days.
2. Rolling 90 days: builds a quick plan, waits for confirmation, shortlists
   French airports/dates, exact-verifies candidates and returns separate normal
   and risky sections.
3. `Проверить всю Францию`: creates a new plan version with all commercial
   airports and a visible larger budget.
4. `Куда угодно из СПб`: uses discovery/calendar evidence, then exact-verifies
   the best destinations.
5. Open-jaw and multi-city: preserves all legs and returns through-ticket,
   unknown-protection and split variants separately.
6. Provider rate limit: waits according to policy or finishes partial without
   losing confirmed candidates.
7. No price history: states `Недостаточно данных` and offers a watch.
8. Hidden-city: cannot execute until the user accepts the dedicated warning.

## 18. Implementation sequence

Implementation should use vertical, test-first slices while preserving the
approved final scope:

1. domain contracts, generic scopes and plan estimator;
2. persistence, API plan lifecycle and plan-card UI;
3. durable executor with calendar shortlist and exact through-ticket search;
4. country/region/anywhere and quick/full expansion;
5. split/self-transfer composer and ranking;
6. open-jaw/multi-city;
7. hidden-city isolated phase;
8. history/anomaly/currency presets;
9. browser E2E, docs, migrations, security and release gate.

## 19. Definition of Done

The feature is complete only when:

- free text and every preset create the same typed plan contract;
- no provider call happens before the version-bound confirmation;
- quick/full, generic scopes and all trip shapes work through production paths;
- through, split, self-transfer and hidden-city results are correctly separated;
- arithmetic uses integer minor units and deterministic FX only;
- jobs are idempotent, resumable, cancellable and household-isolated;
- partial failures are visible and retain successful results;
- history/error-fare/currency statements meet their evidence rules;
- migrations, unit/integration/contract/API/browser tests pass;
- docs and `.env.example` describe the exact runtime;
- summary-only live Aviasales smoke passes or records a typed external failure.
