from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from flight_hunter.application.agent_hidden_city import (
    HIDDEN_CITY_WARNING_VERSION,
    HiddenCityActionability,
    HiddenCityContext,
    HiddenCityRejectionCode,
    classify_hidden_city,
)
from flight_hunter.application.agent_reporting import CandidateRanker
from flight_hunter.domain.agent_evidence import (
    CheckedBaggageState,
    ConfirmedOfferEvidence,
    ProtectionStatus,
)
from flight_hunter.domain.agent_search import TicketShape
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary


def test_hidden_city_warning_version_is_explicit_and_stable() -> None:
    assert HIDDEN_CITY_WARNING_VERSION == "hidden-city-v1"


def test_only_final_one_way_leg_with_desired_intermediate_airport_is_eligible() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.NOT_INCLUDED),
        "CDG",
        HiddenCityContext(plan_leg_index=1, final_plan_leg_index=1),
    )

    assert decision.rejection_code is None
    assert decision.candidate is not None
    assert decision.candidate.desired_airport == "CDG"
    assert decision.candidate.ticketed_destination == "FCO"
    assert tuple(segment.destination for segment in decision.candidate.flown_segments) == ("CDG",)
    assert tuple(segment.destination for segment in decision.candidate.skipped_segments) == ("FCO",)
    assert decision.candidate.actionability is HiddenCityActionability.ELIGIBLE
    assert not decision.candidate.booking_action_available
    assert not decision.candidate.watch_available


def test_non_final_plan_leg_is_rejected() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.NOT_INCLUDED),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=1),
    )

    assert decision.candidate is None
    assert decision.rejection_code is HiddenCityRejectionCode.NOT_FINAL_PLAN_LEG


def test_desired_airport_must_be_intermediate_not_ticketed_destination() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.NOT_INCLUDED),
        "FCO",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.candidate is None
    assert decision.rejection_code is HiddenCityRejectionCode.DESIRED_AIRPORT_NOT_INTERMEDIATE


@pytest.mark.parametrize("shape", (TicketShape.ROUND_TRIP, TicketShape.NATIVE_MULTI))
def test_round_trip_and_native_multi_ticket_products_are_rejected(shape: TicketShape) -> None:
    decision = classify_hidden_city(
        _ticket(
            ticket_shape=shape,
            return_date=date(2026, 9, 20) if shape is TicketShape.ROUND_TRIP else None,
            checked_baggage=CheckedBaggageState.NOT_INCLUDED,
        ),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.candidate is None
    assert decision.rejection_code is HiddenCityRejectionCode.ONE_WAY_TICKET_REQUIRED


def test_later_planned_airport_dependency_is_rejected() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.NOT_INCLUDED),
        "CDG",
        HiddenCityContext(
            plan_leg_index=1,
            final_plan_leg_index=1,
            intended_later_airports=("FCO",),
        ),
    )

    assert decision.candidate is None
    assert decision.rejection_code is HiddenCityRejectionCode.LATER_JOURNEY_DEPENDENCY


def test_known_checked_baggage_is_rejected() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.INCLUDED),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.candidate is None
    assert decision.rejection_code is HiddenCityRejectionCode.CHECKED_BAGGAGE_KNOWN


def test_unknown_baggage_is_research_only_and_never_actionable() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.UNKNOWN),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.rejection_code is None
    assert decision.candidate is not None
    assert decision.candidate.actionability is HiddenCityActionability.RESEARCH_ONLY_NOT_ACTIONABLE
    assert not decision.candidate.booking_action_available
    assert not decision.candidate.watch_available


def test_hidden_city_warnings_cover_baggage_cancellation_and_contract_risk() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.UNKNOWN),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.candidate is not None
    warning_codes = {warning.code for warning in decision.candidate.warnings}
    assert warning_codes == {
        "checked_baggage_continues",
        "later_segments_may_be_cancelled",
        "carrier_contract_risk",
    }


def test_hidden_city_candidate_cannot_enter_normal_ranker() -> None:
    decision = classify_hidden_city(
        _ticket(checked_baggage=CheckedBaggageState.NOT_INCLUDED),
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )

    assert decision.candidate is not None
    with pytest.raises(TypeError, match="confirmed evidence required"):
        CandidateRanker().rank((decision.candidate,), comparison_currency="RUB")  # type: ignore[arg-type]


def _ticket(
    *,
    ticket_shape: TicketShape = TicketShape.ONE_WAY,
    return_date: date | None = None,
    checked_baggage: CheckedBaggageState,
) -> ConfirmedOfferEvidence:
    observed_at = datetime(2026, 7, 16, 12, tzinfo=UTC)
    segments = (
        FlightSegmentSummary(
            airline_code="FV",
            airline_name="Fixture Air",
            flight_number="FV100",
            origin="LED",
            destination="CDG",
            depart_at="2026-09-10 08:00",
            arrive_at="2026-09-10 11:00",
            depart_at_utc=datetime(2026, 9, 10, 5, tzinfo=UTC),
            arrive_at_utc=datetime(2026, 9, 10, 9, tzinfo=UTC),
        ),
        FlightSegmentSummary(
            airline_code="FV",
            airline_name="Fixture Air",
            flight_number="FV200",
            origin="CDG",
            destination="FCO",
            depart_at="2026-09-10 14:00",
            arrive_at="2026-09-10 16:00",
            depart_at_utc=datetime(2026, 9, 10, 12, tzinfo=UTC),
            arrive_at_utc=datetime(2026, 9, 10, 14, tzinfo=UTC),
        ),
    )
    return ConfirmedOfferEvidence(
        id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        provider_id="aviasales_search",
        provider_offer_id="hidden-fixture",
        origin="LED",
        destination="FCO",
        departure_date=date(2026, 9, 10),
        return_date=return_date,
        total_amount=Money(19_000, "RUB"),
        passengers=1,
        observed_at=observed_at,
        segment_ids=("segment-1", "segment-2"),
        segments=segments,
        protection_status=ProtectionStatus.UNKNOWN,
        ticket_shape=ticket_shape,
        checked_baggage=checked_baggage,
    )
