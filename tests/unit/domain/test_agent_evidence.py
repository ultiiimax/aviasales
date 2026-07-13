from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest

from flight_hunter.domain.agent_evidence import (
    ComposedRouteCandidate,
    ConfirmationState,
    ConfirmedOfferEvidence,
    DiscoverySignal,
    DiscoverySource,
    ProtectionStatus,
    require_confirmed_rank_input,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary

OBSERVED_AT = datetime(2026, 7, 13, 12, tzinfo=UTC)


def _segment(
    origin: str = "LED",
    destination: str = "CDG",
) -> FlightSegmentSummary:
    return FlightSegmentSummary(
        airline_code="SU",
        airline_name="Aeroflot",
        flight_number="SU123",
        origin=origin,
        destination=destination,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T13:00:00+02:00",
    )


def _discovery_signal() -> DiscoverySignal:
    return DiscoverySignal(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 10),
        return_date=None,
        observed_amount=Money(1_230_000, "RUB"),
        observed_at=OBSERVED_AT,
        source_kind=DiscoverySource.CALENDAR,
    )


def _confirmed_offer() -> ConfirmedOfferEvidence:
    return ConfirmedOfferEvidence(
        id=UUID("00000000-0000-0000-0000-000000000002"),
        provider_id="aviasales_search",
        provider_offer_id="ticket-fingerprint-1",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 10),
        return_date=None,
        total_amount=Money(1_330_000, "RUB"),
        passengers=2,
        observed_at=OBSERVED_AT,
        segment_ids=["segment-1"],  # type: ignore[arg-type]
        segments=[_segment()],  # type: ignore[arg-type]
        protection_status=ProtectionStatus.UNKNOWN,
        seller_name="Example seller",
        baggage_summary=None,
    )


def _composed_candidate() -> ComposedRouteCandidate:
    return ComposedRouteCandidate(
        id=UUID("00000000-0000-0000-0000-000000000003"),
        component_evidence_ids=[  # type: ignore[arg-type]
            UUID("00000000-0000-0000-0000-000000000002")
        ],
        total_amount=Money(1_330_000, "RUB"),
        passengers=2,
        observed_at=OBSERVED_AT,
        segment_ids=["segment-1"],  # type: ignore[arg-type]
        segments=[_segment()],  # type: ignore[arg-type]
        protection_status=ProtectionStatus.SELF_TRANSFER,
    )


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

    assert signal.confirmation_state is ConfirmationState.INDICATIVE
    with pytest.raises(TypeError, match="confirmed evidence required"):
        require_confirmed_rank_input(signal)  # type: ignore[arg-type]


def test_confirmed_and_composed_records_are_the_only_confirmed_rank_inputs() -> None:
    offer = _confirmed_offer()
    candidate = _composed_candidate()

    assert offer.confirmation_state is ConfirmationState.CONFIRMED
    assert candidate.confirmation_state is ConfirmationState.CONFIRMED
    assert require_confirmed_rank_input(offer) is offer
    assert require_confirmed_rank_input(candidate) is candidate
    assert offer.segment_ids == ("segment-1",)
    assert offer.segments == (_segment(),)
    assert candidate.component_evidence_ids == (offer.id,)
    assert candidate.segment_ids == ("segment-1",)


@pytest.mark.parametrize(
    "record",
    (_discovery_signal(), _confirmed_offer(), _composed_candidate()),
)
def test_every_evidence_record_rejects_naive_observed_at(record: object) -> None:
    with pytest.raises(ValueError, match="observed_at must be timezone-aware"):
        replace(record, observed_at=datetime(2026, 7, 13, 12))


@pytest.mark.parametrize(
    "record",
    (_discovery_signal(), _confirmed_offer(), _composed_candidate()),
)
def test_every_evidence_record_requires_positive_passenger_count(record: object) -> None:
    with pytest.raises(ValueError, match="passengers must be a positive integer"):
        replace(record, passengers=0)


def test_evidence_amounts_must_be_validated_money_values() -> None:
    with pytest.raises(TypeError, match="observed_amount must be Money"):
        replace(_discovery_signal(), observed_amount=1_230_000)
    with pytest.raises(TypeError, match="total_amount must be Money"):
        replace(_confirmed_offer(), total_amount=1_330_000)
    with pytest.raises(ValueError, match="currency must be an ISO 4217"):
        replace(_composed_candidate(), total_amount=Money(1_330_000, "RU"))


def test_confirmed_segment_ids_are_ordered_immutable_and_match_segments() -> None:
    with pytest.raises(ValueError, match="segment_ids must match segments"):
        replace(_confirmed_offer(), segment_ids=("segment-1", "segment-2"))
    with pytest.raises(ValueError, match="segment_ids must be unique"):
        replace(
            _composed_candidate(),
            segment_ids=("segment-1", "segment-1"),
            segments=(_segment(), _segment()),
        )
