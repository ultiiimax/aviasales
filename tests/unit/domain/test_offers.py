from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, PriceBasis


def test_flight_offer_defaults_to_total_for_passengers_price_basis() -> None:
    offer = _offer(passengers=2)

    assert offer.price_basis == PriceBasis.TOTAL_FOR_PASSENGERS


def test_flight_offer_rejects_single_adult_ticket_basis_for_multiple_passengers() -> None:
    with pytest.raises(ValueError, match="single-adult ticket prices require passengers=1"):
        _offer(
            passengers=2,
            price_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
        )


def _offer(
    *,
    passengers: int,
    price_basis: PriceBasis = PriceBasis.TOTAL_FOR_PASSENGERS,
) -> FlightOffer:
    return FlightOffer(
        provider_id="fake",
        provider_offer_id="offer-1",
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date=None,
        total_price=Money(100_000, "RUB"),
        passengers=passengers,
        observed_at=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        freshness=Freshness.CACHED,
        requires_live_confirmation=True,
        baggage_summary=None,
        price_basis=price_basis,
    )
