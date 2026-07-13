from __future__ import annotations

import json
from pathlib import Path

from flight_hunter.providers.aviasales_search.schemas import parse_chunks

FIXTURE = Path("tests/fixtures/provider/aviasales_search/raw_chunk_mow_led.json")


def _load_chunk() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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
