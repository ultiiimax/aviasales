from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import StrEnum
from uuid import UUID, uuid5

from flight_hunter.domain.agent_evidence import (
    ComposedRouteCandidate,
    ComposedRouteLeg,
    ConfirmedOfferEvidence,
    ConnectionAssumption,
    PriceComparisonStatus,
    ProtectionStatus,
    TicketBoundary,
    UnknownCost,
    UnknownCostKind,
)
from flight_hunter.domain.agent_search import TripShape
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import PassengerMix

COMPOSER_VERSION = "route-composer-v1"
_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class CompositionRejectionCode(StrEnum):
    LEG_MISMATCH = "leg_mismatch"
    PASSENGER_MIX_MISMATCH = "passenger_mix_mismatch"
    PRICE_BASIS_MISMATCH = "price_basis_mismatch"
    CONNECTION_TIME_UNUSABLE = "connection_time_unusable"
    CONNECTION_TOO_SHORT = "connection_too_short"
    LAYOVER_TOO_LONG = "layover_too_long"
    SEGMENTS_OVERLAP = "segments_overlap"
    AIRPORT_CHANGE_NOT_APPROVED = "airport_change_not_approved"
    MIXED_CURRENCY_WITHOUT_FX = "mixed_currency_without_fx"
    MONEY_OVERFLOW = "money_overflow"


@dataclass(frozen=True, slots=True)
class ConnectionPolicy:
    same_airport_minimum: timedelta = timedelta(minutes=180)
    airport_change_minimum: timedelta = timedelta(minutes=360)
    maximum_layover: timedelta = timedelta(hours=18)

    def __post_init__(self) -> None:
        values = (
            self.same_airport_minimum,
            self.airport_change_minimum,
            self.maximum_layover,
        )
        if not all(isinstance(value, timedelta) for value in values):
            raise TypeError("connection policy values must be timedelta")
        if self.same_airport_minimum <= timedelta(0):
            raise ValueError("same_airport_minimum must be positive")
        if self.airport_change_minimum <= timedelta(0):
            raise ValueError("airport_change_minimum must be positive")
        if self.maximum_layover < max(
            self.same_airport_minimum,
            self.airport_change_minimum,
        ):
            raise ValueError("maximum_layover must cover both minimum connections")


@dataclass(frozen=True, slots=True)
class CompositionPolicy:
    connection: ConnectionPolicy = ConnectionPolicy()
    beam_width: int = 20
    max_tickets_per_leg: int = 2

    def __post_init__(self) -> None:
        if not isinstance(self.connection, ConnectionPolicy):
            raise TypeError("connection must be ConnectionPolicy")
        if type(self.beam_width) is not int or self.beam_width < 1:
            raise ValueError("beam_width must be a positive integer")
        if self.max_tickets_per_leg not in {1, 2}:
            raise ValueError("max_tickets_per_leg must be one or two")


@dataclass(frozen=True, slots=True)
class FrozenCompositionLeg:
    ordinal: int
    origin: str
    destination: str
    departure_date: date

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        origin = _iata(self.origin, "origin")
        destination = _iata(self.destination, "destination")
        if type(self.departure_date) is not date:
            raise TypeError("departure_date must be a date")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)


@dataclass(frozen=True, slots=True)
class AirportChangeAssumption:
    from_airport: str
    to_airport: str
    provenance: str
    transfer_cost: Money | None

    def __post_init__(self) -> None:
        from_airport = _iata(self.from_airport, "from_airport")
        to_airport = _iata(self.to_airport, "to_airport")
        if from_airport == to_airport:
            raise ValueError("airport change must use different airports")
        if not self.provenance:
            raise ValueError("airport change provenance is required")
        if self.transfer_cost is not None and self.transfer_cost.minor_units < 0:
            raise ValueError("transfer_cost cannot be negative")
        object.__setattr__(self, "from_airport", from_airport)
        object.__setattr__(self, "to_airport", to_airport)


