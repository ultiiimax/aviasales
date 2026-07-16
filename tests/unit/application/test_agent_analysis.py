from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from flight_hunter.application.agent_analysis import (
    AnomalyStatus,
    BuyTimingStatus,
    CurrencyComparisonStatus,
    assess_anomaly,
    assess_buy_timing,
    compare_currency_offers,
    history_series_hash,
    same_flight_fingerprint,
)
from flight_hunter.domain.agent_evidence import (
    BaggageKey,
    CardFeeAssumption,
    CheckedBaggageState,
    CurrencyBasis,
    CurrencyOfferFacts,
    FlightFingerprintSegment,
    FxRateObservation,
    HistoryAggregationMode,
    HistoryLegKey,
    HistoryObservation,
    HistorySeriesKey,
    ProductKey,
    RiskClass,
    StayWindow,
    TicketStructure,
)
from flight_hunter.domain.agent_search import TripShape
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import PassengerMix


def test_history_series_hash_is_deterministic_and_uses_project_prefix() -> None:
    key = _history_key()

    first = history_series_hash(key)
    second = history_series_hash(key)

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == 71


def test_history_series_hash_changes_for_every_material_market_dimension() -> None:
    base = _history_key()
    variants = (
        replace(
            base,
            ordered_leg_keys=(
                replace(base.ordered_leg_keys[0], destination="ORY"),
                base.ordered_leg_keys[1],
            ),
        ),
        replace(
            base,
            ordered_leg_keys=(
                replace(base.ordered_leg_keys[0], date_end=date(2026, 9, 11)),
                base.ordered_leg_keys[1],
            ),
        ),
        replace(base, stay=StayWindow(minimum_nights=6, maximum_nights=8)),
        replace(base, trip_shape=TripShape.OPEN_JAW),
        replace(base, cabin="premium_economy"),
        replace(base, passenger_mix=PassengerMix(adults=2, children=1)),
        replace(base, ticket_structure=TicketStructure.SPLIT_TICKET),
        replace(base, risk_class=RiskClass.MEDIUM),
        replace(
            base,
            baggage_key=BaggageKey(
                state=CheckedBaggageState.UNKNOWN,
                pieces=None,
                weight_kg=None,
            ),
        ),
        replace(
            base,
            currency_basis=CurrencyBasis(
                provider_currency="EUR",
                comparison_currency="RUB",
                fx_source="fixture-fx",
            ),
        ),
    )

    hashes = {history_series_hash(base), *(history_series_hash(value) for value in variants)}

    assert len(hashes) == len(variants) + 1


def test_same_product_hash_changes_for_provider_seller_and_fare_product() -> None:
    base_product = ProductKey(
        provider_id="aviasales_search",
        seller_or_gate="Fixture seller",
        fare_code="YLOW",
        fare_family="LIGHT",
    )
    base = replace(
        _history_key(),
        aggregation_mode=HistoryAggregationMode.SAME_PRODUCT,
        product_key=base_product,
    )
    variants = (
        replace(base, product_key=replace(base_product, provider_id="other-provider")),
        replace(base, product_key=replace(base_product, seller_or_gate="Other seller")),
        replace(base, product_key=replace(base_product, fare_code="YFLEX")),
        replace(base, product_key=replace(base_product, fare_family="FLEX")),
    )

    hashes = {history_series_hash(base), *(history_series_hash(value) for value in variants)}

    assert len(hashes) == len(variants) + 1


def test_history_aggregation_modes_never_mix_product_keys() -> None:
    product = ProductKey(
        provider_id="aviasales_search",
        seller_or_gate="Fixture seller",
        fare_code="YLOW",
        fare_family="LIGHT",
    )

    with pytest.raises(ValueError, match="market_minimum cannot contain product_key"):
        replace(_history_key(), product_key=product)

    with pytest.raises(ValueError, match="same_product requires product_key"):
        replace(
            _history_key(),
            aggregation_mode=HistoryAggregationMode.SAME_PRODUCT,
        )


@pytest.mark.parametrize(
    "history",
    (
        lambda: _spread_history(39),
        lambda: _spread_history(
            40,
            offsets=_cyclic_offsets(39, modulus=14, final=20),
        ),
        lambda: _spread_history(
            40,
            offsets=_cyclic_offsets(39, modulus=12, final=21),
        ),
    ),
)
def test_buy_timing_requires_all_general_history_gates(
    history: Callable[[], tuple[HistoryObservation, ...]],
) -> None:
    observations = history()

    assessment = assess_buy_timing(
        observations,
        _observation(
            9_000,
            datetime(2026, 11, 2, 10, tzinfo=UTC),
        ),
    )

    assert assessment.status is BuyTimingStatus.INSUFFICIENT_DATA
    assert assessment.watch_action_available
    assert assessment.current_percentile is None
    assert assessment.twentieth_percentile_minor_units is None
    assert assessment.calculation_version == "buy-timing-v1"


