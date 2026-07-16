from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from flight_hunter.application.agent_composition import (
    AirportChangeAssumption,
    CompositionPolicy,
    CompositionRejectionCode,
    CompositionRequest,
    ConnectionPolicy,
    FrozenCompositionLeg,
    LegEvidencePool,
    RouteComposer,
    assess_connection,
    connection_is_feasible,
)
from flight_hunter.domain.agent_evidence import (
    ConfirmedOfferEvidence,
    DiscoverySignal,
    DiscoverySource,
    PriceComparisonStatus,
    ProtectionStatus,
    UnknownCostKind,
)
from flight_hunter.domain.agent_search import TripShape
from flight_hunter.domain.money import MAX_MONEY_MINOR_UNITS, Money
from flight_hunter.domain.offers import (
    FlightSegmentSummary,
    PassengerMix,
    PriceBasis,
)

OBSERVED_AT = datetime(2026, 7, 16, 12, tzinfo=UTC)
NAMESPACE = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _segment(
    origin: str,
    destination: str,
    depart_at: str,
    arrive_at: str,
    *,
    suffix: str = "1",
) -> FlightSegmentSummary:
    try:
        depart_at_utc = datetime.fromisoformat(depart_at.replace("Z", "+00:00"))
        arrive_at_utc = datetime.fromisoformat(arrive_at.replace("Z", "+00:00"))
    except ValueError:
        depart_at_utc = arrive_at_utc = None
    if (
        depart_at_utc is None
        or arrive_at_utc is None
        or depart_at_utc.tzinfo is None
        or arrive_at_utc.tzinfo is None
        or depart_at_utc.utcoffset() is None
        or arrive_at_utc.utcoffset() is None
    ):
        depart_at_utc = arrive_at_utc = None
    return FlightSegmentSummary(
        airline_code="FH",
        airline_name="Flight Hunter fixture",
        flight_number=f"FH{suffix}",
        origin=origin,
        destination=destination,
        depart_at=depart_at,
        arrive_at=arrive_at,
        depart_at_utc=depart_at_utc,
        arrive_at_utc=arrive_at_utc,
    )


def _offer(
    number: int,
    origin: str,
    destination: str,
    departure_date: date,
    amount: int,
    *segments: FlightSegmentSummary,
    currency: str = "RUB",
    passenger_mix: PassengerMix | None = None,
    price_basis: PriceBasis = PriceBasis.TOTAL_FOR_PASSENGERS,
    return_date: date | None = None,
) -> ConfirmedOfferEvidence:
    passenger_mix = passenger_mix or PassengerMix(adults=1)
    return ConfirmedOfferEvidence(
        id=UUID(int=number),
        provider_id="aviasales_search",
        provider_offer_id=f"private-provider-ref-{number}",
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        total_amount=Money(amount, currency),
        passengers=passenger_mix.total,
        observed_at=OBSERVED_AT,
        segment_ids=tuple(f"provider-segment-{number}-{index}" for index, _ in enumerate(segments)),
        segments=segments,
        protection_status=ProtectionStatus.UNKNOWN,
        passenger_mix=passenger_mix,
        price_basis=price_basis,
    )


def _request(
    trip_shape: TripShape,
    *pools: LegEvidencePool,
    passenger_mix: PassengerMix | None = None,
    target_currency: str = "RUB",
) -> CompositionRequest:
    passenger_mix = passenger_mix or PassengerMix(adults=1)
    return CompositionRequest(
        namespace=NAMESPACE,
        trip_shape=trip_shape,
        legs=pools,
        passenger_mix=passenger_mix,
        target_currency=target_currency,
    )


def test_provider_multi_segment_offer_remains_one_confirmed_ticket() -> None:
    leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    offer = _offer(
        1,
        "LED",
        "CDG",
        leg.departure_date,
        25_000,
        _segment(
            "LED",
            "IST",
            "2026-09-10T07:00:00+03:00",
            "2026-09-10T11:00:00+03:00",
        ),
        _segment(
            "IST",
            "CDG",
            "2026-09-10T13:00:00+03:00",
            "2026-09-10T16:00:00+02:00",
            suffix="2",
        ),
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(TripShape.ONE_WAY, LegEvidencePool(leg, (offer,)))
    )

    assert result.confirmed == (offer,)
    assert result.composed == ()
    assert result.confirmed[0].protection_status is ProtectionStatus.UNKNOWN
    assert len(result.confirmed[0].segments) == 2


