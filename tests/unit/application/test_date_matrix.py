from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID

import pytest

from flight_hunter.application.date_matrix import (
    DateMatrixCell,
    DateMatrixPlanner,
    DateMatrixRequest,
)
from flight_hunter.domain.agent_evidence import (
    ConfirmationState,
    DiscoverySignal,
    DiscoverySource,
    require_confirmed_rank_input,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness


def test_round_trip_flex_three_days_creates_compatible_seven_by_seven_matrix() -> None:
    planner = DateMatrixPlanner()

    matrix = planner.plan(
        DateMatrixRequest(
            departure_date=date(2026, 10, 12),
            return_date=date(2026, 10, 19),
            flexibility_days=3,
            min_stay_days=None,
            max_stay_days=None,
        )
    )

    assert len(matrix.cells) == 49
    assert matrix.cells[0].departure_date == date(2026, 10, 9)
    assert matrix.cells[0].return_date == date(2026, 10, 16)
    assert matrix.cells[-1].departure_date == date(2026, 10, 15)
    assert matrix.cells[-1].return_date == date(2026, 10, 22)
    assert matrix.provider_calls_required == 0


def test_round_trip_matrix_filters_by_stay_length() -> None:
    planner = DateMatrixPlanner()

    matrix = planner.plan(
        DateMatrixRequest(
            departure_date=date(2026, 10, 12),
            return_date=date(2026, 10, 19),
            flexibility_days=3,
            min_stay_days=6,
            max_stay_days=8,
        )
    )

    assert matrix.cells
    assert all(6 <= cell.stay_days <= 8 for cell in matrix.cells if cell.stay_days is not None)
    assert len(matrix.cells) < 49


def test_flexibility_is_capped_to_prevent_unbounded_combinations() -> None:
    planner = DateMatrixPlanner(max_flexibility_days=7)

    with pytest.raises(ValueError, match="flexibility_days"):
        planner.plan(
            DateMatrixRequest(
                departure_date=date(2026, 10, 12),
                return_date=date(2026, 10, 19),
                flexibility_days=8,
                min_stay_days=None,
                max_stay_days=None,
            )
        )


def test_calendar_discovery_overlay_stays_indicative_in_typed_matrix_cell() -> None:
    planner = DateMatrixPlanner()
    matrix = planner.plan(
        DateMatrixRequest(
            departure_date=date(2026, 9, 15),
            return_date=None,
            flexibility_days=1,
            min_stay_days=None,
            max_stay_days=None,
        )
    )
    signal = DiscoverySignal(
        id=UUID("7acdbeb0-8a80-56d4-9684-386f18529659"),
        provider_id="aviasales_search",
        origin="SVO",
        destination="LED",
        departure_date=date(2026, 9, 15),
        return_date=None,
        observed_amount=Money(432_100, "RUB"),
        observed_at=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
        source_kind=DiscoverySource.CALENDAR,
        passengers=1,
    )

    overlaid = planner.overlay_discovery(
        matrix,
        signals=(signal,),
        freshness=Freshness.LIVE,
    )

    priced = next(cell for cell in overlaid.cells if cell.discovery_signal is not None)
    assert overlaid.priced is True
    assert priced.discovery_signal is signal
    assert priced.evidence_kind == "discovery_signal"
    assert priced.confirmation_state is ConfirmationState.INDICATIVE
    assert priced.requires_live_confirmation is True
    assert priced.freshness is Freshness.LIVE


def test_discovery_signal_cannot_enter_confirmed_ranking_or_non_discovery_overlay() -> None:
    planner = DateMatrixPlanner()
    matrix = planner.plan(
        DateMatrixRequest(
            departure_date=date(2026, 9, 15),
            return_date=None,
            flexibility_days=0,
            min_stay_days=None,
            max_stay_days=None,
        )
    )
    signal = DiscoverySignal(
        id=UUID("7acdbeb0-8a80-56d4-9684-386f18529659"),
        provider_id="aviasales_search",
        origin="SVO",
        destination="LED",
        departure_date=date(2026, 9, 15),
        return_date=None,
        observed_amount=Money(432_100, "RUB"),
        observed_at=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
        source_kind=DiscoverySource.CALENDAR,
    )

    with pytest.raises(TypeError, match="confirmed evidence required"):
        require_confirmed_rank_input(signal)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="DiscoverySignal"):
        planner.overlay_discovery(
            matrix,
            signals=(cast(Any, object()),),
            freshness=Freshness.LIVE,
        )


def test_typed_date_matrix_cell_rejects_mismatched_discovery_dates() -> None:
    signal = DiscoverySignal(
        id=UUID("7acdbeb0-8a80-56d4-9684-386f18529659"),
        provider_id="aviasales_search",
        origin="SVO",
        destination="LED",
        departure_date=date(2026, 9, 15),
        return_date=None,
        observed_amount=Money(432_100, "RUB"),
        observed_at=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
        source_kind=DiscoverySource.CALENDAR,
    )

    with pytest.raises(ValueError, match="dates must match"):
        DateMatrixCell(
            departure_date=date(2026, 9, 16),
            return_date=None,
            stay_days=None,
            discovery_signal=signal,
            freshness=Freshness.LIVE,
        )
