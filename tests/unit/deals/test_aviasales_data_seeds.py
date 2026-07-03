from __future__ import annotations

from datetime import UTC, datetime, timedelta

from flight_hunter.deals.aviasales_data_seeds import build_aviasales_cached_deal_seeds
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness, PriceBasis
from flight_hunter.domain.search_results import Confidence

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


def test_aviasales_cached_deal_seed_is_manual_verification_candidate_only() -> None:
    offer = FlightOffer(
        provider_id="aviasales_data",
        provider_offer_id="aviasales_data:abc",
        origin="MOW",
        destination="IST",
        departure_date="2026-09-10",
        return_date="2026-09-20",
        total_price=Money(1_842_000, "RUB"),
        passengers=1,
        observed_at=NOW,
        freshness=Freshness.CACHED,
        requires_live_confirmation=True,
        baggage_summary=None,
        price_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
    )

    seeds = build_aviasales_cached_deal_seeds(
        (offer,),
        radar_kind="special_offers",
        expires_at=NOW + timedelta(hours=6),
    )

    assert len(seeds) == 1
    seed = seeds[0]
    candidate = seed.candidate
    assert candidate.source_id == "aviasales_data"
    assert candidate.url == "https://www.aviasales.ru/"
    assert candidate.title == "Aviasales Data cached special_offers MOW -> IST"
    assert candidate.extracted_price == Money(1_842_000, "RUB")
    assert candidate.extracted_origin == "MOW"
    assert candidate.extracted_destination == "IST"
    assert candidate.extracted_date_window == "2026-09-10..2026-09-20"
    assert candidate.confidence == Confidence.LOW
    assert candidate.requires_manual_verification is True
    assert candidate.expires_at == NOW + timedelta(hours=6)
    assert "cached" in candidate.summary_ru
    assert "not live availability" in candidate.summary_ru
    assert "provider_single_adult_ticket" in candidate.summary_ru
    assert seed.raw_ref == "aviasales_data:special_offers:aviasales_data:abc"
    assert "signed" not in seed.raw_ref.lower()
