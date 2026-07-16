from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from flight_hunter.application.agent_result_records import (
    confirmed_record_to_evidence,
)
from flight_hunter.domain.agent_evidence import (
    CheckedBaggageState,
    ProtectionStatus,
)
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentConfirmedOfferEvidenceRecord,
)


def test_legacy_confirmed_record_without_baggage_status_remains_readable_as_unknown() -> None:
    observed_at = datetime(2026, 7, 14, 10, tzinfo=UTC)
    record = AgentConfirmedOfferEvidenceRecord(
        id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee2"),
        household_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        run_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        stage_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        provider_id="aviasales_search",
        source="exact_search",
        observed_at=observed_at,
        freshness=Freshness.LIVE,
        passengers=1,
        passenger_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
        amount_minor=20_000,
        currency="RUB",
        itinerary_evidence={
            "origin": "LED",
            "destination": "CDG",
            "departure_date": "2026-09-10",
            "return_date": None,
            "passenger_mix": {"adults": 1, "children": 0, "infants": 0},
            "price_basis": "total_for_passengers",
            "segments": [
                {
                    "segment_ref": "legacy-segment",
                    "origin": "LED",
                    "destination": "CDG",
                    "depart_at": "2026-09-10 08:00",
                    "arrive_at": "2026-09-10 10:00",
                    "carrier": "FV",
                    "flight_number": "FV100",
                }
            ],
            "seller": "Legacy seller",
            "ticket_structure": "provider_ticket",
        },
        protection_status=ProtectionStatus.UNKNOWN,
        baggage_status=None,
        transfer_status=None,
        visa_status=None,
        fingerprint="sha256:" + "a" * 64,
        created_at=observed_at,
    )

    evidence = confirmed_record_to_evidence(record)

    assert evidence.checked_baggage is CheckedBaggageState.UNKNOWN