@dataclass(frozen=True, slots=True)
class LegEvidencePool:
    leg: FrozenCompositionLeg
    evidence: tuple[ConfirmedOfferEvidence, ...]
    approved_airport_changes: tuple[AirportChangeAssumption, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.leg, FrozenCompositionLeg):
            raise TypeError("leg must be FrozenCompositionLeg")
        evidence = tuple(self.evidence)
        if not all(isinstance(item, ConfirmedOfferEvidence) for item in evidence):
            raise TypeError("evidence must contain ConfirmedOfferEvidence values")
        changes = tuple(self.approved_airport_changes)
        if not all(isinstance(item, AirportChangeAssumption) for item in changes):
            raise TypeError("approved_airport_changes must contain AirportChangeAssumption values")
        if len({(item.from_airport, item.to_airport) for item in changes}) != len(changes):
            raise ValueError("approved airport changes must be unique")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "approved_airport_changes", changes)


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    namespace: UUID
    trip_shape: TripShape
    legs: tuple[LegEvidencePool, ...]
    passenger_mix: PassengerMix
    target_currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, UUID):
            raise TypeError("namespace must be UUID")
        trip_shape = TripShape(self.trip_shape)
        legs = tuple(self.legs)
        if not all(isinstance(pool, LegEvidencePool) for pool in legs):
            raise TypeError("legs must contain LegEvidencePool values")
        if tuple(pool.leg.ordinal for pool in legs) != tuple(range(len(legs))):
            raise ValueError("leg ordinals must be contiguous and ordered")
        required = {
            TripShape.ONE_WAY: 1,
            TripShape.ROUND_TRIP: 2,
            TripShape.OPEN_JAW: 2,
        }.get(trip_shape)
        if required is not None and len(legs) != required:
            raise ValueError(f"{trip_shape.value} requires {required} leg(s)")
        if trip_shape is TripShape.MULTI_CITY and len(legs) < 2:
            raise ValueError("multi_city requires at least two legs")
        if not isinstance(self.passenger_mix, PassengerMix):
            raise TypeError("passenger_mix must be PassengerMix")
        currency = self.target_currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError("target_currency must be an ISO 4217 alpha-3 code")
        object.__setattr__(self, "trip_shape", trip_shape)
        object.__setattr__(self, "legs", legs)
        object.__setattr__(self, "target_currency", currency)


@dataclass(frozen=True, slots=True)
class CompositionRejection:
    code: CompositionRejectionCode
    leg_ordinal: int
    component_evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", CompositionRejectionCode(self.code))
        object.__setattr__(self, "component_evidence_ids", tuple(self.component_evidence_ids))


@dataclass(frozen=True, slots=True)
class CompositionStats:
    expanded_count: int = 0
    expanded_per_leg: tuple[int, ...] = ()
    retained_per_leg: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CompositionResult:
    confirmed: tuple[ConfirmedOfferEvidence, ...]
    composed: tuple[ComposedRouteCandidate, ...]
    rejections: tuple[CompositionRejection, ...]
    stats: CompositionStats


@dataclass(frozen=True, slots=True)
class ConnectionAssessment:
    feasible: bool
    rejection_code: CompositionRejectionCode | None
    arrival_airport: str
    departure_airport: str
    layover: timedelta | None
    required_minimum: timedelta | None
    airport_change: AirportChangeAssumption | None = None


@dataclass(frozen=True, slots=True)
class _LegOption:
    leg: FrozenCompositionLeg
    components: tuple[ConfirmedOfferEvidence, ...]
    connections: tuple[ConnectionAssumption, ...] = ()
    unknown_costs: tuple[UnknownCost, ...] = ()


@dataclass(frozen=True, slots=True)
class _EvaluatedPartial:
    options: tuple[_LegOption, ...]
    candidate: ComposedRouteCandidate


def assess_connection(
    inbound: ConfirmedOfferEvidence,
    outbound: ConfirmedOfferEvidence,
    policy: ConnectionPolicy,
    *,
    airport_change: AirportChangeAssumption | None = None,
) -> ConnectionAssessment:
    if not isinstance(inbound, ConfirmedOfferEvidence) or not isinstance(
        outbound, ConfirmedOfferEvidence
    ):
        raise TypeError("connection inputs must be ConfirmedOfferEvidence")
    if not isinstance(policy, ConnectionPolicy):
        raise TypeError("policy must be ConnectionPolicy")
    arrival_airport = inbound.segments[-1].destination
    departure_airport = outbound.segments[0].origin
    is_airport_change = arrival_airport != departure_airport
    if is_airport_change and (
        airport_change is None
        or airport_change.from_airport != arrival_airport
        or airport_change.to_airport != departure_airport
    ):
        return ConnectionAssessment(
            False,
            CompositionRejectionCode.AIRPORT_CHANGE_NOT_APPROVED,
            arrival_airport,
            departure_airport,
            None,
            policy.airport_change_minimum,
        )

    arrive_at = inbound.segments[-1].arrive_at_utc
    depart_at = outbound.segments[0].depart_at_utc
    required = policy.airport_change_minimum if is_airport_change else policy.same_airport_minimum
    if arrive_at is None or depart_at is None:
        return ConnectionAssessment(
            False,
            CompositionRejectionCode.CONNECTION_TIME_UNUSABLE,
            arrival_airport,
            departure_airport,
            None,
            required,
            airport_change if is_airport_change else None,
        )
    layover = depart_at - arrive_at
    if layover < timedelta(0):
        rejection = CompositionRejectionCode.SEGMENTS_OVERLAP
    elif layover < required:
        rejection = CompositionRejectionCode.CONNECTION_TOO_SHORT
    elif layover > policy.maximum_layover:
        rejection = CompositionRejectionCode.LAYOVER_TOO_LONG
    else:
        rejection = None
    return ConnectionAssessment(
        rejection is None,
        rejection,
        arrival_airport,
        departure_airport,
        layover,
        required,
        airport_change if is_airport_change else None,
    )


