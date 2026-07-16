from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
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
from flight_hunter.domain.offers import FlightSegmentSummary, PassengerMix, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentComposedRouteCandidateRecord,
    AgentConfirmedOfferEvidenceRecord,
    BaggageEvidenceStatus,
    NewAgentComposedRouteCandidate,
    TransferEvidenceStatus,
    VisaEvidenceStatus,
)


class StoredAgentEvidenceError(ValueError):
    """Stored agent evidence cannot be reconstructed into a trusted domain fact."""


def confirmed_record_to_evidence(
    record: AgentConfirmedOfferEvidenceRecord,
    *,
    fallback_passenger_mix: PassengerMix | None = None,
    fallback_departure_date: date | None = None,
    fallback_return_date: date | None = None,
) -> ConfirmedOfferEvidence:
    itinerary = _mapping(record.itinerary_evidence, "confirmed itinerary")
    segment_values = _sequence(itinerary.get("segments"), "confirmed segments")
    if not segment_values:
        raise StoredAgentEvidenceError("confirmed itinerary has no segments")
    segment_ids: list[str] = []
    segments: list[FlightSegmentSummary] = []
    for index, raw_segment in enumerate(segment_values):
        segment = _mapping(raw_segment, "confirmed segment")
        segment_ids.append(
            _optional_text(segment.get("segment_ref"))
            or uuid5(record.id, f"stored-segment:{index}").hex
        )
        depart_at_utc = _optional_datetime(segment.get("depart_at_utc"))
        arrive_at_utc = _optional_datetime(segment.get("arrive_at_utc"))
        if (depart_at_utc is None) != (arrive_at_utc is None):
            raise StoredAgentEvidenceError("confirmed segment UTC instants are incomplete")
        segments.append(
            FlightSegmentSummary(
                airline_code=_text(segment.get("carrier"), "segment carrier"),
                airline_name=None,
                flight_number=_optional_text(segment.get("flight_number")),
                origin=_text(segment.get("origin"), "segment origin"),
                destination=_text(segment.get("destination"), "segment destination"),
                depart_at=_text(segment.get("depart_at"), "segment departure"),
                arrive_at=_text(segment.get("arrive_at"), "segment arrival"),
                depart_at_utc=depart_at_utc,
                arrive_at_utc=arrive_at_utc,
            )
        )

    departure_date = _optional_date(itinerary.get("departure_date"))
    if departure_date is None:
        departure_date = fallback_departure_date or _segment_local_date(segments[0].depart_at)
    return_date = (
        _optional_date(itinerary.get("return_date"))
        if "return_date" in itinerary
        else fallback_return_date
    )
    passenger_mix = _passenger_mix(
        itinerary.get("passenger_mix"),
        fallback=fallback_passenger_mix,
        passengers=record.passengers,
    )
    price_basis = PriceBasis(
        _optional_text(itinerary.get("price_basis")) or record.passenger_basis.value
    )
    if record.amount_minor is None or record.currency is None:
        raise StoredAgentEvidenceError("confirmed evidence has no typed total")
    return ConfirmedOfferEvidence(
        id=record.id,
        provider_id=record.provider_id,
        provider_offer_id=f"stored-evidence:{record.id}",
        origin=_text(itinerary.get("origin"), "confirmed origin"),
        destination=_text(itinerary.get("destination"), "confirmed destination"),
        departure_date=departure_date,
        return_date=return_date,
        total_amount=Money(record.amount_minor, record.currency),
        passengers=record.passengers,
        observed_at=record.observed_at,
        segment_ids=tuple(segment_ids),
        segments=tuple(segments),
        protection_status=record.protection_status,
        seller_name=_optional_text(itinerary.get("seller")),
        baggage_summary=None,
        passenger_mix=passenger_mix,
        price_basis=price_basis,
    )


