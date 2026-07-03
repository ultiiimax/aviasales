from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from flight_hunter.domain.offers import FlightOffer
from flight_hunter.domain.search_results import Confidence, DealCandidate

AVIASALES_MANUAL_CHECK_URL = "https://www.aviasales.ru/"


@dataclass(frozen=True, slots=True)
class AviasalesCachedDealSeed:
    candidate: DealCandidate
    raw_ref: str


def build_aviasales_cached_deal_seeds(
    offers: tuple[FlightOffer, ...],
    *,
    radar_kind: str,
    expires_at: datetime,
) -> tuple[AviasalesCachedDealSeed, ...]:
    return tuple(
        AviasalesCachedDealSeed(
            candidate=DealCandidate(
                source_id="aviasales_data",
                url=AVIASALES_MANUAL_CHECK_URL,
                title=f"Aviasales Data cached {radar_kind} {offer.origin} -> {offer.destination}",
                summary_ru=_summary(offer, radar_kind=radar_kind),
                extracted_price=offer.total_price,
                extracted_origin=offer.origin,
                extracted_destination=offer.destination,
                extracted_date_window=_date_window(offer),
                confidence=Confidence.LOW,
                discovered_at=offer.observed_at,
                requires_manual_verification=True,
                expires_at=expires_at,
            ),
            raw_ref=_raw_ref(offer, radar_kind=radar_kind),
        )
        for offer in offers
    )


def aviasales_cached_deal_seed_id(
    *,
    household_id: UUID,
    user_id: UUID,
    search_id: str,
    seed: AviasalesCachedDealSeed,
) -> UUID:
    raw = "|".join(
        (
            "flight-hunter:aviasales-cached-deal-seed",
            str(household_id),
            str(user_id),
            search_id,
            seed.raw_ref,
        )
    )
    return uuid5(NAMESPACE_URL, raw)


def _summary(offer: FlightOffer, *, radar_kind: str) -> str:
    return (
        f"Aviasales Data cached {radar_kind} found a {_price_basis_value(offer)} hint for "
        f"{offer.origin} -> {offer.destination} on {_date_window(offer)} at "
        f"{offer.total_price}. This is cached data, not live availability or a booking link; "
        "verify manually on the external site."
    )


def _date_window(offer: FlightOffer) -> str:
    if offer.return_date is None:
        return offer.departure_date
    return f"{offer.departure_date}..{offer.return_date}"


def _raw_ref(offer: FlightOffer, *, radar_kind: str) -> str:
    return f"aviasales_data:{radar_kind}:{offer.provider_offer_id}"[:240]


def _price_basis_value(offer: FlightOffer) -> str:
    return getattr(offer.price_basis, "value", str(offer.price_basis))
