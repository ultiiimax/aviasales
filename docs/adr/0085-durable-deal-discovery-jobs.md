# ADR 0085: Durable Deal Discovery Jobs

Date: 2026-06-29

## Status

Accepted

## Context

Deal discovery uses optional local SearXNG search and Crawl4AI markdown extraction to find
manual-verification deal hints. Running that work synchronously in an API request makes the
request path dependent on crawler latency, retry behavior and source failures.

Deal discovery results are not prices or availability. They are untrusted external page hints and
must remain separate from ranked priced offers.

## Decision

Add a durable `deal_discovery_jobs` queue with scoped idempotency, worker leases, attempts,
deadline, retry scheduling and terminal status.

`POST /api/v1/deals/discovery-jobs` only validates an authenticated household/user request,
requires `Idempotency-Key`, creates or replays a queued job, and returns `202 Accepted`.

`GET /api/v1/deals/discovery-jobs/{job_id}` is household/user scoped and returns job status plus
persisted non-expired candidates for the job search id.

`flight-hunter-worker` now recovers stale deal-discovery leases, claims due jobs, runs
`DealDiscoveryService`, persists candidates with TTL, records source health events, and reports
deal job counters in its heartbeat summary. It does not create discovery jobs by itself.

## Consequences

- API requests no longer need to block on SearXNG/Crawl4AI for the durable path.
- Duplicate user clicks can safely replay the same job with scoped idempotency.
- Source failures are classified as retryable job failures instead of false prices.
- Deal candidates remain manual-verification-only and never enter priced-offer ranking.
- A production deployment still needs worker-lane supervision and crawler egress hardening.

## Verification

- `tests/unit/application/test_deal_discovery_jobs.py`
- `tests/unit/persistence/test_deal_discovery_job_repository.py`
- `tests/unit/api/test_api_app.py`
- `tests/unit/ops/test_worker_command.py`
