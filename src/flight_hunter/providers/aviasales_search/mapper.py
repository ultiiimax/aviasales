from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from uuid import UUID, uuid5

from flight_hunter.domain.agent_evidence import (
    ConfirmedOfferEvidence,
    DiscoverySignal,
    DiscoverySource,
    ProtectionStatus,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, FlightSegmentSummary, Freshness, PriceBasis
from flight_hunter.providers.aviasales_search.client import CalendarPrice
from flight_hunter.providers.aviasales_search.schemas import ParsedTicket

_EVIDENCE_NAMESPACE = UUID("2350f67f-f74f-4a0d-bc50-e218610f939d")


def map_parsed_ticket(
    ticket: ParsedTicket,
    *,
    observed_at: datetime,
    passengers: int,
    search_id: str | None = None,
    results_url: str | None = None,
) -> FlightOffer:
    baggage_summary = _baggage_summary(ticket)
    return FlightOffer(
        provider_id="aviasales_search",
        provider_offer_id=stable_ticket_id(ticket),
        origin=ticket.origin,
        destination=ticket.destination,
        departure_date=ticket.departure_date,
        return_date=ticket.return_date,
        total_price=Money(ticket.best_proposal.price_minor_units, ticket.best_proposal.currency),
        passengers=passengers,
        observed_at=observed_at,
        freshness=Freshness.LIVE,
        requires_live_confirmation=False,
        baggage_summary=baggage_summary,
        price_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
        seller_name=ticket.best_proposal.gate_name or None,
        segments=_segment_summaries(ticket),
        booking_action_ref=_booking_action_ref(
            ticket,
            search_id=search_id,
            results_url=results_url,
        ),
    )


def stable_ticket_id(ticket: ParsedTicket) -> str:
    raw = "|".join(
        (
            ticket.ticket_signature,
            ticket.best_proposal.proposal_id,
            ticket.origin,
            ticket.destination,
            ticket.departure_date,
            ticket.return_date or "",
            str(ticket.best_proposal.price_minor_units),
            ticket.best_proposal.currency,
        )
    )
    return "aviasales_search:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def map_parsed_ticket_to_evidence(
    ticket: ParsedTicket,
    *,
    observed_at: datetime,
    passengers: int,
) -> ConfirmedOfferEvidence:
    provider_offer_id = stable_ticket_id(ticket)
    segments = _segment_summaries(ticket)
    segment_ids = tuple(
        _stable_segment_id(segment, index=index) for index, segment in enumerate(segments)
    )
    return ConfirmedOfferEvidence(
        id=uuid5(_EVIDENCE_NAMESPACE, f"{provider_offer_id}|{passengers}"),
        provider_id="aviasales_search",
        provider_offer_id=provider_offer_id,
        origin=ticket.origin,
        destination=ticket.destination,
        departure_date=date.fromisoformat(ticket.departure_date),
        return_date=date.fromisoformat(ticket.return_date) if ticket.return_date else None,
        total_amount=Money(
            ticket.best_proposal.price_minor_units,
            ticket.best_proposal.currency,
        ),
        passengers=passengers,
        observed_at=observed_at,
        segment_ids=segment_ids,
        segments=segments,
        protection_status=ProtectionStatus.UNKNOWN,
        seller_name=ticket.best_proposal.gate_name or None,
        baggage_summary=_baggage_summary(ticket),
    )


def map_calendar_price_to_discovery(
    price: CalendarPrice,
    *,
    observed_at: datetime,
    passengers: int,
) -> DiscoverySignal:
    identity = "|".join(
        (
            "aviasales_search",
            "calendar",
            price.origin,
            price.destination,
            price.departure_date,
            price.return_date or "",
            str(price.price_minor_units),
            price.currency,
            str(passengers),
        )
    )
    return DiscoverySignal(
        id=uuid5(_EVIDENCE_NAMESPACE, identity),
        provider_id="aviasales_search",
        origin=price.origin,
        destination=price.destination,
        departure_date=date.fromisoformat(price.departure_date),
        return_date=date.fromisoformat(price.return_date) if price.return_date else None,
        observed_amount=Money(price.price_minor_units, price.currency),
        observed_at=observed_at,
        source_kind=DiscoverySource.CALENDAR,
        passengers=passengers,
    )


def _stable_segment_id(segment: FlightSegmentSummary, *, index: int) -> str:
    raw = "|".join(
        (
            str(index),
            segment.airline_code,
            segment.flight_number or "",
            segment.origin,
            segment.destination,
            segment.depart_at,
            segment.arrive_at,
        )
    )
    return "aviasales_segment:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _baggage_summary(ticket: ParsedTicket) -> str | None:
    count = ticket.best_proposal.baggage_count
    handbag = ticket.best_proposal.handbag
    parts: list[str] = []
    if count is not None and count > 0:
        parts.append(f"baggage:{count}")
    if handbag:
        parts.append(f"handbag:{handbag}")
    return ", ".join(parts) if parts else None


def _segment_summaries(ticket: ParsedTicket) -> tuple[FlightSegmentSummary, ...]:
    return tuple(
        FlightSegmentSummary(
            airline_code=segment.airline_code,
            airline_name=segment.airline_name or None,
            flight_number=segment.flight_number or None,
            origin=segment.origin,
            destination=segment.destination,
            depart_at=segment.depart_at,
            arrive_at=segment.arrive_at,
        )
        for group in ticket.segments
        for segment in group
    )


def _booking_action_ref(
    ticket: ParsedTicket,
    *,
    search_id: str | None,
    results_url: str | None,
) -> str | None:
    if not search_id or not results_url:
        return None
    return json.dumps(
        {
            "provider_id": "aviasales_search",
            "search_id": search_id,
            "proposal_id": ticket.best_proposal.proposal_id,
            "results_url": results_url,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