def connection_is_feasible(
    inbound: ConfirmedOfferEvidence,
    outbound: ConfirmedOfferEvidence,
    policy: ConnectionPolicy,
    *,
    airport_change: AirportChangeAssumption | None = None,
) -> bool:
    return assess_connection(
        inbound,
        outbound,
        policy,
        airport_change=airport_change,
    ).feasible


class RouteComposer:
    def __init__(self, *, policy: CompositionPolicy) -> None:
        if not isinstance(policy, CompositionPolicy):
            raise TypeError("policy must be CompositionPolicy")
        self._policy = policy

    def compose(self, request: CompositionRequest) -> CompositionResult:
        if not isinstance(request, CompositionRequest):
            raise TypeError("request must be CompositionRequest")
        confirmed = tuple(
            sorted(
                (
                    evidence
                    for pool in request.legs
                    for evidence in pool.evidence
                    if _is_direct_match(evidence, pool.leg, request.passenger_mix)
                ),
                key=lambda evidence: evidence.id.hex,
            )
        )
        rejections: list[CompositionRejection] = []
        options_by_leg: list[tuple[_LegOption, ...]] = []
        for pool in request.legs:
            options, option_rejections = _leg_options(pool, request, self._policy)
            options_by_leg.append(options)
            rejections.extend(option_rejections)

        beam: list[_EvaluatedPartial] = []
        expanded_per_leg: list[int] = []
        retained_per_leg: list[int] = []
        for leg_index, leg_options in enumerate(options_by_leg):
            raw_partials = (
                [(option,) for option in leg_options]
                if leg_index == 0
                else [(*partial.options, option) for partial in beam for option in leg_options]
            )
            expanded_per_leg.append(len(raw_partials))
            evaluated: list[_EvaluatedPartial] = []
            for options in raw_partials:
                overlap_code = _planned_leg_overlap(options)
                if overlap_code is not None:
                    rejections.append(
                        CompositionRejection(
                            overlap_code,
                            options[-1].leg.ordinal,
                            tuple(
                                component.id
                                for option in options[-2:]
                                for component in option.components
                            ),
                        )
                    )
                    continue
                candidate, rejection_code = _candidate_from_options(request, options)
                if candidate is None:
                    if rejection_code is not None:
                        rejections.append(
                            CompositionRejection(
                                rejection_code,
                                options[-1].leg.ordinal,
                                tuple(
                                    component.id
                                    for option in options
                                    for component in option.components
                                ),
                            )
                        )
                    continue
                evaluated.append(_EvaluatedPartial(options, candidate))
            evaluated = _non_dominated(evaluated)
            evaluated.sort(key=lambda item: _candidate_sort_key(item.candidate))
            beam = evaluated[: self._policy.beam_width]
            retained_per_leg.append(len(beam))

        composed = [
            partial.candidate
            for partial in beam
            if len(request.legs) > 1 or len(partial.options[0].components) > 1
        ]
        composed.sort(key=_candidate_sort_key)
        rejections = _unique_sorted_rejections(rejections)
        return CompositionResult(
            confirmed=confirmed,
            composed=tuple(composed),
            rejections=tuple(rejections),
            stats=CompositionStats(
                expanded_count=sum(expanded_per_leg),
                expanded_per_leg=tuple(expanded_per_leg),
                retained_per_leg=tuple(retained_per_leg),
            ),
        )