def test_buy_now_boundary_is_historically_low_at_the_twentieth_percentile() -> None:
    history = _spread_history(
        40,
        amounts=tuple(10_000 + index * 100 for index in range(40)),
    )

    at_boundary = assess_buy_timing(
        history,
        _observation(10_700, datetime(2026, 11, 2, 10, tzinfo=UTC)),
    )
    above_boundary = assess_buy_timing(
        history,
        _observation(10_701, datetime(2026, 11, 2, 10, tzinfo=UTC)),
    )

    assert at_boundary.status is BuyTimingStatus.HISTORICALLY_LOW
    assert not at_boundary.watch_action_available
    assert at_boundary.twentieth_percentile_minor_units == 10_700
    assert at_boundary.current_percentile == Decimal("20")
    assert at_boundary.sample_count == 40
    assert at_boundary.distinct_dates >= 14
    assert at_boundary.history_span_days >= 21
    assert at_boundary.timezone == "UTC"
    assert at_boundary.days_to_departure_band == "60+"
    assert above_boundary.status is BuyTimingStatus.NO_BUY_SIGNAL


def test_weekday_recommendation_requires_four_weeks_and_exact_five_percent_difference() -> None:
    at_boundary = assess_buy_timing(
        _weekday_history(best_amount=9_500),
        _observation(
            10_000,
            datetime(2026, 11, 2, 10, tzinfo=UTC),
            departure_date=date(2027, 3, 1),
        ),
    )
    below_boundary = assess_buy_timing(
        _weekday_history(best_amount=9_501),
        _observation(
            10_000,
            datetime(2026, 11, 2, 10, tzinfo=UTC),
            departure_date=date(2027, 3, 1),
        ),
    )

    assert at_boundary.recommended_weekday == 1
    assert at_boundary.weekday_savings_percent == Decimal("5")
    assert below_boundary.recommended_weekday is None
    assert below_boundary.weekday_savings_percent is None


def test_four_hour_recommendation_requires_matched_days_to_departure_band() -> None:
    matched = _hour_bucket_history(best_amount=9_500)
    mismatched = tuple(
        replace(
            observation,
            departure_date=date(2026, 11, 20),
        )
        if observation.observed_at.hour in {14, 15}
        else observation
        for observation in matched
    )
    current = _observation(
        10_000,
        datetime(2026, 11, 2, 10, tzinfo=UTC),
        departure_date=date(2027, 3, 1),
    )

    matched_assessment = assess_buy_timing(matched, current)
    mismatched_assessment = assess_buy_timing(mismatched, current)

    assert matched_assessment.recommended_four_hour_bucket == 12
    assert matched_assessment.four_hour_savings_percent == Decimal("5")
    assert mismatched_assessment.recommended_four_hour_bucket is None
    assert mismatched_assessment.four_hour_savings_percent is None


def test_buy_timing_rejects_mixed_history_series() -> None:
    history = list(_spread_history(40))
    history[-1] = replace(history[-1], series_hash="sha256:" + "f" * 64)

    with pytest.raises(ValueError, match="history observations must share one series"):
        assess_buy_timing(
            tuple(history),
            _observation(9_000, datetime(2026, 11, 2, 10, tzinfo=UTC)),
        )


def test_anomaly_requires_twenty_observations_and_seven_dates() -> None:
    too_few = _spread_history(19)
    too_few_dates = _spread_history(
        20,
        offsets=_cyclic_offsets(19, modulus=5, final=5),
    )
    current = _observation(6_000, datetime(2026, 11, 2, 10, tzinfo=UTC))

    assert assess_anomaly(too_few, current).status is AnomalyStatus.INSUFFICIENT_DATA
    assert assess_anomaly(too_few_dates, current).status is AnomalyStatus.INSUFFICIENT_DATA


