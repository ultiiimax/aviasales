from __future__ import annotations

from dataclasses import asdict, fields, replace
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from uuid import UUID

import pytest

from flight_hunter.application.agent_reporting import (
    BalancedWeights,
    CandidateKind,
    CandidateRanker,
    CandidateReference,
    FactReportBuilder,
    RankingView,
    RankingViewResult,
    ranking_snapshot_from_payload,
    ranking_snapshot_to_payload,
)
from flight_hunter.domain.agent_evidence import (
    ComposedRouteCandidate,
    ComposedRouteLeg,
    ConfirmedOfferEvidence,
    ConnectionAssumption,
    DiscoverySignal,
    DiscoverySource,
    PriceComparisonStatus,
    ProtectionStatus,
    UnknownCost,
    UnknownCostKind,
)
from flight_hunter.domain.agent_evidence import (
    TicketBoundary as DomainTicketBoundary,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import (
    FlightSegmentSummary,
    PassengerMix,
    PriceBasis,
)

OBSERVED_AT = datetime(2026, 7, 16, 9, tzinfo=UTC)


def _segment(
    segment_id: str,
    origin: str,
    destination: str,
    depart_at: str,
    arrive_at: str,
) -> tuple[str, FlightSegmentSummary]:
    depart_at_utc = datetime.fromisoformat(depart_at.replace("Z", "+00:00"))
    arrive_at_utc = datetime.fromisoformat(arrive_at.replace("Z", "+00:00"))
    return (
        segment_id,
        FlightSegmentSummary(
            airline_code="XX",
            airline_name="Fixture Air",
            flight_number=f"XX{segment_id[-1]}",
            origin=origin,
            destination=destination,
            depart_at=depart_at,
            arrive_at=arrive_at,
            depart_at_utc=depart_at_utc,
            arrive_at_utc=arrive_at_utc,
        ),
    )


def _offer(
    identifier: int,
    *,
    origin: str,
    destination: str,
    amount_minor: int,
    depart_at: str,
    arrive_at: str,
    protection: ProtectionStatus,
    provider_id: str = "aviasales_search",
    baggage_summary: str | None = "cabin bag only",
    currency: str = "RUB",
    passenger_mix: PassengerMix | None = None,
) -> ConfirmedOfferEvidence:
    segment_id, segment = _segment(
        f"segment-{identifier}",
        origin,
        destination,
        depart_at,
        arrive_at,
    )
    return ConfirmedOfferEvidence(
        id=UUID(f"00000000-0000-0000-0000-{identifier:012d}"),
        provider_id=provider_id,
        provider_offer_id=f"PRIVATE-provider-offer-{identifier}",
        origin=origin,
        destination=destination,
        departure_date=date(2026, 9, 10),
        return_date=None,
        total_amount=Money(amount_minor, currency),
        passengers=(passenger_mix or PassengerMix(adults=1)).total,
        observed_at=OBSERVED_AT,
        segment_ids=(segment_id,),
        segments=(segment,),
        protection_status=protection,
        seller_name="Fixture seller",
        baggage_summary=baggage_summary,
        passenger_mix=passenger_mix,
    )


def _composed(
    identifier: int,
    components: tuple[ConfirmedOfferEvidence, ...],
    *,
    amount_minor: int,
    transfer_cost: Money | None = None,
) -> ComposedRouteCandidate:
    component_refs = tuple(
        tuple(f"{component.id}#{segment_id}" for segment_id in component.segment_ids)
        for component in components
    )
    segment_refs = tuple(value for refs in component_refs for value in refs)
    connections: list[ConnectionAssumption] = []
    unknown_costs: list[UnknownCost] = []
    for inbound, outbound in pairwise(components):
        inbound_segment = inbound.segments[-1]
        outbound_segment = outbound.segments[0]
        assert inbound_segment.arrive_at_utc is not None
        assert outbound_segment.depart_at_utc is not None
        airport_change = inbound_segment.destination != outbound_segment.origin
        connections.append(
            ConnectionAssumption(
                leg_ordinal=0,
                inbound_component_id=inbound.id,
                outbound_component_id=outbound.id,
                arrival_airport=inbound_segment.destination,
                departure_airport=outbound_segment.origin,
                layover=outbound_segment.depart_at_utc - inbound_segment.arrive_at_utc,
                required_minimum=timedelta(hours=6 if airport_change else 3),
                airport_change=airport_change,
                provenance=("fixture ground transfer" if airport_change else None),
                transfer_cost=transfer_cost if airport_change else None,
            )
        )
        if airport_change and transfer_cost is None:
            unknown_costs.append(
                UnknownCost(
                    UnknownCostKind.GROUND_TRANSFER,
                    0,
                    "Ground transfer cost is unknown",
                )
            )
    return ComposedRouteCandidate(
        id=UUID(f"10000000-0000-0000-0000-{identifier:012d}"),
        components=components,
        total_amount=Money(amount_minor, "RUB"),
        passengers=1,
        observed_at=OBSERVED_AT,
        segment_ids=segment_refs,
        segments=tuple(segment for component in components for segment in component.segments),
        protection_status=ProtectionStatus.SELF_TRANSFER,
        passenger_mix=components[0].passenger_mix,
        price_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
        target_currency="RUB",
        price_comparison_status=(
            PriceComparisonStatus.MANDATORY_COST_UNKNOWN
            if unknown_costs
            else PriceComparisonStatus.FULLY_PRICED
        ),
        ordered_legs=(
            ComposedRouteLeg(
                ordinal=0,
                origin=components[0].origin,
                destination=components[-1].destination,
                departure_date=components[0].departure_date,
                component_evidence_ids=tuple(component.id for component in components),
            ),
        ),
        ticket_boundaries=tuple(
            DomainTicketBoundary(
                ticket_index=index,
                leg_ordinal=0,
                component_evidence_id=component.id,
                segment_refs=component_refs[index],
            )
            for index, component in enumerate(components)
        ),
        connection_assumptions=tuple(connections),
        unknown_costs=tuple(unknown_costs),
    )


def _ranking_candidates() -> tuple[
    ConfirmedOfferEvidence,
    ConfirmedOfferEvidence,
    ComposedRouteCandidate,
    ComposedRouteCandidate,
]:
    protected = _offer(
        1,
        origin="LED",
        destination="CDG",
        amount_minor=20_000,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T13:00:00+02:00",
        protection=ProtectionStatus.EXPLICITLY_PROTECTED,
    )
    fast = _offer(
        2,
        origin="LED",
        destination="CDG",
        amount_minor=10_000,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T12:30:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    split_first = _offer(
        3,
        origin="LED",
        destination="HEL",
        amount_minor=4_500,
        depart_at="2026-09-10T08:00:00+03:00",
        arrive_at="2026-09-10T09:00:00+03:00",
        protection=ProtectionStatus.UNKNOWN,
        baggage_summary=None,
    )
    split_second = _offer(
        4,
        origin="HEL",
        destination="CDG",
        amount_minor=4_500,
        depart_at="2026-09-10T12:00:00+03:00",
        arrive_at="2026-09-10T14:00:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
        baggage_summary=None,
    )
    split = _composed(1, (split_first, split_second), amount_minor=9_000)

    change_first = _offer(
        5,
        origin="LED",
        destination="ARN",
        amount_minor=500,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T10:30:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    change_second = _offer(
        6,
        origin="BMA",
        destination="CDG",
        amount_minor=500,
        depart_at="2026-09-10T17:00:00+02:00",
        arrive_at="2026-09-10T18:30:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    unknown_transfer_cost = _composed(
        2,
        (change_first, change_second),
        amount_minor=1_000,
    )
    return protected, fast, split, unknown_transfer_cost


def _refs(view: RankingViewResult) -> tuple[CandidateReference, ...]:
    return tuple(candidate.reference for candidate in view.candidates)


def test_ranker_builds_six_deterministic_views_and_never_uses_unknown_cost_as_zero() -> None:
    protected, fast, split, unknown_transfer_cost = _ranking_candidates()

    snapshot = CandidateRanker().rank(
        (unknown_transfer_cost, split, fast, protected),
        balanced_weights=BalancedWeights(price=100, duration=0, risk=0),
    )

    protected_ref = CandidateReference(CandidateKind.CONFIRMED_OFFER, protected.id)
    fast_ref = CandidateReference(CandidateKind.CONFIRMED_OFFER, fast.id)
    split_ref = CandidateReference(CandidateKind.COMPOSED_ROUTE, split.id)
    unknown_cost_ref = CandidateReference(
        CandidateKind.COMPOSED_ROUTE,
        unknown_transfer_cost.id,
    )

    assert tuple(view.name for view in snapshot.views) == tuple(RankingView)
    assert _refs(snapshot.view(RankingView.CHEAPEST)) == (
        split_ref,
        fast_ref,
        protected_ref,
    )
    assert _refs(snapshot.view(RankingView.FASTEST))[0] == fast_ref
    assert _refs(snapshot.view(RankingView.LOW_RISK))[0] == protected_ref
    assert _refs(snapshot.view(RankingView.BALANCED)) == (
        split_ref,
        fast_ref,
        protected_ref,
    )
    assert snapshot.view(RankingView.BALANCED).weights == BalancedWeights(
        price=100,
        duration=0,
        risk=0,
    )
    assert _refs(snapshot.view(RankingView.SPLIT_SELF_TRANSFER)) == (
        split_ref,
        unknown_cost_ref,
    )
    assert unknown_cost_ref not in _refs(snapshot.view(RankingView.CHEAPEST))
    assert unknown_cost_ref in _refs(snapshot.view(RankingView.RISKY))
    risky_entry = next(
        entry
        for entry in snapshot.view(RankingView.RISKY).candidates
        if entry.reference == unknown_cost_ref
    )
    assert "unknown_mandatory_transfer_cost" in risky_entry.reasons


def test_non_comparable_total_cannot_beat_fully_priced_candidate() -> None:
    protected, _, split, _ = _ranking_candidates()
    # The Task 11 domain slice widens this field to Money | None.  Keep this
    # reporting test compatible while that shared-tree change lands.
    object.__setattr__(split, "total_amount", None)
    object.__setattr__(
        split,
        "price_comparison_status",
        PriceComparisonStatus.NON_COMPARABLE,
    )

    snapshot = CandidateRanker().rank((split, protected))
    split_ref = CandidateReference(CandidateKind.COMPOSED_ROUTE, split.id)

    assert _refs(snapshot.view(RankingView.CHEAPEST)) == (
        CandidateReference(CandidateKind.CONFIRMED_OFFER, protected.id),
    )
    assert split_ref in _refs(snapshot.view(RankingView.RISKY))


def test_fastest_and_low_risk_views_do_not_require_comparable_complete_price() -> None:
    protected, _, _, unknown_transfer_cost = _ranking_candidates()
    mixed_currency = _offer(
        31,
        origin="LED",
        destination="CDG",
        amount_minor=90,
        currency="USD",
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T11:00:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )

    snapshot = CandidateRanker().rank(
        (protected, mixed_currency, unknown_transfer_cost),
        comparison_currency="RUB",
    )
    mixed_ref = CandidateReference(CandidateKind.CONFIRMED_OFFER, mixed_currency.id)
    unknown_cost_ref = CandidateReference(
        CandidateKind.COMPOSED_ROUTE,
        unknown_transfer_cost.id,
    )

    assert mixed_ref not in _refs(snapshot.view(RankingView.CHEAPEST))
    assert unknown_cost_ref not in _refs(snapshot.view(RankingView.CHEAPEST))
    assert _refs(snapshot.view(RankingView.FASTEST))[0] == mixed_ref
    assert mixed_ref in _refs(snapshot.view(RankingView.LOW_RISK))
    assert unknown_cost_ref in _refs(snapshot.view(RankingView.LOW_RISK))


def test_known_airport_transfer_cost_remains_fully_priced_and_comparable() -> None:
    first = _offer(
        32,
        origin="LED",
        destination="ARN",
        amount_minor=4_000,
        depart_at="2026-09-10T08:00:00+03:00",
        arrive_at="2026-09-10T10:00:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    second = _offer(
        33,
        origin="BMA",
        destination="CDG",
        amount_minor=5_000,
        depart_at="2026-09-10T17:00:00+02:00",
        arrive_at="2026-09-10T19:00:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    candidate = _composed(
        3,
        (first, second),
        amount_minor=9_500,
        transfer_cost=Money(500, "RUB"),
    )

    snapshot = CandidateRanker().rank((candidate,), comparison_currency="RUB")
    reference = CandidateReference(CandidateKind.COMPOSED_ROUTE, candidate.id)

    assert _refs(snapshot.view(RankingView.CHEAPEST)) == (reference,)
    risky = snapshot.view(RankingView.RISKY).candidates[0]
    assert "airport_change" in risky.reasons
    assert "unknown_mandatory_transfer_cost" not in risky.reasons


def test_multi_city_fastest_sums_leg_travel_without_counting_planned_stay() -> None:
    first_leg = _offer(
        34,
        origin="LED",
        destination="CDG",
        amount_minor=6_000,
        depart_at="2026-09-10T08:00:00+00:00",
        arrive_at="2026-09-10T10:00:00+00:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    second_leg = replace(
        _offer(
            35,
            origin="CDG",
            destination="NCE",
            amount_minor=4_000,
            depart_at="2026-09-15T08:00:00+00:00",
            arrive_at="2026-09-15T10:00:00+00:00",
            protection=ProtectionStatus.UNKNOWN,
        ),
        departure_date=date(2026, 9, 15),
    )
    segment_refs = (
        f"{first_leg.id}#{first_leg.segment_ids[0]}",
        f"{second_leg.id}#{second_leg.segment_ids[0]}",
    )
    multi_city = ComposedRouteCandidate(
        id=UUID("10000000-0000-0000-0000-000000000004"),
        components=(first_leg, second_leg),
        total_amount=Money(10_000, "RUB"),
        passengers=1,
        observed_at=OBSERVED_AT,
        segment_ids=segment_refs,
        segments=(*first_leg.segments, *second_leg.segments),
        protection_status=ProtectionStatus.UNKNOWN,
        trip_shape="multi_city",
        passenger_mix=PassengerMix(adults=1),
        price_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
        target_currency="RUB",
        price_comparison_status=PriceComparisonStatus.FULLY_PRICED,
        ordered_legs=(
            ComposedRouteLeg(0, "LED", "CDG", date(2026, 9, 10), (first_leg.id,)),
            ComposedRouteLeg(1, "CDG", "NCE", date(2026, 9, 15), (second_leg.id,)),
        ),
        ticket_boundaries=(
            DomainTicketBoundary(0, 0, first_leg.id, (segment_refs[0],)),
            DomainTicketBoundary(1, 1, second_leg.id, (segment_refs[1],)),
        ),
    )
    continuous_five_hours = _offer(
        36,
        origin="LED",
        destination="NCE",
        amount_minor=11_000,
        depart_at="2026-09-10T08:00:00+00:00",
        arrive_at="2026-09-10T13:00:00+00:00",
        protection=ProtectionStatus.UNKNOWN,
    )

    snapshot = CandidateRanker().rank((continuous_five_hours, multi_city))

    assert _refs(snapshot.view(RankingView.FASTEST))[0] == CandidateReference(
        CandidateKind.COMPOSED_ROUTE,
        multi_city.id,
    )


def test_naive_provider_local_timestamps_still_mark_overnight_connection() -> None:
    first = _offer(
        37,
        origin="LED",
        destination="AMS",
        amount_minor=4_000,
        depart_at="2026-09-10T20:00:00+00:00",
        arrive_at="2026-09-10T23:30:00+00:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    second = _offer(
        38,
        origin="AMS",
        destination="CDG",
        amount_minor=4_000,
        depart_at="2026-09-11T06:00:00+00:00",
        arrive_at="2026-09-11T08:00:00+00:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    first = replace(
        first,
        segments=(replace(first.segments[0], arrive_at="2026-09-10 23:30"),),
    )
    second = replace(
        second,
        segments=(replace(second.segments[0], depart_at="2026-09-11 06:00"),),
    )
    candidate = _composed(4, (first, second), amount_minor=8_000)

    snapshot = CandidateRanker().rank((candidate,))
    entry = snapshot.view(RankingView.RISKY).candidates[0]

    assert "overnight_connection" in entry.reasons


def test_ties_and_snapshot_fingerprint_are_stable_without_mutating_evidence() -> None:
    first = _offer(
        21,
        origin="LED",
        destination="CDG",
        amount_minor=10_000,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T12:30:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    second = _offer(
        22,
        origin="LED",
        destination="CDG",
        amount_minor=10_000,
        depart_at="2026-09-10T10:00:00+03:00",
        arrive_at="2026-09-10T12:30:00+02:00",
        protection=ProtectionStatus.UNKNOWN,
    )
    before = (first, second)

    forward = CandidateRanker().rank((first, second))
    reverse = CandidateRanker().rank((second, first))

    assert forward == reverse
    assert len(forward.fingerprint) == 64
    assert forward.confirmed_evidence_ids == (first.id, second.id)
    assert forward.composed_candidate_ids == ()
    assert before == (first, second)
    assert all(
        field.name not in {"provider_offer_id", "provider_ref", "url"}
        for field in fields(type(forward))
    )


def test_ranking_snapshot_payload_round_trip_is_exact_and_typed() -> None:
    snapshot = CandidateRanker().rank(_ranking_candidates())

    payload = ranking_snapshot_to_payload(snapshot)
    restored = ranking_snapshot_from_payload(payload)

    assert restored == snapshot
    assert payload["version"] == "candidate-ranker-v1"
    assert payload["fingerprint"] == snapshot.fingerprint
    assert {view["name"] for view in payload["views"]} == {view.value for view in RankingView}


def test_ranker_rejects_indicative_or_duplicate_input() -> None:
    offer = _ranking_candidates()[0]
    signal = DiscoverySignal(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 10),
        return_date=None,
        observed_amount=Money(1, "RUB"),
        observed_at=OBSERVED_AT,
        source_kind=DiscoverySource.CALENDAR,
    )

    with pytest.raises(TypeError, match="confirmed evidence required"):
        CandidateRanker().rank((signal,))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate candidate reference"):
        CandidateRanker().rank((offer, offer))


@pytest.mark.parametrize(
    ("factory", "error", "message"),
    (
        (
            lambda: BalancedWeights(price=0, duration=0, risk=0),
            ValueError,
            "at least one balanced weight",
        ),
        (
            lambda: BalancedWeights(price=True, duration=1, risk=1),
            TypeError,
            "weights must be integers",
        ),
    ),
)
def test_balanced_weights_are_explicit_non_negative_integers(
    factory: object,
    error: type[Exception],
    message: str,
) -> None:
    assert callable(factory)
    with pytest.raises(error, match=message):
        factory()


def test_fact_report_projects_typed_facts_ticket_boundaries_and_unknowns_only() -> None:
    protected, fast, split, unknown_transfer_cost = _ranking_candidates()
    snapshot = CandidateRanker().rank((protected, fast, split, unknown_transfer_cost))
    report = FactReportBuilder().build(
        snapshot,
        (protected, fast, split, unknown_transfer_cost),
    )
    split_ref = CandidateReference(CandidateKind.COMPOSED_ROUTE, split.id)
    split_fact = report.candidate(split_ref)
    unknown_transfer_fact = report.candidate(
        CandidateReference(CandidateKind.COMPOSED_ROUTE, unknown_transfer_cost.id)
    )

    assert report.ranking == snapshot
    assert split_fact.passengers == split.passengers
    assert split_fact.passenger_mix == split.passenger_mix
    assert split_fact.trip_shape == split.trip_shape
    assert split_fact.price_basis == split.price_basis
    assert split_fact.total_amount is split.total_amount
    assert split_fact.sources == ("aviasales_search",)
    assert split_fact.observed_at == OBSERVED_AT
    assert split_fact.segments == split.segments
    assert split_fact.protection_status is ProtectionStatus.SELF_TRANSFER
    assert split_fact.ordered_legs == split.ordered_legs
    assert split_fact.connection_assumptions == split.connection_assumptions
    assert split_fact.price_comparison_status is split.price_comparison_status
    assert split_fact.unknown_costs == split.unknown_costs
    assert tuple(boundary.segment_ids for boundary in split_fact.ticket_boundaries) == (
        split.ticket_boundaries[0].segment_refs,
        split.ticket_boundaries[1].segment_refs,
    )
    assert (
        tuple(boundary.confirmed_evidence_id for boundary in split_fact.ticket_boundaries)
        == split.component_evidence_ids
    )
    assert "baggage" in split_fact.unknowns
    assert "mandatory_airport_transfer_cost" in unknown_transfer_fact.unknowns
    assert split_fact.booking_action.available is False
    assert split_fact.booking_action.token is None

    payload = asdict(report)
    rendered = repr(payload)
    assert "PRIVATE-provider-offer" not in rendered
    assert "provider_offer_id" not in rendered
    assert "provider_ref" not in rendered
    assert "https://" not in rendered


def test_fact_report_exposes_only_an_already_signed_short_lived_booking_token() -> None:
    protected = _ranking_candidates()[0]
    snapshot = CandidateRanker().rank((protected,))
    reference = CandidateReference(CandidateKind.CONFIRMED_OFFER, protected.id)
    token = "v1.opaque-signed-short-lived-token"

    report = FactReportBuilder().build(
        snapshot,
        (protected,),
        booking_action_tokens={reference: token},
    )

    assert report.candidate(reference).booking_action.available is True
    assert report.candidate(reference).booking_action.token == token
    booking_action_fields = fields(type(report.candidate(reference).booking_action))
    assert tuple(field.name for field in booking_action_fields) == (
        "available",
        "token",
    )
    with pytest.raises(ValueError, match="opaque pre-signed token"):
        FactReportBuilder().build(
            snapshot,
            (protected,),
            booking_action_tokens={reference: "https://seller.example/private-ref"},
        )


def test_fact_report_builder_does_not_perform_money_arithmetic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protected = _ranking_candidates()[0]
    snapshot = CandidateRanker().rank((protected,))

    def fail_arithmetic(left: Money, right: Money) -> Money:
        raise AssertionError(f"report builder attempted arithmetic: {left!r}, {right!r}")

    monkeypatch.setattr(Money, "__add__", fail_arithmetic)
    monkeypatch.setattr(Money, "__sub__", fail_arithmetic)

    report = FactReportBuilder().build(snapshot, (protected,))

    assert report.candidates[0].total_amount is protected.total_amount
