from __future__ import annotations

from datetime import datetime

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, PriceBasis
from flight_hunter.providers.aviasales_data.client import AviasalesDataItem, stable_item_id


def map_prices_for_dates_item(
    item: AviasalesDataItem,
    *,
    observed_at: datetime,
    passengers: int,
) -> FlightOffer:
    if passengers != 1:
        raise ValueError("aviasales_data_cached_prices_support_single_adult_only")
    return FlightOffer(
        provider_id="aviasales_data",
        provider_offer_id=stable_item_id(item),
        origin=item.origin,
        destination=item.destination,
        departure_date=item.departure_date,
        return_date=item.return_date,
        total_price=Money(item.price_minor_units, item.currency),
        passengers=passengers,
        observed_at=observed_at,
        freshness=Freshness.CACHED,
        requires_live_confirmation=True,
        baggage_summary=None,
        price_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
    )
