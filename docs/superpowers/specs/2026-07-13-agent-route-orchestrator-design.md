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
- direct and protected-connection tickets returned by Aviasales;
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
Strategies: direct, protected, split, self-transfer
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
4. protected-ticket extraction;
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
    PROTECTED_CONNECTION = "protected_connection"
    SPLIT_TICKET = "split_ticket"
    SELF_TRANSFER = "self_transfer"
    HIDDEN_CITY = "hidden_city"
```

`TravelIntent` is provider-neutral and contains ordered requested legs. Each
leg has origin/destination `LocationScope` and a `DateConstraint`. Multi-city
and open-jaw are represented as explicit ordered legs instead of special
provider DTO fields.

### 5.2 Search plan

`AgentSearchPlan` contains:

- UUID, household/user ownership and version;
- normalized intent and unresolved choices;
- expanded airport scopes or expansion rules;
- coverage mode: `quick` or `full`;
- enabled strategies and risk gates;
- ranking profile;
- request budget and deadline;
- estimated calendar/exact calls;
- current status and timestamps;
- prompt/parser version and deterministic plan-builder version.

Plan states:

```text
draft
  -> awaiting_approval
  -> queued
  -> running
  -> completed | partial | failed | cancelled | expired
```

Editing a plan creates a new version. Approval applies only to the exact
version displayed to the user.

### 5.3 Run and stage records

`AgentPlanRun` stores idempotency key, attempts, deadline, status, counters,
next retry and terminal code. `AgentPlanStage` stores one row per phase with
status, attempt counts, provider-call counts and sanitized error summary.

Candidate observations are append-only. Re-ranking creates a new ranking
snapshot without rewriting raw normalized evidence.

## 6. Geographic expansion

Location scopes resolve through a provider-neutral airport catalog:

- airport → one IATA airport;
- city → all relevant commercial airports for that city;
- country → commercial airports in that country;
- region → countries and their commercial airports;
- anywhere → destinations discoverable from calendar/hot-offer/reference
  sources, followed by exact verification.

The catalog records provenance and commercial relevance. A quick scan orders
airports by route coverage, commercial relevance, nearby distance and calendar
evidence. A full scan includes every commercial airport in the approved scope,
subject to the displayed hard budget.

Origin scopes use the same mechanism, so `Москва и аэропорты рядом → Южная
Европа` is not a special case.

## 7. Search algorithm

### 7.1 Phase A — scope and budget

Resolve scopes, remove impossible/closed/non-commercial airports, deduplicate
city and airport aliases, calculate the Cartesian search surface and estimate
calls before approval.

Initial configurable defaults:

| Mode | Calendar calls | Exact calls | Deadline |
|---|---:|---:|---:|
| quick | up to 40 | up to 20 | 10 minutes |
| full | scope-dependent, hard cap 240 total calls | plan-derived | 30 minutes |

Provider-specific RPM and circuit-breaker policies override these ceilings.
The plan is rejected as `budget_too_large` rather than silently truncating an
approved full scan. The user may approve a smaller scope or explicit larger
budget later.

### 7.2 Phase B — calendar shortlist

For range/flexible/90-day requests, calendar endpoints gather indicative date
and airport candidates. Calendar values never become final ticket results.
Candidates are ordered by observed amount and data recency, then the best
airport/date pairs move to exact search.

Exact-date requests skip this phase when no scope discovery is required.

### 7.3 Phase C — exact live search

The Aviasales adapter performs exact searches for approved pairs. Provider
responses supply direct flights and protected itineraries with connection
segments. Mapping stays inside the provider boundary.

Only exact ticket-bearing results can become confirmed priced candidates.
Calendar-only rows remain indicative and visibly unconfirmed.

### 7.4 Phase D — split-ticket and self-transfer

Candidate hubs come from:

- connection airports observed in protected results;
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

Native provider multi-direction search is used when supported. The composer may
also combine confirmed per-leg offers. It keeps journey order, passenger mix,
currency evidence, connection constraints and ticket boundaries explicit.

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
- never generate a purchase action automatically;
- warn that checked baggage may continue to the ticketed destination;
- warn that later/return segments may be cancelled;
- are not described as safe or recommended.

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

Any later statistical recommendation must publish sample count, history span,
confidence and calculation version.

### 9.4 Error fare

A fare is labelled `suspected_anomaly`, never guaranteed error fare. Detection
requires a sufficient comparable sample and a deterministic deviation rule.
External forums/bots/channels may be researched through configured web-search
connectors, but their text is untrusted data and is not a price source.

### 9.5 Country site and currency

Comparison requires a stable same-flight identity, observed amounts in each
currency, deterministic timestamped FX and configured card-fee assumptions.
Without those inputs the UI shows side-by-side amounts and
`not_comparable`. The agent never bypasses geo/access controls and never buys.

## 10. Application components

- `IntentParser`: deterministic parser plus optional typed model overlay.
- `AgentPlanBuilder`: validates intent and creates provider-neutral plans.
- `ScopeResolver`: expands airport/city/country/region/anywhere.
- `PlanEstimator`: computes call counts, budgets and deadline estimate.
- `PlanApprovalService`: validates ownership, plan version and risk gates.
- `PlanExecutor`: durable orchestration state machine.
- `ProviderSearchGateway`: policy-checked exact/calendar provider port.
- `RouteComposer`: split/self-transfer/open-jaw/multi-city candidates.
- `HiddenCityResearchService`: isolated high-risk expansion.
- `CandidateRanker`: deterministic ranking snapshots.
- `FactReportBuilder`: final user-facing factual explanation.

Delivery adapters remain thin. Provider DTOs do not enter these contracts.

## 11. Persistence

Add forward-only migrations for:

- `agent_search_plans`;
- `agent_search_plan_versions` or immutable version rows;
- `agent_plan_runs`;
- `agent_plan_stages`;
- `agent_candidate_observations`;
- `agent_ranking_snapshots`.

Every query includes household scope. Runs have unique idempotency constraints.
Stage claims use the existing worker lock/retry conventions. Candidate evidence
is append-only and may reference normalized existing offers instead of copying
secret provider refs.

## 12. API contracts

Proposed endpoints:

```text
POST   /api/v1/agent/search-plans
GET    /api/v1/agent/search-plans/{plan_id}
PATCH  /api/v1/agent/search-plans/{plan_id}
POST   /api/v1/agent/search-plans/{plan_id}/execute
POST   /api/v1/agent/search-plans/{plan_id}/cancel
GET    /api/v1/agent/search-plans/{plan_id}/runs/latest
GET    /api/v1/agent/search-plans/{plan_id}/results
```

`execute` requires bearer session, household ownership, `expected_version`, an
idempotency key and explicit hidden-city acknowledgement when applicable. It
records approval and queues the run atomically.

`POST /api/v1/agent/chat/turn` remains compatible but returns a proposed plan
reference instead of executing live searches. `/api/v1/agent/plan` and presets
delegate to the new builder during migration.

API errors use stable codes such as:

- `agent_plan_incomplete`;
- `agent_plan_stale`;
- `agent_plan_budget_too_large`;
- `agent_plan_approval_required`;
- `agent_hidden_city_ack_required`;
- `agent_run_already_active`;
- `agent_run_deadline_exceeded`;
- `agent_run_partial`;
- `agent_run_cancelled`.

## 13. Reliability and errors

Every run has:

- idempotency key;
- deadline and provider-call budget;
- durable attempts and next retry;
- distributed/SQLite-safe claim lock;
- graceful cancellation;
- per-stage partial success;
- bounded retry respecting `Retry-After` and circuit breakers;
- restart recovery;
- sanitized trace events.

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
- airport/city/country/region/anywhere scopes;
- exact/flexible/range/90-day constraints;
- one-way/round-trip/open-jaw/multi-city plans;
- provider-protected connections map without DTO leakage;
- split price is accepted only with every segment confirmed;
- infeasible or overlapping self-transfers are rejected;
- airport-change buffer and unknown ground cost are visible;
- mixed-currency routes require deterministic FX;
- hidden-city is isolated and approval-gated;
- unknown baggage/visa/transfer values remain unknown;
- buy-timing without history returns `insufficient_data`;
- error fare is `suspected_anomaly`, never guarantee.

### 16.2 Persistence and worker

- household A cannot read/run/cancel household B's plan;
- execute idempotency prevents duplicate runs;
- plan version mismatch rejects stale approval;
- stage retries do not duplicate candidates;
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
5. Open-jaw and multi-city: preserves all legs and returns protected and split
   variants separately.
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
