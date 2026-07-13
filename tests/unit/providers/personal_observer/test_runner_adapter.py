from __future__ import annotations

from pathlib import Path

import pytest

from flight_hunter.application.personal_observations import (
    PersonalObservationCode,
    PersonalObservationRunnerError,
)
from flight_hunter.domain.observation import ObservationErrorCode, ObservationStatus
from flight_hunter.domain.offers import SearchIntent
from flight_hunter.providers.personal_observer.adapter import PersonalObserverRunnerAdapter
from flight_hunter.providers.personal_observer.runner import (
    PersonalObserverError,
    PersonalObserverErrorCode,
)


def test_adapter_maps_playwright_unavailable_to_terminal_runtime_error() -> None:
    adapter = PersonalObserverRunnerAdapter(PlaywrightUnavailableRunner())

    with pytest.raises(PersonalObservationRunnerError) as exc:
        adapter.observe(
            source_id="tutu",
            intent=SearchIntent(
                origin="MOW",
                destination="IST",
                departure_date="2026-09-10",
                return_date="2026-09-20",
                passengers=1,
                currency="RUB",
            ),
            user_action=True,
        )

    assert exc.value.code == PersonalObservationCode.RUNNER_FAILED
    assert exc.value.status == ObservationStatus.FAILED
    assert exc.value.error_code == ObservationErrorCode.BROWSER_RUNTIME_UNAVAILABLE
    assert "playwright is not installed" in exc.value.message


class PlaywrightUnavailableRunner:
    def observe(
        self,
        *,
        source_id: str,
        intent: SearchIntent,
        user_action: bool,
        fixture_html_path: Path | None = None,
        progress_callback=None,
        checkpoint_callback=None,
    ):
        raise PersonalObserverError(
            PersonalObserverErrorCode.PLAYWRIGHT_UNAVAILABLE,
            "playwright is not installed; sync the scraping dependency group",
        )