def test_anomaly_threshold_is_suspected_only_at_sixty_percent_and_mad_z_minus_three() -> None:
    amounts = tuple(9_500 if index % 2 == 0 else 10_500 for index in range(20))
    history = _spread_history(20, amounts=amounts)

    at_boundary = assess_anomaly(
        history,
        _observation(6_000, datetime(2026, 11, 2, 10, tzinfo=UTC)),
    )
    above_ratio = assess_anomaly(
        history,
        _observation(6_001, datetime(2026, 11, 2, 10, tzinfo=UTC)),
    )

    assert at_boundary.status is AnomalyStatus.SUSPECTED_ANOMALY
    assert at_boundary.ratio_to_median == Decimal("0.6")
    assert at_boundary.robust_mad_z is not None
    assert at_boundary.robust_mad_z <= Decimal("-3")
    assert at_boundary.detector_version == "suspected-anomaly-v1"
    assert above_ratio.status is AnomalyStatus.NOT_ANOMALOUS
    assert "error_fare" not in at_boundary.status.value


def test_zero_mad_still_requires_non_zero_range_and_ratio_rule() -> None:
    non_zero_range = _spread_history(
        20,
        amounts=(10_000,) * 19 + (12_000,),
    )
    zero_range = _spread_history(20, amounts=(10_000,) * 20)
    current = _observation(6_000, datetime(2026, 11, 2, 10, tzinfo=UTC))

    suspected = assess_anomaly(non_zero_range, current)
    rejected = assess_anomaly(zero_range, current)

    assert suspected.status is AnomalyStatus.SUSPECTED_ANOMALY
    assert suspected.mad_minor_units == Decimal("0")
    assert suspected.robust_mad_z is None
    assert rejected.status is AnomalyStatus.NOT_ANOMALOUS


def test_same_flight_fingerprint_ignores_market_and_amount_but_tracks_flight_identity() -> None:
    base = _currency_offer(amount=10_000, currency="RUB", market="RU")

    assert same_flight_fingerprint(base) == same_flight_fingerprint(
        replace(base, amount=Money(90, "EUR"), market="TR")
    )
    for changed in (
        replace(
            base,
            segments=(replace(base.segments[0], destination="ORY"),),
        ),
        replace(
            base,
            segments=(replace(base.segments[0], carrier_code="ZZ"),),
        ),
        replace(
            base,
            segments=(replace(base.segments[0], flight_number="ZZ999"),),
        ),
        replace(
            base,
            segments=(
                replace(
                    base.segments[0],
                    local_departure=datetime(2026, 9, 10, 13, tzinfo=UTC),
                ),
            ),
        ),
        replace(base, cabin="business"),
    ):
        assert same_flight_fingerprint(changed) != same_flight_fingerprint(base)


