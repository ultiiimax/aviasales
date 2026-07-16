from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from flight_hunter.domain.agent_evidence import (
    CheckedBaggageState,
    ConfirmationState,
    DiscoverySource,
    ProtectionStatus,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.providers.aviasales_search.client import CalendarPrice, HotOffer
from flight_hunter.providers.aviasales_search.mapper import (
    map_parsed_ticket,
    map_parsed_ticket_to_evidence,
    stable_ticket_id,
)
from flight_hunter.providers.aviasales_search.schemas import (
    ParsedProposal,
    ParsedSegment,
    ParsedTicket,
)

EVIDENCE_NAMESPACE = UUID("11111111-1111-4111-8111-111111111111")
OTHER_EVIDENCE_NAMESPACE = UUID("22222222-2222-4222-8222-222222222222")


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
        results_url="results-fixture.aviasales.ru",
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
        "results_url": "results-fixture.aviasales.ru",
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
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    repeated = mapper.map_parsed_ticket_to_evidence(
        ticket,
        observed_at=observed_at,
        passengers=2,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    other_operation = mapper.map_parsed_ticket_to_evidence(
        ticket,
        observed_at=observed_at,
        passengers=2,
        evidence_namespace=OTHER_EVIDENCE_NAMESPACE,
    )

    assert evidence == repeated
    assert evidence.id != other_operation.id
    assert evidence.provider_offer_id == other_operation.provider_offer_id
    assert evidence.segment_ids == other_operation.segment_ids
    assert evidence.provider_id == "aviasales_search"
    assert re.fullmatch(r"aviasales_search:[0-9a-f]{64}", evidence.provider_offer_id)
    assert "sig_redacted_0" not in evidence.provider_offer_id
    assert "120:0" not in evidence.provider_offer_id
    assert evidence.total_amount == Money(580300, "RUB")
    assert evidence.passengers == 2
    assert evidence.observed_at == observed_at
    assert evidence.seller_name == "Trip.com"
    assert evidence.baggage_summary is None
    assert evidence.checked_baggage is CheckedBaggageState.NOT_INCLUDED
    assert evidence.protection_status is ProtectionStatus.UNKNOWN
    assert evidence.confirmation_state is ConfirmationState.CONFIRMED
    assert len(evidence.segment_ids) == len(evidence.segments) == 1
    assert evidence.segment_ids[0].startswith("aviasales_segment:")
    assert evidence.segments[0].flight_number == "DP6821"
    assert not hasattr(evidence, "booking_action_ref")
    assert not hasattr(evidence, "search_id")
    assert not hasattr(evidence, "results_url")


@pytest.mark.parametrize(
    ("baggage_count", "expected"),
    (
        (1, CheckedBaggageState.INCLUDED),
        (0, CheckedBaggageState.NOT_INCLUDED),
        (None, CheckedBaggageState.UNKNOWN),
        (-1, CheckedBaggageState.UNKNOWN),
    ),
)
def test_confirmed_evidence_preserves_checked_baggage_tristate(
    baggage_count: int | None,
    expected: CheckedBaggageState,
) -> None:
    evidence = map_parsed_ticket_to_evidence(
        _ticket(baggage_count=baggage_count, handbag=None),
        observed_at=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
        passengers=1,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )

    assert evidence.checked_baggage is expected


def test_calendar_discovery_uuid_is_idempotent_only_within_operation_namespace() -> None:
    from flight_hunter.providers.aviasales_search import mapper

    price = CalendarPrice(
        origin="SVO",
        destination="LED",
        departure_date="2026-09-15",
        return_date=None,
        price_minor_units=432_100,
        currency="RUB",
    )
    observed_at = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)

    first = mapper.map_calendar_price_to_discovery(
        price,
        observed_at=observed_at,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    repeated = mapper.map_calendar_price_to_discovery(
        price,
        observed_at=observed_at,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    other_operation = mapper.map_calendar_price_to_discovery(
        price,
        observed_at=observed_at,
        evidence_namespace=OTHER_EVIDENCE_NAMESPACE,
    )

    assert first.id == repeated.id
    assert first.id != other_operation.id
    assert first.passengers == 1


def test_hot_offer_mapper_binds_every_sanitized_field_to_approved_request() -> None:
    from flight_hunter.providers.aviasales_search import mapper

    observed_at = datetime(2026, 7, 14, 21, 0, tzinfo=UTC)
    offer = HotOffer(
        origin="SVO",
        destination="CDG",
        departure_date="2026-09-15",
        return_date=None,
        price_minor_units=123_400,
        currency="RUB",
    )

    signal = mapper.map_hot_offer_to_discovery(
        offer,
        expected_origin="SVO",
        date_from=date(2026, 9, 14),
        date_to=date(2026, 9, 16),
        expected_currency="RUB",
        one_way=True,
        observed_at=observed_at,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    repeated = mapper.map_hot_offer_to_discovery(
        offer,
        expected_origin="SVO",
        date_from=date(2026, 9, 14),
        date_to=date(2026, 9, 16),
        expected_currency="RUB",
        one_way=True,
        observed_at=observed_at,
        evidence_namespace=EVIDENCE_NAMESPACE,
    )
    other_operation = mapper.map_hot_offer_to_discovery(
        offer,
        expected_origin="SVO",
        date_from=date(2026, 9, 14),
        date_to=date(2026, 9, 16),
        expected_currency="RUB",
        one_way=True,
        observed_at=observed_at,
        evidence_namespace=OTHER_EVIDENCE_NAMESPACE,
    )

    assert signal == repeated
    assert signal.id != other_operation.id
    assert signal.source_kind is DiscoverySource.HOT_OFFER
    assert signal.observed_amount == Money(123_400, "RUB")
    assert signal.passengers == 1
    assert signal.observed_at == observed_at


@pytest.mark.parametrize(
    "override",
    (
        {"origin": "LED"},
        {"destination": "PARIS"},
        {"destination": "SVO"},
        {"departure_date": None},
        {"departure_date": "2026-09-17"},
        {"return_date": "2026-09-20"},
        {"price_minor_units": None},
        {"price_minor_units": -1},
        {"currency": "USD"},
    ),
)
def test_hot_offer_mapper_rejects_missing_invalid_or_provider_mismatched_rows(
    override: dict[str, object],
) -> None:
    from dataclasses import replace

    from flight_hunter.providers.aviasales_search import mapper

    offer = replace(
        HotOffer(
            origin="SVO",
            destination="CDG",
            departure_date="2026-09-15",
            return_date=None,
            price_minor_units=123_400,
            currency="RUB",
        ),
        **override,
    )

    with pytest.raises((TypeError, ValueError)):
        mapper.map_hot_offer_to_discovery(
            offer,
            expected_origin="SVO",
            date_from=date(2026, 9, 14),
            date_to=date(2026, 9, 16),
            expected_currency="RUB",
            one_way=True,
            observed_at=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
            evidence_namespace=EVIDENCE_NAMESPACE,
        )


def test_hot_offer_mapper_rejects_naive_observation_time() -> None:
    from flight_hunter.providers.aviasales_search import mapper

    with pytest.raises(ValueError, match="timezone"):
        mapper.map_hot_offer_to_discovery(
            HotOffer(
                origin="SVO",
                destination="CDG",
                departure_date="2026-09-15",
                return_date=None,
                price_minor_units=123_400,
                currency="RUB",
            ),
            expected_origin="SVO",
            date_from=date(2026, 9, 14),
            date_to=date(2026, 9, 16),
            expected_currency="RUB",
            one_way=True,
            observed_at=datetime(2026, 7, 14, 21, 0),
            evidence_namespace=EVIDENCE_NAMESPACE,
        )


def test_hot_offer_mapper_rejects_non_datetime_observation_time() -> None:
    from flight_hunter.providers.aviasales_search import mapper

    with pytest.raises(TypeError, match="datetime"):
        mapper.map_hot_offer_to_discovery(
            HotOffer(
                origin="SVO",
                destination="CDG",
                departure_date="2026-09-15",
                return_date=None,
                price_minor_units=123_400,
                currency="RUB",
            ),
            expected_origin="SVO",
            date_from=date(2026, 9, 14),
            date_to=date(2026, 9, 16),
            expected_currency="RUB",
            one_way=True,
            observed_at="not-a-datetime",  # type: ignore[arg-type]
            evidence_namespace=EVIDENCE_NAMESPACE,
        )
