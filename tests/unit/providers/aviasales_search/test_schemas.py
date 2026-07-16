from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC
from pathlib import Path

import pytest

from flight_hunter.providers.aviasales_search.schemas import (
    AviasalesSearchParseError,
    parse_chunks,
)

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")


def _load_chunk() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _synthetic_round_trip_chunk() -> dict[str, object]:
    return {
        "agents": {"1": {"gate_name": "Fixture Gate"}},
        "airlines": {"FH": {"name": {"ru": {"default": "Fixture Air"}}}},
        "flight_legs": [
            {
                "origin": "MOW",
                "destination": "LED",
                "local_departure_date_time": "2026-09-15 10:00",
                "local_arrival_date_time": "2026-09-15 11:30",
                "operating_carrier_designator": {"carrier": "FH", "number": "101"},
            },
            {
                "origin": "LED",
                "destination": "MOW",
                "local_departure_date_time": "2026-09-22 18:00",
                "local_arrival_date_time": "2026-09-22 19:30",
                "operating_carrier_designator": {"carrier": "FH", "number": "102"},
            },
        ],
        "tickets": [
            {
                "signature": "private-ticket-signature",
                "segments": [{"flights": [0]}, {"flights": [1]}],
                "proposals": [
                    {
                        "id": "1:0",
                        "agent_id": 1,
                        "price": {"value": 100, "currency_code": "RUB"},
                    }
                ],
            }
        ],
    }


def test_parse_chunks_returns_sorted_deduped_tickets_from_real_fixture() -> None:
    tickets = parse_chunks([_load_chunk()])

    assert len(tickets) == 5
    prices = [t.best_proposal.price_minor_units for t in tickets]
    assert prices == sorted(prices)
    assert prices[0] <= prices[-1]
    assert all(t.best_proposal.currency == "RUB" for t in tickets)
    assert all(t.departure_date == "2026-09-15" for t in tickets)
    assert all(t.destination == "LED" for t in tickets)
    assert all(t.segments for t in tickets)
    assert all(t.best_proposal.proposal_id for t in tickets)
    assert all(t.best_proposal.gate_name for t in tickets)


def test_parse_chunks_dedupes_repeated_chunks_by_signature_and_proposal() -> None:
    chunk = _load_chunk()
    tickets = parse_chunks([chunk, chunk])

    assert len(tickets) == 5


def test_parse_chunks_first_ticket_segments_carry_airline_and_route() -> None:
    tickets = parse_chunks([_load_chunk()])
    first = tickets[0]
    segment = first.segments[0][0]

    assert segment.origin in {"SVO", "DME", "VKO", "ZIA", "BKA"}
    assert segment.airline_code
    assert segment.flight_number.startswith(segment.airline_code)
    assert segment.depart_at_utc is not None
    assert segment.arrive_at_utc is not None
    assert segment.depart_at_utc.tzinfo is UTC
    assert segment.arrive_at_utc > segment.depart_at_utc


def test_parse_chunks_rejects_inverted_verified_unix_segment_instants() -> None:
    chunk = _load_chunk()
    legs = chunk["flight_legs"]
    assert isinstance(legs, list) and isinstance(legs[0], dict)
    legs[0]["arrival_unix_timestamp"] = legs[0]["departure_unix_timestamp"] - 1

    with pytest.raises(AviasalesSearchParseError, match="invalid_segment_instants"):
        parse_chunks([chunk])


def test_parse_chunks_empty_input_returns_empty() -> None:
    assert parse_chunks([]) == ()


def test_parse_chunks_skips_tickets_when_flight_legs_missing() -> None:
    chunk = _load_chunk()
    assert isinstance(chunk, dict)
    without_legs = {**chunk, "flight_legs": []}
    tickets = parse_chunks([without_legs])

    assert tickets == ()


def test_parse_chunks_skips_malformed_ticket_without_raising() -> None:
    chunk = _load_chunk()
    assert isinstance(chunk, dict)
    malformed = {**chunk, "tickets": [{"segments": "not-a-list"}]}
    tickets = parse_chunks([malformed])

    assert tickets == ()


def test_parse_chunks_normalizes_reciprocal_round_trip_route() -> None:
    ticket = parse_chunks([_synthetic_round_trip_chunk()])[0]

    assert ticket.origin == "MOW"
    assert ticket.destination == "LED"
    assert ticket.departure_date == "2026-09-15"
    assert ticket.return_date == "2026-09-22"


@pytest.mark.parametrize(
    "corruption",
    ["empty_direction", "discontinuous_direction", "nonreciprocal_return", "extra_direction"],
)
def test_parse_chunks_rejects_corrupt_direction_groups(corruption: str) -> None:
    chunk = deepcopy(_synthetic_round_trip_chunk())
    tickets = chunk["tickets"]
    legs = chunk["flight_legs"]
    assert isinstance(tickets, list) and isinstance(tickets[0], dict)
    assert isinstance(legs, list)
    segments = tickets[0]["segments"]
    assert isinstance(segments, list)
    if corruption == "empty_direction":
        segments[0] = {"flights": []}
    elif corruption == "discontinuous_direction":
        segments[:] = [{"flights": [0, 1]}]
        assert isinstance(legs[1], dict)
        legs[1]["origin"] = "CDG"
    elif corruption == "nonreciprocal_return":
        assert isinstance(legs[1], dict)
        legs[1]["origin"] = "CDG"
    else:
        legs.append(deepcopy(legs[0]))
        segments.append({"flights": [2]})

    with pytest.raises(AviasalesSearchParseError):
        parse_chunks([chunk])


@pytest.mark.parametrize("currency", [None, "РУБ", "US1"])
def test_parse_chunks_rejects_missing_or_non_ascii_proposal_currency(
    currency: str | None,
) -> None:
    chunk = _synthetic_round_trip_chunk()
    tickets = chunk["tickets"]
    assert isinstance(tickets, list) and isinstance(tickets[0], dict)
    proposals = tickets[0]["proposals"]
    assert isinstance(proposals, list) and isinstance(proposals[0], dict)
    price = proposals[0]["price"]
    assert isinstance(price, dict)
    if currency is None:
        price.pop("currency_code")
    else:
        price["currency_code"] = currency

    with pytest.raises(AviasalesSearchParseError):
        parse_chunks([chunk])


def test_parse_chunks_rejects_negative_proposal_price() -> None:
    chunk = _synthetic_round_trip_chunk()
    tickets = chunk["tickets"]
    assert isinstance(tickets, list) and isinstance(tickets[0], dict)
    proposals = tickets[0]["proposals"]
    assert isinstance(proposals, list) and isinstance(proposals[0], dict)
    price = proposals[0]["price"]
    assert isinstance(price, dict)
    price["value"] = -1

    with pytest.raises(AviasalesSearchParseError):
        parse_chunks([chunk])
