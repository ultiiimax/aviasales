# ADR 0101: Personal observer Playwright unavailable retry

Date: 2026-06-29

## Status

Accepted.

## Context

The Personal Browser Observer depends on a local Playwright Chromium runtime. A missing or temporarily
unavailable runtime is an operator/environment problem, not evidence that the source page has no
price, the provider policy denied access, or the parser is permanently broken.

Before this decision, `PersonalObserverErrorCode.PLAYWRIGHT_UNAVAILABLE` fell through the adapter's
generic error mapping and became a terminal `failed` job. That made worker summaries and source
health under-report a recoverable runtime setup issue.

## Decision

`PersonalObserverRunnerAdapter` now maps `PLAYWRIGHT_UNAVAILABLE` to
`ObservationStatus.SOURCE_UNAVAILABLE`, the same retryable status used for navigation/runtime
unavailability.

The application service already treats `SOURCE_UNAVAILABLE` as retryable while attempts and the job
deadline allow it. The worker therefore schedules a retry, records source health as
`retry_scheduled`, and does not persist offers.

## Consequences

- A local browser dependency outage no longer becomes terminal `failed` on the first attempt.
- Policy-denied, parser and challenge errors remain non-retryable.
- Tests use fake runner errors only; CI still does not visit live travel sites or require a broken
  Playwright installation.

## Verification

- Adapter tests cover `PLAYWRIGHT_UNAVAILABLE` mapping to retryable `SOURCE_UNAVAILABLE`.
- Worker tests cover queued browser jobs retrying with source health `retry_scheduled` and no
  persisted offers when the runtime is unavailable.
