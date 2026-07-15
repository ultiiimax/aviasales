from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from flight_hunter.domain.agent_evidence import ConfirmationState, ProtectionStatus
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.providers.aviasales_search.mapper import map_parsed_ticket, stable_ticket_id
from flight_hunter.providers.aviasales_search.schemas import (
    ParsedProposal,
    ParsedSegment,
    ParsedTicket,
)


def _ticket(baggage_count: int | None = 1, handbag: str | None = "1x8kg") -> ParsedTicket:
    return ParsedTicket(
        ticket_signature="sig_redacted_0",
        origin="SVO",
        destination="LED",
        departure_date="2026-09-15",
        return_date=None,
        segments=(
            (
                ParsedSegment(
                    airline_code="DP",
                    airline_name="Pobeda",
                    flight_number="DP6821",
                    origin="SVO",
                    destination="LED",
                    depart_at="2026-09-15 08:50",
                    arrive_at="2026-09-15 10:20",
                ),
            ),
        ),
        best_proposal=ParsedProposal(
            proposal_id="120:0",
            agent_id=120,
            price_minor_units=580300,
            currency="RUB",
            gate_name="Trip.com",
            baggage_count=baggage_count,
            handbag=handbag,
        ),
    )


def test_map_parsed_ticket_produces_live_total_for_passengers_offer() -> None:
    observed_at = datetime(2026, 7, 4, 23, 30, tzinfo=UTC)
    offer = map_parsed_ticket(
        _ticket(),
        observed_at=observed_at,
        passengers=1,
        search_id="sid-1",
        results_url="host-1",
    )

    assert offer.provider_id == "aviasales_search"
    assert offer.origin == "SVO"
    assert offer.destination == "LED"
    assert offer.departure_date == "2026-09-15"
    assert offer.return_date is None
    assert offer.total_price == Money(580300, "RUB")
    assert offer.passengers == 1
    assert offer.observed_at == observed_at
    assert offer.freshness == Freshness.LIVE
    assert offer.requires_live_confirmation is False
    assert offer.price_basis == PriceBasis.TOTAL_FOR_PASSENGERS
    assert offer.baggage_summary == "baggage:1, handbag:1x8kg"
    assert offer.seller_name == "Trip.com"
    assert offer.segments[0].flight_number == "DP6821"
    assert offer.segments[0].airline_name == "Pobeda"
    assert offer.booking_action_ref is not None
    ref = json.loads(offer.booking_action_ref)
    assert ref == {
        "provider_id": "aviasales_search",
        "proposal_id": "120:0",
        "results_url": "host-1",
        "search_id": "sid-1",
    }


def test_stable_ticket_id_is_deterministic() -> None:
    ticket = _ticket()
    assert stable_ticket_id(ticket) == stable_ticket_id(ticket)
    assert stable_ticket_id(ticket).startswith("aviasales_search:")


def test_map_parsed_ticket_baggage_summary_none_when_no_baggage() -> None:
    observed_at = datetime(2026, 7, 4, 23, 30, tzinfo=UTC)
    offer = map_parsed_ticket(
        _ticket(baggage_count=0, handbag=None), observed_at=observed_at, passengers=1
    )

    assert offer.baggage_summary is None


def test_map_parsed_ticket_to_confirmed_evidence_is_sanitized_and_deterministic() -> None:
    from flight_hunter.providers.aviasales_search import mapper

    observed_at = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)
    ticket = _ticket(baggage_count=0, handbag=None)

    evidence = mapper.map_parsed_ticket_to_evidence(
        ticket,
        observed_at=observed_at,
        passengers=2,
    )
    repeated = mapper.map_parsed_ticket_to_evidence(
        ticket,
        observed_at=observed_at,
        passengers=2,
    )

    assert evidence == repeated
    assert evidence.provider_id == "aviasales_search"
    assert re.fullmatch(r"aviasales_search:[0-9a-f]{64}", evidence.provider_offer_id)
    assert "sig_redacted_0" not in evidence.provider_offer_id
    assert "120:0" not in evidence.provider_offer_id
    assert evidence.total_amount == Money(580300, "RUB")
    assert evidence.passengers == 2
    assert evidence.observed_at == observed_at
    assert evidence.seller_name == "Trip.com"
    assert evidence.baggage_summary is None
    assert evidence.protection_status is ProtectionStatus.UNKNOWN
    assert evidence.confirmation_state is ConfirmationState.CONFIRMED
    assert len(evidence.segment_ids) == len(evidence.segments) == 1
    assert evidence.segment_ids[0].startswith("aviasales_segment:")
    assert evidence.segments[0].flight_number == "DP6821"
    assert not hasattr(evidence, "booking_action_ref")
    assert not hasattr(evidence, "search_id")
    assert not hasattr(evidence, "results_url")
