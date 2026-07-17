from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from flight_hunter.domain.agent_search import LocationScopeKind

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class AviasalesSearchParseError(RuntimeError):
    """Raised when a raw Aviasales Search chunk cannot be parsed safely."""


@dataclass(frozen=True, slots=True)
class ProviderLocation:
    kind: LocationScopeKind
    code: str

    def __post_init__(self) -> None:
        kind = LocationScopeKind(self.kind)
        if kind not in {LocationScopeKind.AIRPORT, LocationScopeKind.CITY}:
            raise ValueError("provider location kind must be airport or city")
        if not isinstance(self.code, str):
            raise TypeError("provider location code must be a string")
        code = self.code.upper()
        if not _IATA_RE.fullmatch(code):
            raise ValueError("provider location code must be a three-letter IATA code")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "code", code)

    @property
    def is_airport(self) -> bool:
        return self.kind is LocationScopeKind.AIRPORT


@dataclass(frozen=True, slots=True)
class ParsedSegment:
    airline_code: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    depart_at: str
    arrive_at: str
    depart_at_utc: datetime | None = None
    arrive_at_utc: datetime | None = None


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
    provider_airport_changes: tuple[tuple[str, str], ...] = ()


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
    if len(segments_raw) > 2:
        raise AviasalesSearchParseError("aviasales_search_invalid_directions")
    proposals_raw = raw.get("proposals")
    if not isinstance(proposals_raw, list) or not proposals_raw:
        return None

    segments: list[tuple[ParsedSegment, ...]] = []
    provider_airport_changes: list[tuple[str, str]] = []
    for seg in segments_raw:
        if not isinstance(seg, dict):
            return None
        flights = seg.get("flights")
        if not isinstance(flights, list):
            return None
        if not flights:
            raise AviasalesSearchParseError("aviasales_search_invalid_directions")
        seg_segments: list[ParsedSegment] = []
        for fi in flights:
            if not isinstance(fi, int) or fi < 0 or fi >= len(legs):
                return None
            leg = legs[fi]
            if not isinstance(leg, dict):
                return None
            seg_segments.append(_parse_segment(leg, airlines))
        direction = tuple(seg_segments)
        direction_airport_changes = _provider_airport_changes(seg, direction)
        _require_valid_direction(
            direction,
            provider_airport_changes=direction_airport_changes,
        )
        segments.append(direction)
        provider_airport_changes.extend(direction_airport_changes)

    outbound = segments[0]
    origin = outbound[0].origin
    destination = outbound[-1].destination
    first_depart = outbound[0].depart_at
    departure_date = first_depart[:10]
    return_date: str | None = None
    if len(segments) == 2:
        inbound = segments[1]
        if inbound[0].origin != destination or inbound[-1].destination != origin:
            if _provider_marks_different_airports(raw):
                return None
            raise AviasalesSearchParseError("aviasales_search_invalid_directions")
        return_date = inbound[0].depart_at[:10]

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
        provider_airport_changes=tuple(provider_airport_changes),
    )


def _require_valid_direction(
    direction: tuple[ParsedSegment, ...],
    *,
    provider_airport_changes: tuple[tuple[str, str], ...],
) -> None:
    if not direction:
        raise AviasalesSearchParseError("aviasales_search_invalid_directions")
    for segment in direction:
        if not _IATA_RE.fullmatch(segment.origin) or not _IATA_RE.fullmatch(segment.destination):
            raise AviasalesSearchParseError("aviasales_search_invalid_directions")
    airport_changes = tuple(
        (previous.destination, current.origin)
        for previous, current in pairwise(direction)
        if previous.destination != current.origin
    )
    if airport_changes != provider_airport_changes:
        raise AviasalesSearchParseError("aviasales_search_invalid_directions")


def _provider_airport_changes(
    segment: dict[str, Any],
    direction: tuple[ParsedSegment, ...],
) -> tuple[tuple[str, str], ...]:
    transfers = segment.get("transfers")
    if not isinstance(transfers, list):
        return ()
    return tuple(
        (previous.destination, current.origin)
        for index, (previous, current) in enumerate(pairwise(direction))
        if previous.destination != current.origin
        and index < len(transfers)
        and isinstance(transfer := transfers[index], dict)
        and isinstance(tags := transfer.get("tags"), list)
        and "airport_change" in tags
    )


def _provider_marks_different_airports(ticket: dict[str, Any]) -> bool:
    tags = ticket.get("tags")
    return isinstance(tags, list) and "airport_different" in tags


def _parse_segment(leg: dict[str, Any], airlines: dict[str, Any]) -> ParsedSegment:
    carrier = leg.get("operating_carrier_designator") or {}
    if not isinstance(carrier, dict):
        carrier = {}
    airline_code = str(carrier.get("carrier") or "")
    number = str(carrier.get("number") or "")
    airline_name = _airline_name(airlines.get(airline_code))
    depart_at_utc, arrive_at_utc = _segment_instants(leg)
    return ParsedSegment(
        airline_code=airline_code,
        airline_name=airline_name,
        flight_number=f"{airline_code}{number}" if airline_code and number else number,
        origin=str(leg.get("origin") or ""),
        destination=str(leg.get("destination") or ""),
        depart_at=str(leg.get("local_departure_date_time") or ""),
        arrive_at=str(leg.get("local_arrival_date_time") or ""),
        depart_at_utc=depart_at_utc,
        arrive_at_utc=arrive_at_utc,
    )


def _segment_instants(leg: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    raw_depart = leg.get("departure_unix_timestamp")
    raw_arrive = leg.get("arrival_unix_timestamp")
    if raw_depart is None and raw_arrive is None:
        return None, None
    if (
        type(raw_depart) is not int
        or type(raw_arrive) is not int
        or raw_depart < 0
        or raw_arrive <= raw_depart
    ):
        raise AviasalesSearchParseError("aviasales_search_invalid_segment_instants")
    try:
        return (
            datetime.fromtimestamp(raw_depart, tz=UTC),
            datetime.fromtimestamp(raw_arrive, tz=UTC),
        )
    except (OverflowError, OSError, ValueError):
        raise AviasalesSearchParseError("aviasales_search_invalid_segment_instants") from None


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
        if major < 0:
            raise AviasalesSearchParseError("aviasales_search_invalid_money")
        currency = price.get("currency_code")
        if not isinstance(currency, str):
            raise AviasalesSearchParseError("aviasales_search_invalid_money")
        normalized_currency = currency.upper()
        if not _CURRENCY_RE.fullmatch(normalized_currency):
            raise AviasalesSearchParseError("aviasales_search_invalid_money")
        if best_value is not None and major >= best_value:
            continue
        proposal = _parse_proposal(raw, major, normalized_currency, agents)
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
    if price_major < 0 or not _CURRENCY_RE.fullmatch(currency):
        raise AviasalesSearchParseError("aviasales_search_invalid_money")
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
        currency=currency,
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
