# ADR 0100: Personal observation claimed expiry guard

Date: 2026-06-29

## Status

Accepted.

## Context

Personal Browser Observer jobs have a short deadline because browser-observed fares are user-action
facts, not provider guarantees. The queued direct-run path already rejected jobs that expired before
browser launch, but a worker can claim a job shortly before expiry and then spend time in a visible
browser checkpoint, navigation, parsing or persistence. In that window an expired job could still
persist `browser_observed` offers.

Stale active job recovery also used a generic `failed`/`timed_out` terminal state for jobs that had
already passed their deadline, which made expired work look like a runtime timeout.

## Decision

`PersonalObservationService.run_claimed_job()` now checks the job deadline:

- before invoking the runner;
- again after the runner returns and before any offers are persisted.

If the deadline has passed, the job is marked `expired` with `ObservationErrorCode.EXPIRED`, the
runner is skipped when possible, and no offers are persisted.

`BrowserObservationJobRepository.recover_stale_running()` now marks stale active jobs whose
deadline has passed as `expired`/`expired` instead of `failed`/`timed_out`.

## Consequences

- Browser observations cannot become fresh-looking persisted offers after their job deadline.
- Visible checkpoint delays and slow parser/runtime paths fail closed at persistence time.
- Worker stale recovery, direct-run execution and claimed-job execution now use the same terminal
  expiry semantics.
- No migration is needed because the existing status/error-code enums and columns already support
  `expired`.

## Verification

- Application tests cover expired queued jobs, expired claimed jobs before runner invocation, and
  jobs that expire after the runner returns but before persistence.
- Persistence tests cover stale active job recovery after deadline.