def composed_record_to_candidate(
    record: AgentComposedRouteCandidateRecord,
    confirmed_by_id: Mapping[UUID, ConfirmedOfferEvidence],
) -> ComposedRouteCandidate:
    try:
        components = tuple(confirmed_by_id[value] for value in record.component_evidence_ids)
    except KeyError as error:
        raise StoredAgentEvidenceError("composed component evidence is missing") from error
    facts = _mapping(record.itinerary_evidence, "composed itinerary")
    stored_components = tuple(
        UUID(_text(value, "composed component id"))
        for value in _sequence(facts.get("components"), "composed components")
    )
    if stored_components != record.component_evidence_ids:
        raise StoredAgentEvidenceError("composed component order is inconsistent")
    total_amount = (
        None
        if record.amount_minor is None
        else Money(record.amount_minor, _text(record.currency, "candidate currency"))
    )
    passenger_mix = _passenger_mix(
        facts.get("passenger_mix"),
        fallback=None,
        passengers=record.passengers,
    )
    ordered_legs = tuple(
        ComposedRouteLeg(
            ordinal=_integer(leg.get("ordinal"), "leg ordinal"),
            origin=_text(leg.get("origin"), "leg origin"),
            destination=_text(leg.get("destination"), "leg destination"),
            departure_date=_date(leg.get("departure_date"), "leg departure date"),
            component_evidence_ids=tuple(
                UUID(_text(value, "leg component id"))
                for value in _sequence(leg.get("components"), "leg components")
            ),
        )
        for leg in (
            _mapping(value, "composed leg")
            for value in _sequence(facts.get("ordered_legs"), "ordered legs")
        )
    )
    ticket_boundaries = tuple(
        TicketBoundary(
            ticket_index=_integer(boundary.get("ticket_index"), "ticket index"),
            leg_ordinal=_integer(boundary.get("leg_ordinal"), "ticket leg ordinal"),
            component_evidence_id=UUID(
                _text(boundary.get("component_evidence_id"), "ticket component id")
            ),
            segment_refs=tuple(
                _text(value, "ticket segment ref")
                for value in _sequence(boundary.get("segment_refs"), "ticket segment refs")
            ),
        )
        for boundary in (
            _mapping(value, "ticket boundary")
            for value in _sequence(facts.get("tickets"), "ticket boundaries")
        )
    )
    connections = tuple(
        ConnectionAssumption(
            leg_ordinal=_integer(connection.get("leg_ordinal"), "connection leg ordinal"),
            inbound_component_id=UUID(
                _text(connection.get("inbound_component_id"), "inbound component id")
            ),
            outbound_component_id=UUID(
                _text(connection.get("outbound_component_id"), "outbound component id")
            ),
            arrival_airport=_text(
                connection.get("arrival_airport"),
                "connection arrival airport",
            ),
            departure_airport=_text(
                connection.get("departure_airport"),
                "connection departure airport",
            ),
            layover=timedelta(
                seconds=_integer(connection.get("layover_seconds"), "layover seconds")
            ),
            required_minimum=timedelta(
                seconds=_integer(
                    connection.get("required_minimum_seconds"),
                    "required minimum seconds",
                )
            ),
            airport_change=_boolean(connection.get("airport_change"), "airport change"),
            provenance=_optional_text(connection.get("provenance")),
            transfer_cost=_optional_money(connection.get("transfer_cost")),
        )
        for connection in (
            _mapping(value, "connection assumption")
            for value in _sequence(facts.get("connections"), "connections")
        )
    )
    unknown_costs = tuple(
        UnknownCost(
            kind=UnknownCostKind(_text(cost.get("kind"), "unknown cost kind")),
            leg_ordinal=_integer(cost.get("leg_ordinal"), "unknown cost leg ordinal"),
            description=_text(cost.get("description"), "unknown cost description"),
        )
        for cost in (
            _mapping(value, "unknown cost")
            for value in _sequence(facts.get("unknown_costs"), "unknown costs")
        )
    )
    segment_ids = tuple(
        f"{component.id}#{segment_id}"
        for component in components
        for segment_id in component.segment_ids
    )
    fingerprint = record.fingerprint.removeprefix("sha256:")
    return ComposedRouteCandidate(
        id=record.id,
        components=components,
        total_amount=total_amount,
        passengers=record.passengers,
        observed_at=record.observed_at,
        segment_ids=segment_ids,
        segments=tuple(segment for component in components for segment in component.segments),
        protection_status=record.protection_status,
        trip_shape=TripShape(_text(facts.get("trip_shape"), "trip shape")),
        passenger_mix=passenger_mix,
        price_basis=record.passenger_basis,
        target_currency=_text(facts.get("target_currency"), "target currency"),
        price_comparison_status=PriceComparisonStatus(
            _text(facts.get("price_comparison_status"), "price comparison status")
        ),
        ordered_legs=ordered_legs,
        ticket_boundaries=ticket_boundaries,
        connection_assumptions=connections,
        unknown_costs=unknown_costs,
        fingerprint=fingerprint,
        composition_version=_text(
            facts.get("composition_version"),
            "composition version",
        ),
        ranking_reasons=tuple(
            _text(value, "ranking reason")
            for value in _sequence(facts.get("ranking_reasons"), "ranking reasons")
        ),
    )