def _leg_options(
    pool: LegEvidencePool,
    request: CompositionRequest,
    policy: CompositionPolicy,
) -> tuple[tuple[_LegOption, ...], tuple[CompositionRejection, ...]]:
    options: list[_LegOption] = []
    rejections: list[CompositionRejection] = []
    direct = sorted(
        (item for item in pool.evidence if _is_direct_route(item, pool.leg)),
        key=lambda item: item.id.hex,
    )
    for evidence in direct:
        mismatch = _component_mismatch_code((evidence,), request)
        if mismatch is None:
            options.append(_LegOption(pool.leg, (evidence,)))
        else:
            rejections.append(CompositionRejection(mismatch, pool.leg.ordinal, (evidence.id,)))

    if policy.max_tickets_per_leg == 2:
        starts = sorted(
            (
                item
                for item in pool.evidence
                if item.origin == pool.leg.origin
                and item.destination != pool.leg.destination
                and item.departure_date == pool.leg.departure_date
                and item.return_date is None
            ),
            key=lambda item: item.id.hex,
        )
        ends = sorted(
            (
                item
                for item in pool.evidence
                if item.destination == pool.leg.destination
                and item.origin != pool.leg.origin
                and item.return_date is None
            ),
            key=lambda item: item.id.hex,
        )
        for inbound in starts:
            for outbound in ends:
                if inbound.id == outbound.id:
                    continue
                components = (inbound, outbound)
                mismatch = _component_mismatch_code(components, request)
                if mismatch is not None:
                    rejections.append(
                        CompositionRejection(
                            mismatch,
                            pool.leg.ordinal,
                            (inbound.id, outbound.id),
                        )
                    )
                    continue
                airport_change = _approved_change(pool, inbound, outbound)
                assessment = assess_connection(
                    inbound,
                    outbound,
                    policy.connection,
                    airport_change=airport_change,
                )
                if not assessment.feasible:
                    if assessment.rejection_code is not None:
                        rejections.append(
                            CompositionRejection(
                                assessment.rejection_code,
                                pool.leg.ordinal,
                                (inbound.id, outbound.id),
                            )
                        )
                    continue
                if assessment.layover is None or assessment.required_minimum is None:
                    rejections.append(
                        CompositionRejection(
                            CompositionRejectionCode.CONNECTION_TIME_UNUSABLE,
                            pool.leg.ordinal,
                            (inbound.id, outbound.id),
                        )
                    )
                    continue
                connection = ConnectionAssumption(
                    leg_ordinal=pool.leg.ordinal,
                    inbound_component_id=inbound.id,
                    outbound_component_id=outbound.id,
                    arrival_airport=assessment.arrival_airport,
                    departure_airport=assessment.departure_airport,
                    layover=assessment.layover,
                    required_minimum=assessment.required_minimum,
                    airport_change=assessment.arrival_airport != assessment.departure_airport,
                    provenance=(
                        assessment.airport_change.provenance
                        if assessment.airport_change is not None
                        else None
                    ),
                    transfer_cost=(
                        assessment.airport_change.transfer_cost
                        if assessment.airport_change is not None
                        else None
                    ),
                )
                unknown_costs = (
                    (
                        UnknownCost(
                            UnknownCostKind.GROUND_TRANSFER,
                            pool.leg.ordinal,
                            "Ground transfer "
                            f"{assessment.arrival_airport}-{assessment.departure_airport}",
                        ),
                    )
                    if assessment.airport_change is not None
                    and assessment.airport_change.transfer_cost is None
                    else ()
                )
                options.append(
                    _LegOption(
                        pool.leg,
                        components,
                        connections=(connection,),
                        unknown_costs=unknown_costs,
                    )
                )

    unique = {tuple(component.id for component in option.components): option for option in options}
    ordered = tuple(
        unique[key] for key in sorted(unique, key=lambda ids: tuple(value.hex for value in ids))
    )
    return ordered, tuple(_unique_sorted_rejections(rejections))