def test_leg_pool_rejects_any_component_that_is_not_confirmed() -> None:
    leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    signal = DiscoverySignal(
        id=UUID(int=2),
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=leg.departure_date,
        return_date=None,
        observed_amount=Money(20_000, "RUB"),
        observed_at=OBSERVED_AT,
        source_kind=DiscoverySource.CALENDAR,
    )

    with pytest.raises(TypeError, match="ConfirmedOfferEvidence"):
        LegEvidencePool(leg, (signal,))  # type: ignore[arg-type]


def _connection_pair(
    outbound_depart_at: str,
    *,
    arrival_airport: str = "IST",
    departure_airport: str = "IST",
) -> tuple[ConfirmedOfferEvidence, ConfirmedOfferEvidence]:
    inbound = _offer(
        10,
        "LED",
        arrival_airport,
        date(2026, 9, 10),
        10_000,
        _segment(
            "LED",
            arrival_airport,
            "2026-09-10T04:00:00+00:00",
            "2026-09-10T10:00:00+00:00",
        ),
    )
    outbound = _offer(
        11,
        departure_airport,
        "CDG",
        date(2026, 9, 10),
        12_000,
        _segment(
            departure_airport,
            "CDG",
            outbound_depart_at,
            "2026-09-11T08:00:00+00:00",
        ),
    )
    return inbound, outbound


@pytest.mark.parametrize(
    ("outbound_depart_at", "expected", "rejection_code"),
    (
        (
            "2026-09-10T12:59:59+00:00",
            False,
            CompositionRejectionCode.CONNECTION_TOO_SHORT,
        ),
        ("2026-09-10T13:00:00+00:00", True, None),
        ("2026-09-11T04:00:00+00:00", True, None),
        (
            "2026-09-11T04:00:01+00:00",
            False,
            CompositionRejectionCode.LAYOVER_TOO_LONG,
        ),
        (
            "2026-09-10T09:59:59+00:00",
            False,
            CompositionRejectionCode.SEGMENTS_OVERLAP,
        ),
    ),
)
def test_same_airport_connection_has_exact_boundaries(
    outbound_depart_at: str,
    expected: bool,
    rejection_code: CompositionRejectionCode | None,
) -> None:
    inbound, outbound = _connection_pair(outbound_depart_at)

    assessment = assess_connection(inbound, outbound, ConnectionPolicy())

    assert assessment.feasible is expected
    assert assessment.rejection_code is rejection_code
    assert connection_is_feasible(inbound, outbound, ConnectionPolicy()) is expected


@pytest.mark.parametrize(
    ("outbound_depart_at", "expected", "rejection_code"),
    (
        (
            "2026-09-10T15:59:59+00:00",
            False,
            CompositionRejectionCode.CONNECTION_TOO_SHORT,
        ),
        ("2026-09-10T16:00:00+00:00", True, None),
    ),
)
def test_airport_change_requires_exact_six_hours(
    outbound_depart_at: str,
    expected: bool,
    rejection_code: CompositionRejectionCode | None,
) -> None:
    inbound, outbound = _connection_pair(
        outbound_depart_at,
        arrival_airport="CDG",
        departure_airport="ORY",
    )
    assumption = AirportChangeAssumption(
        "CDG",
        "ORY",
        provenance="test-approved-transfer",
        transfer_cost=None,
    )

    assessment = assess_connection(
        inbound,
        outbound,
        ConnectionPolicy(),
        airport_change=assumption,
    )

    assert assessment.feasible is expected
    assert assessment.rejection_code is rejection_code


def test_airport_change_is_rejected_without_an_explicit_approved_assumption() -> None:
    inbound, outbound = _connection_pair(
        "2026-09-10T16:00:00+00:00",
        arrival_airport="CDG",
        departure_airport="ORY",
    )

    assessment = assess_connection(inbound, outbound, ConnectionPolicy())

    assert not assessment.feasible
    assert assessment.rejection_code is CompositionRejectionCode.AIRPORT_CHANGE_NOT_APPROVED


