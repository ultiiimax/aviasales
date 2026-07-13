from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AviasalesSearchParseError(RuntimeError):
    """Raised when a raw Aviasales Search chunk cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class ParsedSegment:
    airline_code: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    depart_at: str
    arrive_at: str


@dataclass(frozen=True, slots=True)
class ParsedProposal:
    proposal_id: str
    agent_id: int
    price_minor_units: int
    currency: str
    gate_name: str
    baggage_count: int | None
    handbag: str | None


@dataclass(frozen=True, slots=True)
class ParsedTicket:
    ticket_signature: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    segments: tuple[tuple[ParsedSegment, ...], ...]
    best_proposal: ParsedProposal


def parse_chunks(chunks: list[dict[str, Any]]) -> tuple[ParsedTicket, ...]:
    airlines: dict[str, Any] = {}
    agents: dict[str, Any] = {}
    for chunk in chunks:
        if not isinstance(chunk, dict):
            raise AviasalesSearchParseError("aviasales_search_invalid_chunk")
        airlines.update(_as_dict(chunk.get("airlines")))
        agents.update(_as_dict(chunk.get("agents")))

    parsed: list[ParsedTicket] = []
    for chunk in chunks:
        tickets = chunk.get("tickets", []) or []
        if not isinstance(tickets, list):
            raise AviasalesSearchParseError("aviasales_search_invalid_chunk")
        legs = chunk.get("flight_legs")
        if not isinstance(legs, list):
            if "flight_legs" in chunk or tickets:
                raise AviasalesSearchParseError("aviasales_search_invalid_chunk")
            continue
        for raw in tickets:
            ticket = _parse_ticket(raw, legs, airlines, agents)
            if ticket is not None:
                parsed.append(ticket)

    parsed.sort(key=lambda t: t.best_proposal.price_minor_units)
    deduped: list[ParsedTicket] = []
    seen: set[tuple[str, str]] = set()
    for ticket in parsed:
        key = (ticket.ticket_signature, ticket.best_proposal.proposal_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ticket)
    return tuple(deduped)


def _parse_ticket(
    raw: Any,
    legs: list[Any],
    airlines: dict[str, Any],
    agents: dict[str, Any],
) -> ParsedTicket | None:
    if not isinstance(raw, dict):
        return None
    segments_raw = raw.get("segments")
    if not isinstance(segments_raw, list) or not segments_raw:
        return None
    proposals_raw = raw.get("proposals")
    if not isinstance(proposals_raw, list) or not proposals_raw:
        return None

    segments: list[tuple[ParsedSegment, ...]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            return None
        flights = seg.get("flights")
        if not isinstance(flights, list):
            return None
        seg_segments: list[ParsedSegment] = []
        for fi in flights:
            if not isinstance(fi, int) or fi < 0 or fi >= len(legs):
                return None
            leg = legs[fi]
            if not isinstance(leg, dict):
                return None
            seg_segments.append(_parse_segment(leg, airlines))
        segments.append(tuple(seg_segments))

    flat = [seg for group in segments for seg in group]
    if not flat:
        return None
    origin = flat[0].origin
    destination = flat[-1].destination
    first_depart = flat[0].depart_at
    departure_date = first_depart[:10]
    return_date = segments[-1][0].depart_at[:10] if len(segments) > 1 else None

    best = _cheapest_proposal(proposals_raw, agents)
    if best is None:
        return None
    return ParsedTicket(
        ticket_signature=str(raw.get("signature") or ""),
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        segments=tuple(segments),
        best_proposal=best,
    )


def _parse_segment(leg: dict[str, Any], airlines: dict[str, Any]) -> ParsedSegment:
    carrier = leg.get("operating_carrier_designator") or {}
    if not isinstance(carrier, dict):
        carrier = {}
    airline_code = str(carrier.get("carrier") or "")
    number = str(carrier.get("number") or "")
    airline_name = _airline_name(airlines.get(airline_code))
    return ParsedSegment(
        airline_code=airline_code,
        airline_name=airline_name,
        flight_number=f"{airline_code}{number}" if airline_code and number else number,
        origin=str(leg.get("origin") or ""),
        destination=str(leg.get("destination") or ""),
        depart_at=str(leg.get("local_departure_date_time") or ""),
        arrive_at=str(leg.get("local_arrival_date_time") or ""),
    )


def _cheapest_proposal(
    proposals: list[Any],
    agents: dict[str, Any],
) -> ParsedProposal | None:
    best: ParsedProposal | None = None
    best_value: int | None = None
    for raw in proposals:
        if not isinstance(raw, dict):
            continue
        price = raw.get("price")
        if not isinstance(price, dict):
            continue
        value = price.get("value")
        if not isinstance(value, int | float) or isinstance(value, bool):
            continue
        if isinstance(value, float) and not value.is_integer():
            continue
        major = int(value)
        if best_value is not None and major >= best_value:
            continue
        proposal = _parse_proposal(raw, major, str(price.get("currency_code") or ""), agents)
        if proposal is None:
            continue
        best = proposal
        best_value = major
    return best


def _parse_proposal(
    raw: dict[str, Any],
    price_major: int,
    currency: str,
    agents: dict[str, Any],
) -> ParsedProposal | None:
    proposal_id = str(raw.get("id") or "")
    if not proposal_id:
        return None
    agent_id_raw = raw.get("agent_id")
    if not isinstance(agent_id_raw, int):
        return None
    agent = agents.get(str(agent_id_raw))
    gate_name = _agent_name(agent) if isinstance(agent, dict) else ""
    baggage_count, handbag = _parse_baggage(raw.get("flight_terms"))
    return ParsedProposal(
        proposal_id=proposal_id,
        agent_id=agent_id_raw,
        price_minor_units=price_major * 100,
        currency=currency.upper() or "RUB",
        gate_name=gate_name,
        baggage_count=baggage_count,
        handbag=handbag,
    )


def _parse_baggage(flight_terms: Any) -> tuple[int | None, str | None]:
    if not isinstance(flight_terms, dict):
        return None, None
    baggage_count: int | None = None
    handbag: str | None = None
    for value in flight_terms.values():
        if not isinstance(value, dict):
            continue
        if baggage_count is None:
            bag = value.get("baggage")
            if isinstance(bag, dict) and isinstance(bag.get("count"), int):
                baggage_count = bag["count"]
        if handbag is None:
            handbags = value.get("handbags")
            if isinstance(handbags, dict):
                count = handbags.get("count")
                weight = handbags.get("weight")
                if isinstance(count, int) and count > 0:
                    handbag = (
                        f"{count}x{weight}kg" if isinstance(weight, (int, float)) else f"{count}x"
                    )
    return baggage_count, handbag


def _airline_name(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    return _localized_name(raw.get("name"))


def _agent_name(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    label = _localized_name(raw.get("label"))
    return label or str(raw.get("gate_name") or "")


def _localized_name(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if not isinstance(obj, dict):
        return ""
    ru = obj.get("ru")
    if isinstance(ru, dict):
        return str(ru.get("default") or ru.get("name") or "")
    if isinstance(ru, str):
        return ru
    default = obj.get("default")
    if isinstance(default, dict):
        return str(default.get("default") or default.get("name") or "")
    if isinstance(default, str):
        return default
    return ""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
