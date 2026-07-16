from __future__ import annotations

import hashlib
import json
import re
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
from flight_hunter.providers.aviasales_search.client import CalendarPrice, HotOffer
from flight_hunter.providers.aviasales_search.schemas import ParsedTicket

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


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
    evidence_namespace: UUID,
) -> ConfirmedOfferEvidence:
    if not isinstance(evidence_namespace, UUID):
        raise TypeError("evidence_namespace must be UUID")
    provider_offer_id = stable_ticket_id(ticket)
    segments = _segment_summaries(ticket)
    segment_ids = tuple(
        _stable_segment_id(segment, index=index) for index, segment in enumerate(segments)
    )
    return ConfirmedOfferEvidence(
        id=uuid5(evidence_namespace, f"exact|{provider_offer_id}|{passengers}"),
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
    evidence_namespace: UUID,
) -> DiscoverySignal:
    if not isinstance(evidence_namespace, UUID):
        raise TypeError("evidence_namespace must be UUID")
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
        )
    )
    return DiscoverySignal(
        id=uuid5(evidence_namespace, f"discovery|{identity}"),
        provider_id="aviasales_search",
        origin=price.origin,
        destination=price.destination,
        departure_date=date.fromisoformat(price.departure_date),
        return_date=date.fromisoformat(price.return_date) if price.return_date else None,
        observed_amount=Money(price.price_minor_units, price.currency),
        observed_at=observed_at,
        source_kind=DiscoverySource.CALENDAR,
        passengers=1,
    )


def map_hot_offer_to_discovery(
    offer: HotOffer,
    *,
    expected_origin: str,
    date_from: date,
    date_to: date,
    expected_currency: str,
    one_way: bool,
    observed_at: datetime,
    evidence_namespace: UUID,
) -> DiscoverySignal:
    """Validate a hot-offer row against one approved discovery operation."""

    if not isinstance(offer, HotOffer):
        raise TypeError("offer must be HotOffer")
    if not isinstance(evidence_namespace, UUID):
        raise TypeError("evidence_namespace must be UUID")
    if type(date_from) is not date or type(date_to) is not date or date_to < date_from:
        raise ValueError("date bounds must be ordered dates")
    if type(one_way) is not bool:
        raise TypeError("one_way must be a boolean")
    if not isinstance(observed_at, datetime):
        raise TypeError("observed_at must be a datetime")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    origin = _strict_iata(expected_origin, "expected_origin")
    row_origin = _strict_iata(offer.origin, "origin")
    destination = _strict_iata(offer.destination, "destination")
    if row_origin != origin or destination == origin:
        raise ValueError("hot offer route does not match approved request")

    departure = _strict_provider_date(offer.departure_date, "departure_date")
    if not date_from <= departure <= date_to:
        raise ValueError("hot offer departure is outside approved window")
    returned = (
        _strict_provider_date(offer.return_date, "return_date")
        if offer.return_date is not None
        else None
    )
    if one_way and returned is not None:
        raise ValueError("one-way hot offer cannot contain a return date")
    if not one_way and (returned is None or returned < departure):
        raise ValueError("round-trip hot offer requires an ordered return date")

    currency = _strict_currency(expected_currency, "expected_currency")
    row_currency = _strict_currency(offer.currency, "currency")
    if row_currency != currency:
        raise ValueError("hot offer currency does not match approved request")
    if type(offer.price_minor_units) is not int or offer.price_minor_units < 0:
        raise ValueError("hot offer amount must be non-negative integer minor units")

    identity = "|".join(
        (
            "aviasales_search",
            "hot_offer",
            origin,
            destination,
            departure.isoformat(),
            returned.isoformat() if returned is not None else "",
            str(offer.price_minor_units),
            currency,
            "1",
        )
    )
    return DiscoverySignal(
        id=uuid5(evidence_namespace, f"discovery|{identity}"),
        provider_id="aviasales_search",
        origin=origin,
        destination=destination,
        departure_date=departure,
        return_date=returned,
        observed_amount=Money(offer.price_minor_units, currency),
        observed_at=observed_at,
        source_kind=DiscoverySource.HOT_OFFER,
        passengers=1,
    )


def _strict_iata(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.upper()
    if not _IATA_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ASCII IATA code")
    return normalized


def _strict_currency(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.upper()
    if not _ISO_CURRENCY_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ASCII ISO currency")
    return normalized


def _strict_provider_date(value: object, field_name: str) -> date:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a canonical ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} must be a canonical ISO date") from None
    if parsed.isoformat() != value:
        raise ValueError(f"{field_name} must be a canonical ISO date")
    return parsed


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
