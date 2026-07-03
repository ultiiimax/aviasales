from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flight_hunter.domain.offers import FlightOffer, Freshness, PriceBasis


class OfferRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class OfferRiskFlag(StrEnum):
    CACHED_PRICE = "cached_price"
    STALE_PRICE = "stale_price"
    UNKNOWN_FRESHNESS = "unknown_freshness"
    REQUIRES_LIVE_CONFIRMATION = "requires_live_confirmation"
    BAGGAGE_UNKNOWN = "baggage_unknown"
    PROVIDER_SINGLE_ADULT_TICKET = "provider_single_adult_ticket"


@dataclass(frozen=True, slots=True)
class OfferRiskAssessment:
    level: OfferRiskLevel
    flags: tuple[OfferRiskFlag, ...]
    explanations: tuple[str, ...]


def assess_offer_risk(offer: FlightOffer) -> OfferRiskAssessment:
    flags: list[OfferRiskFlag] = []
    explanations: list[str] = []

    _append_freshness_risk(offer.freshness, flags=flags, explanations=explanations)
    if offer.requires_live_confirmation:
        flags.append(OfferRiskFlag.REQUIRES_LIVE_CONFIRMATION)
        explanations.append("Provider requires a live confirmation before purchase.")
    if offer.baggage_summary is None:
        flags.append(OfferRiskFlag.BAGGAGE_UNKNOWN)
        explanations.append("Baggage and fare-rule data are not available for this offer.")
    if PriceBasis(offer.price_basis) == PriceBasis.PROVIDER_SINGLE_ADULT_TICKET:
        flags.append(OfferRiskFlag.PROVIDER_SINGLE_ADULT_TICKET)
        explanations.append("Provider price basis is a single adult ticket.")

    return OfferRiskAssessment(
        level=_risk_level(tuple(flags)),
        flags=tuple(flags),
        explanations=tuple(explanations),
    )


def _append_freshness_risk(
    freshness: Freshness,
    *,
    flags: list[OfferRiskFlag],
    explanations: list[str],
) -> None:
    if freshness in {Freshness.CACHED, Freshness.API_CACHED}:
        flags.append(OfferRiskFlag.CACHED_PRICE)
        explanations.append("Price came from cached data and must be checked before purchase.")
    elif freshness == Freshness.STALE:
        flags.append(OfferRiskFlag.STALE_PRICE)
        explanations.append("Price is stale and must not be treated as available.")
    elif freshness == Freshness.UNKNOWN_EXTERNAL:
        flags.append(OfferRiskFlag.UNKNOWN_FRESHNESS)
        explanations.append("Price freshness is unknown and must be checked externally.")


def _risk_level(flags: tuple[OfferRiskFlag, ...]) -> OfferRiskLevel:
    if OfferRiskFlag.STALE_PRICE in flags or OfferRiskFlag.UNKNOWN_FRESHNESS in flags:
        return OfferRiskLevel.HIGH
    if flags:
        return OfferRiskLevel.MEDIUM
    return OfferRiskLevel.LOW