def test_missing_fx_provider_is_explicit_and_never_claims_savings() -> None:
    reference = _currency_offer(amount=10_000, currency="RUB", market="RU")
    candidate = _currency_offer(amount=90, currency="EUR", market="TR")

    comparison = compare_currency_offers(
        reference,
        candidate,
        fx_rate=None,
        reference_fee=_fee(),
        candidate_fee=_fee(),
        assessed_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    assert comparison.status is CurrencyComparisonStatus.FX_PROVIDER_UNAVAILABLE
    assert comparison.reason_code == "fx_provider_unavailable"
    assert comparison.reference_amount == reference.amount
    assert comparison.candidate_amount == candidate.amount
    assert comparison.savings_minor_units is None
    assert comparison.savings_percent is None


def test_fx_is_fresh_through_exactly_twenty_four_hours() -> None:
    assessed_at = datetime(2026, 7, 16, 12, tzinfo=UTC)
    reference = _currency_offer(amount=10_000, currency="RUB", market="RU")
    candidate = _currency_offer(amount=90, currency="EUR", market="TR")

    fresh = compare_currency_offers(
        reference,
        candidate,
        fx_rate=_fx(observed_at=assessed_at - timedelta(hours=24)),
        reference_fee=_fee(),
        candidate_fee=_fee(),
        assessed_at=assessed_at,
    )
    stale = compare_currency_offers(
        reference,
        candidate,
        fx_rate=_fx(observed_at=assessed_at - timedelta(hours=24, seconds=1)),
        reference_fee=_fee(),
        candidate_fee=_fee(),
        assessed_at=assessed_at,
    )

    assert fresh.status is CurrencyComparisonStatus.COMPARABLE
    assert fresh.reference_effective_minor_units == 10_000
    assert fresh.candidate_effective_minor_units == 9_000
    assert fresh.savings_minor_units == 1_000
    assert fresh.savings_percent == Decimal("10")
    assert stale.status is CurrencyComparisonStatus.NOT_COMPARABLE
    assert stale.reason_code == "fx_stale"
    assert stale.savings_minor_units is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda offer: replace(offer, seller_or_gate="Other seller"),
        lambda offer: replace(offer, fare_code="YFLEX"),
        lambda offer: replace(offer, fare_family="FLEX"),
        lambda offer: replace(
            offer,
            baggage_key=BaggageKey(
                state=CheckedBaggageState.INCLUDED,
                pieces=1,
                weight_kg=Decimal("23"),
            ),
        ),
        lambda offer: replace(offer, ticket_structure=TicketStructure.SPLIT_TICKET),
        lambda offer: replace(offer, refund_rule="refundable"),
        lambda offer: replace(offer, change_rule="changes_allowed"),
    ),
)
def test_material_currency_comparison_mismatches_are_not_comparable(
    mutate: Callable[[CurrencyOfferFacts], CurrencyOfferFacts],
) -> None:
    reference = _currency_offer(amount=10_000, currency="RUB", market="RU")
    candidate = mutate(_currency_offer(amount=90, currency="EUR", market="TR"))

    comparison = compare_currency_offers(
        reference,
        candidate,
        fx_rate=_fx(),
        reference_fee=_fee(),
        candidate_fee=_fee(),
        assessed_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    assert comparison.status is CurrencyComparisonStatus.NOT_COMPARABLE
    assert comparison.reason_code == "material_facts_mismatch"
    assert comparison.savings_minor_units is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda offer: replace(offer, seller_or_gate=None),
        lambda offer: replace(offer, fare_code=None),
        lambda offer: replace(offer, fare_family=None),
        lambda offer: replace(offer, baggage_key=None),
        lambda offer: replace(offer, ticket_structure=None),
        lambda offer: replace(offer, refund_rule=None),
        lambda offer: replace(offer, change_rule=None),
    ),
)
def test_unknown_material_currency_facts_are_not_comparable(
    mutate: Callable[[CurrencyOfferFacts], CurrencyOfferFacts],
) -> None:
    candidate = mutate(_currency_offer(amount=90, currency="EUR", market="TR"))

    comparison = compare_currency_offers(
        _currency_offer(amount=10_000, currency="RUB", market="RU"),
        candidate,
        fx_rate=_fx(),
        reference_fee=_fee(),
        candidate_fee=_fee(),
        assessed_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    assert comparison.status is CurrencyComparisonStatus.NOT_COMPARABLE
    assert comparison.reason_code == "material_facts_unknown"
    assert comparison.savings_minor_units is None


def test_missing_fee_provenance_is_not_comparable() -> None:
    comparison = compare_currency_offers(
        _currency_offer(amount=10_000, currency="RUB", market="RU"),
        _currency_offer(amount=90, currency="EUR", market="TR"),
        fx_rate=_fx(),
        reference_fee=_fee(provenance=None),
        candidate_fee=_fee(),
        assessed_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    assert comparison.status is CurrencyComparisonStatus.NOT_COMPARABLE
    assert comparison.reason_code == "fee_assumption_missing"
    assert comparison.savings_minor_units is None


def _history_key() -> HistorySeriesKey:
    return HistorySeriesKey(
        ordered_leg_keys=(
            HistoryLegKey(
                origin="LED",
                destination="CDG",
                date_start=date(2026, 9, 10),
                date_end=date(2026, 9, 10),
            ),
            HistoryLegKey(
                origin="CDG",
                destination="LED",
                date_start=date(2026, 9, 17),
                date_end=date(2026, 9, 17),
            ),
        ),
        trip_shape=TripShape.ROUND_TRIP,
        stay=StayWindow(minimum_nights=7, maximum_nights=7),
        cabin="economy",
        passenger_mix=PassengerMix(adults=1),
        ticket_structure=TicketStructure.SINGLE_TICKET,
        risk_class=RiskClass.LOW,
        baggage_key=BaggageKey(
            state=CheckedBaggageState.NOT_INCLUDED,
            pieces=0,
            weight_kg=Decimal("0"),
        ),
        currency_basis=CurrencyBasis(
            provider_currency="RUB",
            comparison_currency="RUB",
            fx_source=None,
        ),
        aggregation_mode=HistoryAggregationMode.MARKET_MINIMUM,
        product_key=None,
    )


def _observation(
    amount_minor: int,
    observed_at: datetime,
    *,
    departure_date: date = date(2027, 3, 1),
    timezone: str = "UTC",
) -> HistoryObservation:
    return HistoryObservation(
        series_hash=history_series_hash(_history_key()),
        amount=Money(amount_minor, "RUB"),
        observed_at=observed_at,
        departure_date=departure_date,
        timezone=timezone,
    )


def _spread_history(
    count: int,
    *,
    amounts: tuple[int, ...] | None = None,
    offsets: tuple[int, ...] | None = None,
) -> tuple[HistoryObservation, ...]:
    if amounts is None:
        amounts = tuple(10_000 + index * 100 for index in range(count))
    if offsets is None:
        offsets = tuple((index * 21) // max(count - 1, 1) for index in range(count))
    assert len(amounts) == count
    assert len(offsets) == count
    start = datetime(2026, 10, 1, 10, tzinfo=UTC)
    return tuple(
        _observation(
            amount,
            start + timedelta(days=offset, minutes=index),
        )
        for index, (amount, offset) in enumerate(zip(amounts, offsets, strict=True))
    )


def _cyclic_offsets(count: int, *, modulus: int, final: int) -> tuple[int, ...]:
    values = [index % modulus for index in range(count)]
    values.append(final)
    return tuple(values)


def _weekday_history(*, best_amount: int) -> tuple[HistoryObservation, ...]:
    observations: list[HistoryObservation] = []
    first_monday = datetime(2026, 10, 5, 10, tzinfo=UTC)
    for week in range(4):
        monday = first_monday + timedelta(days=week * 7)
        tuesday = monday + timedelta(days=1)
        observations.extend(
            _observation(
                10_000,
                monday + timedelta(hours=hour_offset),
                departure_date=date(2027, 3, 1),
            )
            for hour_offset in (0, 1)
        )
        observations.extend(
            _observation(
                best_amount,
                tuesday + timedelta(hours=hour_offset),
                departure_date=date(2027, 3, 1),
            )
            for hour_offset in (0, 1)
        )
        for day_offset in range(2, 7):
            observations.append(
                _observation(
                    9_900,
                    monday + timedelta(days=day_offset, hours=8),
                    departure_date=date(2027, 3, 1),
                )
            )
        observations.append(
            _observation(
                9_900,
                monday + timedelta(days=2, hours=9),
                departure_date=date(2027, 3, 1),
            )
        )
    assert len(observations) == 40
    return tuple(observations)


def _hour_bucket_history(*, best_amount: int) -> tuple[HistoryObservation, ...]:
    observations: list[HistoryObservation] = []
    first_monday = datetime(2026, 10, 5, 10, tzinfo=UTC)
    for week in range(4):
        monday = first_monday + timedelta(days=week * 7)
        observations.extend(
            _observation(
                10_000,
                monday + timedelta(hours=hour_offset),
                departure_date=date(2027, 3, 1),
            )
            for hour_offset in (0, 1)
        )
        observations.extend(
            _observation(
                best_amount,
                monday + timedelta(hours=4 + hour_offset),
                departure_date=date(2027, 3, 1),
            )
            for hour_offset in (0, 1)
        )
        for day_offset in range(1, 7):
            observations.append(
                _observation(
                    9_900,
                    monday + timedelta(days=day_offset, hours=8),
                    departure_date=date(2027, 3, 1),
                )
            )
    assert len(observations) == 40
    return tuple(observations)


def _currency_offer(
    *,
    amount: int,
    currency: str,
    market: str,
) -> CurrencyOfferFacts:
    return CurrencyOfferFacts(
        market=market,
        amount=Money(amount, currency),
        segments=(
            FlightFingerprintSegment(
                origin="LED",
                destination="CDG",
                carrier_code="XX",
                flight_number="XX123",
                local_departure=datetime(2026, 9, 10, 12, tzinfo=UTC),
            ),
        ),
        cabin="economy",
        seller_or_gate="Fixture seller",
        fare_code="YLOW",
        fare_family="LIGHT",
        baggage_key=BaggageKey(
            state=CheckedBaggageState.NOT_INCLUDED,
            pieces=0,
            weight_kg=Decimal("0"),
        ),
        ticket_structure=TicketStructure.SINGLE_TICKET,
        refund_rule="non_refundable",
        change_rule="changes_not_allowed",
    )


def _fx(
    *,
    observed_at: datetime = datetime(2026, 7, 16, 12, tzinfo=UTC),
) -> FxRateObservation:
    return FxRateObservation(
        source="fixture-fx",
        base_currency="EUR",
        quote_currency="RUB",
        rate=Decimal("100"),
        observed_at=observed_at,
    )


def _fee(
    *,
    provenance: str | None = "user-setting",
) -> CardFeeAssumption:
    return CardFeeAssumption(
        percent=Decimal("0"),
        provenance=provenance,
        effective_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