def test_connection_rejects_naive_local_timestamps() -> None:
    inbound, outbound = _connection_pair("2026-09-10T13:00:00")

    assessment = assess_connection(inbound, outbound, ConnectionPolicy())

    assert not assessment.feasible
    assert assessment.rejection_code is CompositionRejectionCode.CONNECTION_TIME_UNUSABLE


def test_connection_rejects_display_timestamps_without_verified_provider_instants() -> None:
    inbound, outbound = _connection_pair("2026-09-10T13:00:00+00:00")
    inbound = replace(
        inbound,
        segments=(
            replace(
                inbound.segments[0],
                depart_at_utc=None,
                arrive_at_utc=None,
            ),
        ),
    )

    assessment = assess_connection(inbound, outbound, ConnectionPolicy())

    assert not assessment.feasible
    assert assessment.rejection_code is CompositionRejectionCode.CONNECTION_TIME_UNUSABLE


def test_approved_airport_change_records_unknown_ground_cost_and_safe_facts() -> None:
    leg = FrozenCompositionLeg(0, "LED", "FCO", date(2026, 9, 10))
    inbound, outbound = _connection_pair(
        "2026-09-10T16:00:00+00:00",
        arrival_airport="CDG",
        departure_airport="ORY",
    )
    outbound = _offer(
        12,
        "ORY",
        "FCO",
        date(2026, 9, 10),
        12_000,
        _segment(
            "ORY",
            "FCO",
            "2026-09-10T16:00:00+00:00",
            "2026-09-10T18:00:00+00:00",
        ),
    )
    assumption = AirportChangeAssumption(
        "CDG",
        "ORY",
        provenance="test-approved-transfer",
        transfer_cost=None,
    )
    pool = LegEvidencePool(leg, (outbound, inbound), (assumption,))
    composer = RouteComposer(policy=CompositionPolicy())

    first = composer.compose(_request(TripShape.ONE_WAY, pool))
    second = composer.compose(
        _request(
            TripShape.ONE_WAY,
            LegEvidencePool(leg, (inbound, outbound), (assumption,)),
        )
    )

    assert len(first.composed) == 1
    candidate = first.composed[0]
    assert candidate.id == second.composed[0].id
    assert candidate.id.version == 5
    assert candidate.fingerprint == second.composed[0].fingerprint
    assert candidate.known_total == Money(22_000, "RUB")
    assert candidate.price_comparison_status is PriceComparisonStatus.MANDATORY_COST_UNKNOWN
    assert candidate.protection_status is ProtectionStatus.SELF_TRANSFER
    assert candidate.connection_assumptions[0].airport_change
    assert candidate.connection_assumptions[0].layover == timedelta(hours=6)
    assert tuple(cost.kind for cost in candidate.unknown_costs) == (
        UnknownCostKind.GROUND_TRANSFER,
    )
    assert len(candidate.ticket_boundaries) == 2

    canonical_json = json.dumps(candidate.canonical_facts, sort_keys=True)
    assert "private-provider-ref" not in canonical_json
    assert "provider_offer_id" not in canonical_json
    assert "http://" not in canonical_json
    assert "https://" not in canonical_json


def test_mixed_currency_without_fx_is_retained_but_not_comparable() -> None:
    leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    inbound = _offer(
        20,
        "LED",
        "IST",
        leg.departure_date,
        10_000,
        _segment(
            "LED",
            "IST",
            "2026-09-10T04:00:00+00:00",
            "2026-09-10T08:00:00+00:00",
        ),
        currency="RUB",
    )
    outbound = _offer(
        21,
        "IST",
        "CDG",
        leg.departure_date,
        100,
        _segment(
            "IST",
            "CDG",
            "2026-09-10T11:00:00+00:00",
            "2026-09-10T14:00:00+00:00",
        ),
        currency="USD",
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(TripShape.ONE_WAY, LegEvidencePool(leg, (inbound, outbound)))
    )

    assert len(result.composed) == 1
    candidate = result.composed[0]
    assert candidate.known_total is None
    assert candidate.price_comparison_status is PriceComparisonStatus.NON_COMPARABLE
    assert candidate.component_amounts == (Money(10_000, "RUB"), Money(100, "USD"))
    assert tuple(cost.kind for cost in candidate.unknown_costs) == (
        UnknownCostKind.CURRENCY_CONVERSION,
    )
    assert result.rejections == ()


