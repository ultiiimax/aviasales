from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, PriceBasis
from flight_hunter.itinerary_engine.risk import (
    OfferRiskFlag,
    OfferRiskLevel,
    assess_offer_risk,
)

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def test_live_offer_with_baggage_has_low_risk() -> None:
    assessment = assess_offer_risk(
        _offer(
            freshness=Freshness.LIVE,
            requires_live_confirmation=False,
            baggage_summary="carry-on included",
        )
    )

    assert assessment.level == OfferRiskLevel.LOW
    assert assessment.flags == ()
    assert assessment.explanations == ()


def test_cached_offer_explains_external_confirmation_and_baggage_unknown() -> None:
    assessment = assess_offer_risk(
        _offer(
            freshness=Freshness.CACHED,
            requires_live_confirmation=True,
            baggage_summary=None,
        )
    )

    assert assessment.level == OfferRiskLevel.MEDIUM
    assert assessment.flags == (
        OfferRiskFlag.CACHED_PRICE,
        OfferRiskFlag.REQUIRES_LIVE_CONFIRMATION,
        OfferRiskFlag.BAGGAGE_UNKNOWN,
    )
    assert assessment.explanations == (
        "Price came from cached data and must be checked before purchase.",
        "Provider requires a live confirmation before purchase.",
        "Baggage and fare-rule data are not available for this offer.",
    )


def test_stale_price_is_high_risk_even_with_baggage() -> None:
    assessment = assess_offer_risk(
        _offer(
            freshness=Freshness.STALE,
            requires_live_confirmation=False,
            baggage_summary="checked bag included",
        )
    )

    assert assessment.level == OfferRiskLevel.HIGH
    assert assessment.flags == (OfferRiskFlag.STALE_PRICE,)
    assert assessment.explanations == ("Price is stale and must not be treated as available.",)


def test_provider_single_adult_ticket_price_basis_is_visible() -> None:
    assessment = assess_offer_risk(
        _offer(
            freshness=Freshness.API_CACHED,
            price_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
            requires_live_confirmation=True,
        )
    )

    assert assessment.level == OfferRiskLevel.MEDIUM
    assert assessment.flags == (
        OfferRiskFlag.CACHED_PRICE,
        OfferRiskFlag.REQUIRES_LIVE_CONFIRMATION,
        OfferRiskFlag.PROVIDER_SINGLE_ADULT_TICKET,
    )


def _offer(
    *,
    freshness: Freshness,
    requires_live_confirmation: bool,
    baggage_summary: str | None = "carry-on included",
    price_basis: PriceBasis = PriceBasis.TOTAL_FOR_PASSENGERS,
) -> FlightOffer:
    return FlightOffer(
        provider_id="fake",
        provider_offer_id="offer-1",
        origin="WAW",
        destination="BCN",
        departure_date="2026-10-12",
        return_date="2026-10-19",
        total_price=Money(159_800, "PLN"),
        passengers=1,
        observed_at=NOW,
        freshness=freshness,
        requires_live_confirmation=requires_live_confirmation,
        baggage_summary=baggage_summary,
        price_basis=price_basis,
    )
