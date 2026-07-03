from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.providers.aviasales_data.client import AviasalesDataItem
from flight_hunter.providers.aviasales_data.mapper import map_prices_for_dates_item


def test_mapper_marks_data_api_offer_as_cached_and_requiring_live_confirmation() -> None:
    received_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    offer = map_prices_for_dates_item(
        AviasalesDataItem(
            origin="WAW",
            destination="BCN",
            origin_airport="WAW",
            destination_airport="BCN",
            price_minor_units=51200,
            currency="PLN",
            departure_date="2026-10-12",
            return_date="2026-10-19",
            airline="LO",
            flight_number="437",
            link_path="/search/WAW1210BCN1910",
        ),
        observed_at=received_at,
        passengers=1,
    )

    assert offer.provider_id == "aviasales_data"
    assert offer.total_price == Money(51200, "PLN")
    assert offer.price_basis == PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
    assert offer.freshness == Freshness.CACHED
    assert offer.observed_at == received_at
    assert offer.requires_live_confirmation
    assert "search" not in offer.provider_offer_id.lower()


def test_mapper_rejects_multi_passenger_inferred_totals() -> None:
    received_at = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="single_adult_only"):
        map_prices_for_dates_item(
            AviasalesDataItem(
                origin="WAW",
                destination="BCN",
                origin_airport="WAW",
                destination_airport="BCN",
                price_minor_units=51200,
                currency="PLN",
                departure_date="2026-10-12",
                return_date="2026-10-19",
                airline="LO",
                flight_number="437",
                link_path="/search/WAW1210BCN1910",
            ),
            observed_at=received_at,
            passengers=2,
        )