def test_integer_money_overflow_is_a_typed_rejection() -> None:
    leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    inbound = _offer(
        22,
        "LED",
        "IST",
        leg.departure_date,
        MAX_MONEY_MINOR_UNITS,
        _segment(
            "LED",
            "IST",
            "2026-09-10T04:00:00+00:00",
            "2026-09-10T08:00:00+00:00",
        ),
    )
    outbound = _offer(
        23,
        "IST",
        "CDG",
        leg.departure_date,
        1,
        _segment(
            "IST",
            "CDG",
            "2026-09-10T11:00:00+00:00",
            "2026-09-10T14:00:00+00:00",
        ),
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(TripShape.ONE_WAY, LegEvidencePool(leg, (inbound, outbound)))
    )

    assert result.composed == ()
    assert tuple(item.code for item in result.rejections) == (
        CompositionRejectionCode.MONEY_OVERFLOW,
    )


def test_open_jaw_preserves_ordered_legs_and_full_passenger_mix() -> None:
    passenger_mix = PassengerMix(adults=2, children=1, infants=1)
    outbound_leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    return_leg = FrozenCompositionLeg(1, "ORY", "LED", date(2026, 9, 20))
    outbound = _offer(
        30,
        "LED",
        "CDG",
        outbound_leg.departure_date,
        40_000,
        _segment(
            "LED",
            "CDG",
            "2026-09-10T05:00:00+00:00",
            "2026-09-10T09:00:00+00:00",
        ),
        passenger_mix=passenger_mix,
    )
    returning = _offer(
        31,
        "ORY",
        "LED",
        return_leg.departure_date,
        45_000,
        _segment(
            "ORY",
            "LED",
            "2026-09-20T08:00:00+00:00",
            "2026-09-20T12:00:00+00:00",
        ),
        passenger_mix=passenger_mix,
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(
            TripShape.OPEN_JAW,
            LegEvidencePool(outbound_leg, (outbound,)),
            LegEvidencePool(return_leg, (returning,)),
            passenger_mix=passenger_mix,
        )
    )

    assert len(result.composed) == 1
    candidate = result.composed[0]
    assert candidate.passenger_mix == passenger_mix
    assert tuple(
        (leg.ordinal, leg.origin, leg.destination, leg.departure_date)
        for leg in candidate.ordered_legs
    ) == (
        (0, "LED", "CDG", date(2026, 9, 10)),
        (1, "ORY", "LED", date(2026, 9, 20)),
    )
    assert tuple(leg.component_evidence_ids for leg in candidate.ordered_legs) == (
        (outbound.id,),
        (returning.id,),
    )
    assert candidate.connection_assumptions == ()
    assert candidate.known_total == Money(85_000, "RUB")


def test_multi_city_planned_stopovers_are_not_self_transfer_layovers() -> None:
    passenger_mix = PassengerMix(adults=1, children=1)
    legs = (
        FrozenCompositionLeg(0, "LED", "BER", date(2026, 9, 10)),
        FrozenCompositionLeg(1, "BER", "FCO", date(2026, 9, 15)),
        FrozenCompositionLeg(2, "FCO", "LED", date(2026, 9, 25)),
    )
    offers = (
        _offer(
            40,
            "LED",
            "BER",
            legs[0].departure_date,
            20_000,
            _segment(
                "LED",
                "BER",
                "2026-09-10T05:00:00+00:00",
                "2026-09-10T08:00:00+00:00",
            ),
            passenger_mix=passenger_mix,
        ),
        _offer(
            41,
            "BER",
            "FCO",
            legs[1].departure_date,
            21_000,
            _segment(
                "BER",
                "FCO",
                "2026-09-15T05:00:00+00:00",
                "2026-09-15T08:00:00+00:00",
            ),
            passenger_mix=passenger_mix,
        ),
        _offer(
            42,
            "FCO",
            "LED",
            legs[2].departure_date,
            22_000,
            _segment(
                "FCO",
                "LED",
                "2026-09-25T05:00:00+00:00",
                "2026-09-25T09:00:00+00:00",
            ),
            passenger_mix=passenger_mix,
        ),
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(
            TripShape.MULTI_CITY,
            *(LegEvidencePool(leg, (offer,)) for leg, offer in zip(legs, offers, strict=True)),
            passenger_mix=passenger_mix,
        )
    )

    assert len(result.composed) == 1
    candidate = result.composed[0]
    assert tuple(leg.component_evidence_ids for leg in candidate.ordered_legs) == tuple(
        (offer.id,) for offer in offers
    )
    assert candidate.connection_assumptions == ()
    assert candidate.protection_status is ProtectionStatus.UNKNOWN
    assert candidate.known_total == Money(63_000, "RUB")