def _candidate_from_options(
    request: CompositionRequest,
    options: tuple[_LegOption, ...],
) -> tuple[ComposedRouteCandidate | None, CompositionRejectionCode | None]:
    components = tuple(component for option in options for component in option.components)
    if len({component.id for component in components}) != len(components):
        return None, CompositionRejectionCode.LEG_MISMATCH
    mismatch = _component_mismatch_code(components, request)
    if mismatch is not None:
        return None, mismatch
    connections = tuple(connection for option in options for connection in option.connections)
    unknown_costs = tuple(cost for option in options for cost in option.unknown_costs)
    priced_items = [component.total_amount for component in components]
    priced_items.extend(
        connection.transfer_cost
        for connection in connections
        if connection.transfer_cost is not None
    )
    currencies = {amount.currency for amount in priced_items}
    total: Money | None
    status: PriceComparisonStatus
    ranking_reasons = ["confirmed_components"]
    if currencies != {request.target_currency}:
        total = None
        status = PriceComparisonStatus.NON_COMPARABLE
        unknown_costs = (
            *unknown_costs,
            UnknownCost(
                UnknownCostKind.CURRENCY_CONVERSION,
                options[0].leg.ordinal,
                "Fresh deterministic FX is unavailable",
            ),
        )
        ranking_reasons.append("mixed_currency_without_fx")
    else:
        try:
            total = Money(
                sum(amount.minor_units for amount in priced_items),
                request.target_currency,
            )
        except ValueError:
            return None, CompositionRejectionCode.MONEY_OVERFLOW
        if unknown_costs:
            status = PriceComparisonStatus.MANDATORY_COST_UNKNOWN
            ranking_reasons.append("mandatory_cost_unknown")
        else:
            status = PriceComparisonStatus.FULLY_PRICED

    segment_refs = tuple(
        f"{component.id}#{segment_id}"
        for component in components
        for segment_id in component.segment_ids
    )
    boundaries: list[TicketBoundary] = []
    offset = 0
    ticket_index = 0
    for option in options:
        for component in option.components:
            count = len(component.segment_ids)
            boundaries.append(
                TicketBoundary(
                    ticket_index=ticket_index,
                    leg_ordinal=option.leg.ordinal,
                    component_evidence_id=component.id,
                    segment_refs=segment_refs[offset : offset + count],
                )
            )
            offset += count
            ticket_index += 1
    provisional = ComposedRouteCandidate(
        id=UUID(int=0),
        components=components,
        total_amount=total,
        passengers=request.passenger_mix.total,
        observed_at=min(item.observed_at for item in components),
        segment_ids=segment_refs,
        segments=tuple(segment for item in components for segment in item.segments),
        protection_status=(
            ProtectionStatus.SELF_TRANSFER if connections else ProtectionStatus.UNKNOWN
        ),
        trip_shape=request.trip_shape,
        passenger_mix=request.passenger_mix,
        price_basis=components[0].price_basis,
        target_currency=request.target_currency,
        price_comparison_status=status,
        ordered_legs=tuple(
            ComposedRouteLeg(
                option.leg.ordinal,
                option.leg.origin,
                option.leg.destination,
                option.leg.departure_date,
                tuple(component.id for component in option.components),
            )
            for option in options
        ),
        ticket_boundaries=tuple(boundaries),
        connection_assumptions=connections,
        unknown_costs=unknown_costs,
        composition_version=COMPOSER_VERSION,
        ranking_reasons=tuple(ranking_reasons),
    )
    fingerprint = _fingerprint(provisional.canonical_facts)
    return (
        replace(
            provisional,
            id=uuid5(request.namespace, fingerprint),
            fingerprint=fingerprint,
        ),
        None,
    )


def _planned_leg_overlap(
    options: tuple[_LegOption, ...],
) -> CompositionRejectionCode | None:
    if len(options) < 2:
        return None
    previous = options[-2].components[-1]
    current = options[-1].components[0]
    arrive_at = previous.segments[-1].arrive_at_utc
    depart_at = current.segments[0].depart_at_utc
    if arrive_at is None or depart_at is None:
        return CompositionRejectionCode.CONNECTION_TIME_UNUSABLE
    if depart_at < arrive_at:
        return CompositionRejectionCode.SEGMENTS_OVERLAP
    return None


def _candidate_sort_key(candidate: ComposedRouteCandidate) -> tuple[object, ...]:
    status_rank = {
        PriceComparisonStatus.FULLY_PRICED: 0,
        PriceComparisonStatus.MANDATORY_COST_UNKNOWN: 1,
        PriceComparisonStatus.NON_COMPARABLE: 2,
    }[candidate.price_comparison_status]
    amount = candidate.known_total.minor_units if candidate.known_total is not None else 2**63
    elapsed = _candidate_elapsed_seconds(candidate)
    airport_changes = sum(
        assumption.airport_change for assumption in candidate.connection_assumptions
    )
    uncertainty = len(candidate.unknown_costs)
    route_key = tuple(
        (leg.origin, leg.destination, leg.departure_date.isoformat())
        for leg in candidate.ordered_legs
    )
    return (
        status_rank,
        amount,
        elapsed,
        airport_changes,
        len(candidate.ticket_boundaries),
        uncertainty,
        route_key,
        candidate.fingerprint,
    )


