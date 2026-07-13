from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from flight_hunter.application.personal_observations import (
    PersonalObservationCode,
    PersonalObservationRunnerError,
    PersonalObservationRunnerResult,
)
from flight_hunter.domain.observation import (
    ObservationErrorCode,
    ObservationStatus,
    OperatorCheckpointDecision,
)
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverError,
    PersonalObserverErrorCode,
    PersonalObserverRunner,
)


class PersonalObserverRunnerAdapter:
    def __init__(self, runner: PersonalObserverRunner) -> None:
        self._runner = runner

    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback: Callable[[ObservationStatus], None] | None = None,
        checkpoint_callback: Callable[[], OperatorCheckpointDecision] | None = None,
    ) -> PersonalObservationRunnerResult:
        try:
            result = self._runner.observe(
                source_id=source_id,
                intent=intent,
                user_action=user_action,
                fixture_html_path=fixture_html_path,
                progress_callback=progress_callback,
                checkpoint_callback=checkpoint_callback,
            )
        except PersonalObserverError as exc:
            raise _runner_error(exc) from exc
        return PersonalObservationRunnerResult(offers=result.extraction.offers)


def _runner_error(error: PersonalObserverError) -> PersonalObservationRunnerError:
    if error.code == PersonalObserverErrorCode.PARSER_NO_OFFERS:
        return PersonalObservationRunnerError(
            PersonalObservationCode.PARSER_NO_OFFERS,
            error.message,
            status=ObservationStatus.NO_PRICE_FOUND,
        )
    if error.code == PersonalObserverErrorCode.SOURCE_CHALLENGE:
        return PersonalObservationRunnerError(
            PersonalObservationCode.SOURCE_CHALLENGE,
            error.message,
            status=ObservationStatus.SOURCE_CHALLENGE,
        )
    if error.code == PersonalObserverErrorCode.SELECTOR_DRIFT:
        return PersonalObservationRunnerError(
            PersonalObservationCode.SELECTOR_DRIFT,
            error.message,
            status=ObservationStatus.SELECTOR_DRIFT,
        )
    if error.code == PersonalObserverErrorCode.OPERATOR_ABORTED:
        return PersonalObservationRunnerError(
            PersonalObservationCode.OPERATOR_ABORTED,
            error.message,
            status=ObservationStatus.NEEDS_HUMAN,
        )
    if error.code in {
        PersonalObserverErrorCode.OBSERVER_DISABLED,
        PersonalObserverErrorCode.SOURCE_NOT_OBSERVABLE,
        PersonalObserverErrorCode.HOST_NOT_ALLOWED,
    }:
        return PersonalObservationRunnerError(
            PersonalObservationCode.RUNNER_FAILED,
            error.message,
            status=ObservationStatus.POLICY_DENIED,
        )
    if error.code == PersonalObserverErrorCode.PLAYWRIGHT_UNAVAILABLE:
        return PersonalObservationRunnerError(
            PersonalObservationCode.RUNNER_FAILED,
            error.message,
            status=ObservationStatus.FAILED,
            error_code=ObservationErrorCode.BROWSER_RUNTIME_UNAVAILABLE,
        )
    if error.code == PersonalObserverErrorCode.NAVIGATION_FAILED:
        return PersonalObservationRunnerError(
            PersonalObservationCode.RUNNER_FAILED,
            error.message,
            status=ObservationStatus.SOURCE_UNAVAILABLE,
        )
    if error.code == PersonalObserverErrorCode.PROFILE_LOCKED:
        return PersonalObservationRunnerError(
            PersonalObservationCode.RUNNER_FAILED,
            error.message,
            status=ObservationStatus.SOURCE_UNAVAILABLE,
        )
    return PersonalObservationRunnerError(
        PersonalObservationCode.RUNNER_FAILED,
        error.message,
        status=ObservationStatus.FAILED,
    )