def test_beam_bounds_every_leg_and_has_stable_uuid5_ties() -> None:
    legs = (
        FrozenCompositionLeg(0, "LED", "BER", date(2026, 9, 10)),
        FrozenCompositionLeg(1, "BER", "FCO", date(2026, 9, 15)),
        FrozenCompositionLeg(2, "FCO", "LED", date(2026, 9, 20)),
    )
    pools: list[LegEvidencePool] = []
    for leg in legs:
        evidence = tuple(
            _offer(
                100 + leg.ordinal * 10 + alternative,
                leg.origin,
                leg.destination,
                leg.departure_date,
                20_000,
                _segment(
                    leg.origin,
                    leg.destination,
                    f"{leg.departure_date.isoformat()}T05:00:00+00:00",
                    f"{leg.departure_date.isoformat()}T08:00:00+00:00",
                    suffix=str(alternative),
                ),
            )
            for alternative in range(4)
        )
        pools.append(LegEvidencePool(leg, evidence))
    composer = RouteComposer(policy=CompositionPolicy(beam_width=2))

    forward = composer.compose(_request(TripShape.MULTI_CITY, *pools))
    reversed_input = composer.compose(
        _request(
            TripShape.MULTI_CITY,
            *(LegEvidencePool(pool.leg, tuple(reversed(pool.evidence))) for pool in pools),
        )
    )

    assert forward.stats.expanded_per_leg == (4, 8, 8)
    assert forward.stats.expanded_count == 20
    assert forward.stats.retained_per_leg == (2, 2, 2)
    assert len(forward.composed) == 2
    assert tuple(item.id for item in forward.composed) == tuple(
        item.id for item in reversed_input.composed
    )
    assert tuple(item.fingerprint for item in forward.composed) == tuple(
        item.fingerprint for item in reversed_input.composed
    )
    assert all(item.id.version == 5 for item in forward.composed)
    assert all(len(item.component_evidence_ids) == 3 for item in forward.composed)
    with pytest.raises(FrozenInstanceError):
        forward.composed[0].id = UUID(int=999)  # type: ignore[misc]


def test_dominated_option_is_pruned_before_beam_truncation() -> None:
    first_leg = FrozenCompositionLeg(0, "LED", "BER", date(2026, 9, 10))
    second_leg = FrozenCompositionLeg(1, "BER", "FCO", date(2026, 9, 15))
    cheap_balanced = _offer(
        200,
        "LED",
        "BER",
        first_leg.departure_date,
        10_000,
        _segment(
            "LED",
            "BER",
            "2026-09-10T05:00:00+00:00",
            "2026-09-10T08:00:00+00:00",
        ),
    )
    dominated = _offer(
        201,
        "LED",
        "BER",
        first_leg.departure_date,
        20_000,
        _segment(
            "LED",
            "BER",
            "2026-09-10T05:00:00+00:00",
            "2026-09-10T09:00:00+00:00",
        ),
    )
    faster_tradeoff = _offer(
        202,
        "LED",
        "BER",
        first_leg.departure_date,
        30_000,
        _segment(
            "LED",
            "BER",
            "2026-09-10T05:00:00+00:00",
            "2026-09-10T07:00:00+00:00",
        ),
    )
    onward = _offer(
        203,
        "BER",
        "FCO",
        second_leg.departure_date,
        5_000,
        _segment(
            "BER",
            "FCO",
            "2026-09-15T05:00:00+00:00",
            "2026-09-15T08:00:00+00:00",
        ),
    )

    result = RouteComposer(policy=CompositionPolicy(beam_width=2)).compose(
        _request(
            TripShape.MULTI_CITY,
            LegEvidencePool(first_leg, (dominated, faster_tradeoff, cheap_balanced)),
            LegEvidencePool(second_leg, (onward,)),
        )
    )

    retained_first_components = {
        candidate.ordered_legs[0].component_evidence_ids[0] for candidate in result.composed
    }
    assert retained_first_components == {cheap_balanced.id, faster_tradeoff.id}
    assert dominated.id not in retained_first_components