def _non_dominated(candidates: list[_EvaluatedPartial]) -> list[_EvaluatedPartial]:
    return [
        candidate
        for index, candidate in enumerate(candidates)
        if not any(
            _dominates(other.candidate, candidate.candidate)
            for other_index, other in enumerate(candidates)
            if other_index != index
        )
    ]


def _dominates(
    candidate: ComposedRouteCandidate,
    other: ComposedRouteCandidate,
) -> bool:
    metrics = _pareto_metrics(candidate)
    other_metrics = _pareto_metrics(other)
    return all(left <= right for left, right in zip(metrics, other_metrics, strict=True)) and any(
        left < right for left, right in zip(metrics, other_metrics, strict=True)
    )


def _pareto_metrics(candidate: ComposedRouteCandidate) -> tuple[int, ...]:
    status_rank = {
        PriceComparisonStatus.FULLY_PRICED: 0,
        PriceComparisonStatus.MANDATORY_COST_UNKNOWN: 1,
        PriceComparisonStatus.NON_COMPARABLE: 2,
    }[candidate.price_comparison_status]
    amount = candidate.known_total.minor_units if candidate.known_total is not None else 2**63
    elapsed = _candidate_elapsed_seconds(candidate)
    return (
        status_rank,
        amount,
        elapsed,
        sum(assumption.airport_change for assumption in candidate.connection_assumptions),
        len(candidate.ticket_boundaries),
        len(candidate.unknown_costs) + int(candidate.protection_status is ProtectionStatus.UNKNOWN),
    )


def _candidate_elapsed_seconds(candidate: ComposedRouteCandidate) -> int:
    component_by_id = {component.id: component for component in candidate.components}
    elapsed = 0
    for leg in candidate.ordered_legs:
        first = component_by_id[leg.component_evidence_ids[0]]
        last = component_by_id[leg.component_evidence_ids[-1]]
        depart_at = first.segments[0].depart_at_utc
        arrive_at = last.segments[-1].arrive_at_utc
        if depart_at is None or arrive_at is None or arrive_at < depart_at:
            return 2**63
        elapsed += int((arrive_at - depart_at).total_seconds())
    return elapsed


def _unique_sorted_rejections(
    rejections: list[CompositionRejection],
) -> list[CompositionRejection]:
    unique = {
        (
            item.code,
            item.leg_ordinal,
            item.component_evidence_ids,
        ): item
        for item in rejections
    }
    return [
        unique[key]
        for key in sorted(
            unique,
            key=lambda item: (
                item[1],
                tuple(value.hex for value in item[2]),
                item[0].value,
            ),
        )
    ]


def _component_mismatch_code(
    components: tuple[ConfirmedOfferEvidence, ...],
    request: CompositionRequest,
) -> CompositionRejectionCode | None:
    if any(item.passenger_mix != request.passenger_mix for item in components):
        return CompositionRejectionCode.PASSENGER_MIX_MISMATCH
    if len({item.price_basis for item in components}) != 1:
        return CompositionRejectionCode.PRICE_BASIS_MISMATCH
    return None


def _approved_change(
    pool: LegEvidencePool,
    inbound: ConfirmedOfferEvidence,
    outbound: ConfirmedOfferEvidence,
) -> AirportChangeAssumption | None:
    arrival = inbound.segments[-1].destination
    departure = outbound.segments[0].origin
    if arrival == departure:
        return None
    return next(
        (
            item
            for item in pool.approved_airport_changes
            if item.from_airport == arrival and item.to_airport == departure
        ),
        None,
    )


def _is_direct_match(
    evidence: ConfirmedOfferEvidence,
    leg: FrozenCompositionLeg,
    passenger_mix: PassengerMix,
) -> bool:
    return _is_direct_route(evidence, leg) and evidence.passenger_mix == passenger_mix


def _is_direct_route(
    evidence: ConfirmedOfferEvidence,
    leg: FrozenCompositionLeg,
) -> bool:
    return (
        evidence.origin == leg.origin
        and evidence.destination == leg.destination
        and evidence.departure_date == leg.departure_date
        and evidence.return_date is None
    )


def _fingerprint(facts: dict[str, object]) -> str:
    canonical = json.dumps(
        facts,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _iata(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.upper()
    if not _IATA_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an IATA code")
    return normalized