def new_composed_candidate(
    candidate: ComposedRouteCandidate,
    *,
    household_id: UUID,
    run_id: UUID,
    stage_id: UUID,
    created_at: datetime,
) -> NewAgentComposedRouteCandidate:
    amount = candidate.total_amount
    return NewAgentComposedRouteCandidate(
        id=candidate.id,
        household_id=household_id,
        run_id=run_id,
        stage_id=stage_id,
        component_evidence_ids=candidate.component_evidence_ids,
        observed_at=candidate.observed_at,
        passengers=candidate.passengers,
        passenger_basis=candidate.price_basis,
        amount_minor=amount.minor_units if amount is not None else None,
        currency=amount.currency if amount is not None else None,
        itinerary_evidence=candidate.canonical_facts,
        protection_status=candidate.protection_status,
        baggage_status=BaggageEvidenceStatus.UNKNOWN,
        transfer_status=(
            TransferEvidenceStatus.SELF_TRANSFER
            if candidate.protection_status is ProtectionStatus.SELF_TRANSFER
            else TransferEvidenceStatus.UNKNOWN
        ),
        visa_status=VisaEvidenceStatus.UNKNOWN,
        fingerprint=f"sha256:{candidate.fingerprint}",
        created_at=created_at,
    )


def _passenger_mix(
    value: object,
    *,
    fallback: PassengerMix | None,
    passengers: int,
) -> PassengerMix:
    if value is None:
        return fallback or PassengerMix(adults=passengers)
    payload = _mapping(value, "passenger mix")
    mix = PassengerMix(
        adults=_integer(payload.get("adults"), "adults"),
        children=_integer(payload.get("children"), "children"),
        infants=_integer(payload.get("infants"), "infants"),
    )
    if mix.total != passengers:
        raise StoredAgentEvidenceError("stored passenger mix total is inconsistent")
    return mix


def _optional_money(value: object) -> Money | None:
    if value is None:
        return None
    payload = _mapping(value, "money")
    return Money(
        _integer(payload.get("minor_units"), "money minor units"),
        _text(payload.get("currency"), "money currency"),
    )


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise StoredAgentEvidenceError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise StoredAgentEvidenceError(f"{field_name} must be an ordered collection")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise StoredAgentEvidenceError(f"{field_name} must be a non-empty string")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value, "optional text")


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise StoredAgentEvidenceError(f"{field_name} must be an integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise StoredAgentEvidenceError(f"{field_name} must be bool")
    return value


def _date(value: object, field_name: str) -> date:
    text = _text(value, field_name)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise StoredAgentEvidenceError(f"{field_name} must be an ISO date") from error


def _optional_date(value: object) -> date | None:
    if value is None:
        return None
    return _date(value, "optional date")


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = _text(value, "optional datetime")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StoredAgentEvidenceError("stored datetime must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StoredAgentEvidenceError("stored datetime must be timezone-aware")
    return parsed


def _segment_local_date(value: str) -> date:
    if len(value) < 10:
        raise StoredAgentEvidenceError("segment departure date is missing")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        raise StoredAgentEvidenceError("segment departure date is invalid") from error