def test_target_currency_is_part_of_non_comparable_candidate_identity() -> None:
    leg = FrozenCompositionLeg(0, "LED", "CDG", date(2026, 9, 10))
    inbound = _offer(
        250,
        "LED",
        "IST",
        leg.departure_date,
        10_000,
        _segment(
            "LED",
            "IST",
            "2026-09-10T04:00:00+00:00",
            "2026-09-10T08:00:00+00:00",
        ),
        currency="RUB",
    )
    outbound = _offer(
        251,
        "IST",
        "CDG",
        leg.departure_date,
        100,
        _segment(
            "IST",
            "CDG",
            "2026-09-10T11:00:00+00:00",
            "2026-09-10T14:00:00+00:00",
        ),
        currency="USD",
    )
    pool = LegEvidencePool(leg, (inbound, outbound))
    composer = RouteComposer(policy=CompositionPolicy())

    rub = composer.compose(_request(TripShape.ONE_WAY, pool, target_currency="RUB")).composed[0]
    eur = composer.compose(_request(TripShape.ONE_WAY, pool, target_currency="EUR")).composed[0]

    assert rub.target_currency == "RUB"
    assert eur.target_currency == "EUR"
    assert rub.fingerprint != eur.fingerprint
    assert rub.id != eur.id


def test_unknown_ground_cost_cannot_win_on_known_airfare_alone() -> None:
    leg = FrozenCompositionLeg(0, "LED", "FCO", date(2026, 9, 10))
    unknown_inbound = _offer(
        300,
        "LED",
        "CDG",
        leg.departure_date,
        5_000,
        _segment(
            "LED",
            "CDG",
            "2026-09-10T04:00:00+00:00",
            "2026-09-10T10:00:00+00:00",
        ),
    )
    unknown_outbound = _offer(
        301,
        "ORY",
        "FCO",
        leg.departure_date,
        5_000,
        _segment(
            "ORY",
            "FCO",
            "2026-09-10T16:00:00+00:00",
            "2026-09-10T18:00:00+00:00",
        ),
    )
    fully_priced_inbound = _offer(
        302,
        "LED",
        "IST",
        leg.departure_date,
        20_000,
        _segment(
            "LED",
            "IST",
            "2026-09-10T05:00:00+00:00",
            "2026-09-10T08:00:00+00:00",
        ),
    )
    fully_priced_outbound = _offer(
        303,
        "IST",
        "FCO",
        leg.departure_date,
        20_000,
        _segment(
            "IST",
            "FCO",
            "2026-09-10T11:00:00+00:00",
            "2026-09-10T14:00:00+00:00",
        ),
    )
    change = AirportChangeAssumption(
        "CDG",
        "ORY",
        provenance="test-approved-transfer",
        transfer_cost=None,
    )

    result = RouteComposer(policy=CompositionPolicy()).compose(
        _request(
            TripShape.ONE_WAY,
            LegEvidencePool(
                leg,
                (
                    unknown_inbound,
                    unknown_outbound,
                    fully_priced_inbound,
                    fully_priced_outbound,
                ),
                (change,),
            ),
        )
    )

    assert len(result.composed) == 2
    assert result.composed[0].known_total == Money(40_000, "RUB")
    assert result.composed[0].price_comparison_status is PriceComparisonStatus.FULLY_PRICED
    assert result.composed[1].known_total == Money(10_000, "RUB")
    assert (
        result.composed[1].price_comparison_status is PriceComparisonStatus.MANDATORY_COST_UNKNOWN
    )
