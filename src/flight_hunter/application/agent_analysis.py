from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from flight_hunter.domain.agent_evidence import (
    CardFeeAssumption,
    CurrencyOfferFacts,
    FxRateObservation,
    HistoryObservation,
    HistorySeriesKey,
)
from flight_hunter.domain.money import Money

BUY_TIMING_CALCULATION_VERSION = "buy-timing-v1"
ANOMALY_DETECTOR_VERSION = "suspected-anomaly-v1"
CURRENCY_COMPARISON_VERSION = "currency-comparison-v1"
MAX_FX_AGE = timedelta(hours=24)


class BuyTimingStatus(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    HISTORICALLY_LOW = "historically_low"
    NO_BUY_SIGNAL = "no_buy_signal"


class AnomalyStatus(StrEnum):
    INSUFFICIENT_DATA = "insufficient_data"
    SUSPECTED_ANOMALY = "suspected_anomaly"
    NOT_ANOMALOUS = "not_anomalous"


class CurrencyComparisonStatus(StrEnum):
    COMPARABLE = "comparable"
    NOT_COMPARABLE = "not_comparable"
    FX_PROVIDER_UNAVAILABLE = "fx_provider_unavailable"


@dataclass(frozen=True, slots=True)
class BuyTimingThresholds:
    minimum_observations: int = 40
    minimum_history_span_days: int = 21
    minimum_distinct_dates: int = 14
    minimum_bucket_observations: int = 8
    minimum_bucket_weeks: int = 4
    minimum_recommendation_difference_percent: Decimal = Decimal("5")
    buy_now_percentile: Decimal = Decimal("20")


@dataclass(frozen=True, slots=True)
class AnomalyThresholds:
    minimum_observations: int = 20
    minimum_distinct_dates: int = 7
    maximum_median_ratio: Decimal = Decimal("0.60")
    maximum_robust_mad_z: Decimal = Decimal("-3")


BUY_TIMING_THRESHOLDS = BuyTimingThresholds()
ANOMALY_THRESHOLDS = AnomalyThresholds()


@dataclass(frozen=True, slots=True)
class BuyTimingAssessment:
    status: BuyTimingStatus
    watch_action_available: bool
    sample_count: int
    distinct_dates: int
    distinct_weeks: int
    history_span_days: int
    current_percentile: Decimal | None
    twentieth_percentile_minor_units: int | None
    median_minor_units: Decimal | None
    timezone: str
    days_to_departure_band: str
    recommended_weekday: int | None
    weekday_savings_percent: Decimal | None
    recommended_four_hour_bucket: int | None
    four_hour_savings_percent: Decimal | None
    calculation_version: str
    thresholds: BuyTimingThresholds


@dataclass(frozen=True, slots=True)
class AnomalyAssessment:
    status: AnomalyStatus
    sample_count: int
    distinct_dates: int
    median_minor_units: Decimal | None
    ratio_to_median: Decimal | None
    mad_minor_units: Decimal | None
    robust_mad_z: Decimal | None
    observed_range_minor_units: int | None
    detector_version: str
    thresholds: AnomalyThresholds


@dataclass(frozen=True, slots=True)
class CurrencyComparison:
    status: CurrencyComparisonStatus
    reference_amount: Money
    candidate_amount: Money
    comparison_currency: str
    reference_effective_minor_units: int | None
    candidate_effective_minor_units: int | None
    savings_minor_units: int | None
    savings_percent: Decimal | None
    flight_fingerprint: str
    reason_code: str
    fx_source: str | None
    fx_observed_at: datetime | None
    fee_provenance: tuple[str, ...]
    calculation_version: str


def history_series_hash(key: HistorySeriesKey) -> str:
    if not isinstance(key, HistorySeriesKey):
        raise TypeError("key must be HistorySeriesKey")
    canonical = json.dumps(
        _history_series_payload(key),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def same_flight_fingerprint(offer: CurrencyOfferFacts) -> str:
    if not isinstance(offer, CurrencyOfferFacts):
        raise TypeError("offer must be CurrencyOfferFacts")
    canonical = json.dumps(
        {
            "cabin": offer.cabin,
            "segments": [
                {
                    "carrier_code": segment.carrier_code,
                    "destination": segment.destination,
                    "flight_number": segment.flight_number,
                    "local_departure": segment.local_departure.isoformat(),
                    "origin": segment.origin,
                }
                for segment in offer.segments
            ],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare_currency_offers(
    reference: CurrencyOfferFacts,
    candidate: CurrencyOfferFacts,
    *,
    fx_rate: FxRateObservation | None,
    reference_fee: CardFeeAssumption | None,
    candidate_fee: CardFeeAssumption | None,
    assessed_at: datetime,
) -> CurrencyComparison:
    if not isinstance(reference, CurrencyOfferFacts) or not isinstance(
        candidate,
        CurrencyOfferFacts,
    ):
        raise TypeError("reference and candidate must be CurrencyOfferFacts")
    _require_aware_datetime(assessed_at, "assessed_at")
    reference_fingerprint = same_flight_fingerprint(reference)
    if reference_fingerprint != same_flight_fingerprint(candidate):
        return _currency_not_comparable(
            reference,
            candidate,
            reference_fingerprint,
            "flight_mismatch",
        )
    reference_material = _material_currency_facts(reference)
    candidate_material = _material_currency_facts(candidate)
    if reference_material is None or candidate_material is None:
        return _currency_not_comparable(
            reference,
            candidate,
            reference_fingerprint,
            "material_facts_unknown",
        )
    if reference_material != candidate_material:
        return _currency_not_comparable(
            reference,
            candidate,
            reference_fingerprint,
            "material_facts_mismatch",
        )
    if reference.amount.currency != candidate.amount.currency and fx_rate is None:
        return CurrencyComparison(
            status=CurrencyComparisonStatus.FX_PROVIDER_UNAVAILABLE,
            reference_amount=reference.amount,
            candidate_amount=candidate.amount,
            comparison_currency=reference.amount.currency,
            reference_effective_minor_units=None,
            candidate_effective_minor_units=None,
            savings_minor_units=None,
            savings_percent=None,
            flight_fingerprint=reference_fingerprint,
            reason_code="fx_provider_unavailable",
            fx_source=None,
            fx_observed_at=None,
            fee_provenance=(),
            calculation_version=CURRENCY_COMPARISON_VERSION,
        )
    if not _complete_fee(reference_fee, assessed_at) or not _complete_fee(
        candidate_fee,
        assessed_at,
    ):
        return _currency_not_comparable(
            reference,
            candidate,
            reference_fingerprint,
            "fee_assumption_missing",
            fx_rate=fx_rate,
        )
    candidate_in_reference = Decimal(candidate.amount.minor_units)
    if reference.amount.currency != candidate.amount.currency:
        if fx_rate is None:  # Narrowing after the explicit unavailable branch.
            raise RuntimeError("cross-currency comparison lost its FX observation")
        age = assessed_at - fx_rate.observed_at
        if age < timedelta(0) or age > MAX_FX_AGE:
            return _currency_not_comparable(
                reference,
                candidate,
                reference_fingerprint,
                "fx_stale",
                fx_rate=fx_rate,
            )
        converted = _convert_minor_units(
            candidate.amount,
            reference.amount.currency,
            fx_rate,
        )
        if converted is None:
            return _currency_not_comparable(
                reference,
                candidate,
                reference_fingerprint,
                "fx_pair_mismatch",
                fx_rate=fx_rate,
            )
        candidate_in_reference = converted

    if reference_fee is None or candidate_fee is None:
        raise RuntimeError("fee narrowing invariant failed")
    reference_effective = _rounded_minor_units(
        _apply_percent(Decimal(reference.amount.minor_units), reference_fee.percent)
    )
    candidate_effective = _rounded_minor_units(
        _apply_percent(candidate_in_reference, candidate_fee.percent)
    )
    difference = reference_effective - candidate_effective
    savings_minor = difference if difference > 0 else None
    savings_percent = (
        Decimal(difference) * Decimal(100) / Decimal(reference_effective)
        if difference > 0 and reference_effective > 0
        else None
    )
    return CurrencyComparison(
        status=CurrencyComparisonStatus.COMPARABLE,
        reference_amount=reference.amount,
        candidate_amount=candidate.amount,
        comparison_currency=reference.amount.currency,
        reference_effective_minor_units=reference_effective,
        candidate_effective_minor_units=candidate_effective,
        savings_minor_units=savings_minor,
        savings_percent=savings_percent,
        flight_fingerprint=reference_fingerprint,
        reason_code="comparable",
        fx_source=fx_rate.source if fx_rate is not None else None,
        fx_observed_at=fx_rate.observed_at if fx_rate is not None else None,
        fee_provenance=(
            reference_fee.provenance or "",
            candidate_fee.provenance or "",
        ),
        calculation_version=CURRENCY_COMPARISON_VERSION,
    )


def assess_buy_timing(
    history: Sequence[HistoryObservation],
    current: HistoryObservation,
) -> BuyTimingAssessment:
    observations = _validated_history(history, current)
    local_dates = tuple(observation.local_observed_at.date() for observation in observations)
    sample_count = len(observations)
    distinct_dates = len(set(local_dates))
    distinct_weeks = len({_iso_week(value) for value in local_dates})
    history_span_days = (max(local_dates) - min(local_dates)).days if local_dates else 0
    band = _days_to_departure_band(current.days_to_departure)
    if (
        sample_count < BUY_TIMING_THRESHOLDS.minimum_observations
        or history_span_days < BUY_TIMING_THRESHOLDS.minimum_history_span_days
        or distinct_dates < BUY_TIMING_THRESHOLDS.minimum_distinct_dates
    ):
        return BuyTimingAssessment(
            status=BuyTimingStatus.INSUFFICIENT_DATA,
            watch_action_available=True,
            sample_count=sample_count,
            distinct_dates=distinct_dates,
            distinct_weeks=distinct_weeks,
            history_span_days=history_span_days,
            current_percentile=None,
            twentieth_percentile_minor_units=None,
            median_minor_units=None,
            timezone=current.timezone,
            days_to_departure_band=band,
            recommended_weekday=None,
            weekday_savings_percent=None,
            recommended_four_hour_bucket=None,
            four_hour_savings_percent=None,
            calculation_version=BUY_TIMING_CALCULATION_VERSION,
            thresholds=BUY_TIMING_THRESHOLDS,
        )

    amounts = tuple(sorted(observation.amount.minor_units for observation in observations))
    twentieth = _nearest_rank_percentile(amounts, 20)
    current_percentile = (
        Decimal(sum(value <= current.amount.minor_units for value in amounts))
        * Decimal(100)
        / Decimal(sample_count)
    )
    median = _median(amounts)
    weekday, weekday_savings = _bucket_recommendation(
        observations,
        current,
        key=lambda value: value.local_observed_at.weekday(),
    )
    four_hour, four_hour_savings = _bucket_recommendation(
        observations,
        current,
        key=lambda value: (value.local_observed_at.hour // 4) * 4,
    )
    return BuyTimingAssessment(
        status=(
            BuyTimingStatus.HISTORICALLY_LOW
            if current.amount.minor_units <= twentieth
            else BuyTimingStatus.NO_BUY_SIGNAL
        ),
        watch_action_available=False,
        sample_count=sample_count,
        distinct_dates=distinct_dates,
        distinct_weeks=distinct_weeks,
        history_span_days=history_span_days,
        current_percentile=current_percentile,
        twentieth_percentile_minor_units=twentieth,
        median_minor_units=median,
        timezone=current.timezone,
        days_to_departure_band=band,
        recommended_weekday=weekday,
        weekday_savings_percent=weekday_savings,
        recommended_four_hour_bucket=four_hour,
        four_hour_savings_percent=four_hour_savings,
        calculation_version=BUY_TIMING_CALCULATION_VERSION,
        thresholds=BUY_TIMING_THRESHOLDS,
    )


def assess_anomaly(
    history: Sequence[HistoryObservation],
    current: HistoryObservation,
) -> AnomalyAssessment:
    observations = _validated_history(history, current)
    local_dates = tuple(observation.local_observed_at.date() for observation in observations)
    sample_count = len(observations)
    distinct_dates = len(set(local_dates))
    if (
        sample_count < ANOMALY_THRESHOLDS.minimum_observations
        or distinct_dates < ANOMALY_THRESHOLDS.minimum_distinct_dates
    ):
        return AnomalyAssessment(
            status=AnomalyStatus.INSUFFICIENT_DATA,
            sample_count=sample_count,
            distinct_dates=distinct_dates,
            median_minor_units=None,
            ratio_to_median=None,
            mad_minor_units=None,
            robust_mad_z=None,
            observed_range_minor_units=None,
            detector_version=ANOMALY_DETECTOR_VERSION,
            thresholds=ANOMALY_THRESHOLDS,
        )

    amounts = tuple(sorted(observation.amount.minor_units for observation in observations))
    median = _median(amounts)
    observed_range = max(amounts) - min(amounts)
    if median <= 0:
        return AnomalyAssessment(
            status=AnomalyStatus.NOT_ANOMALOUS,
            sample_count=sample_count,
            distinct_dates=distinct_dates,
            median_minor_units=median,
            ratio_to_median=None,
            mad_minor_units=None,
            robust_mad_z=None,
            observed_range_minor_units=observed_range,
            detector_version=ANOMALY_DETECTOR_VERSION,
            thresholds=ANOMALY_THRESHOLDS,
        )
    ratio = Decimal(current.amount.minor_units) / median
    deviations = tuple(abs(Decimal(value) - median) for value in amounts)
    mad = _median_decimal(deviations)
    robust_z = (
        None
        if mad == 0
        else Decimal("0.6745") * (Decimal(current.amount.minor_units) - median) / mad
    )
    ratio_matches = ratio <= ANOMALY_THRESHOLDS.maximum_median_ratio
    distribution_matches = (
        observed_range > 0
        if mad == 0
        else robust_z is not None and robust_z <= ANOMALY_THRESHOLDS.maximum_robust_mad_z
    )
    return AnomalyAssessment(
        status=(
            AnomalyStatus.SUSPECTED_ANOMALY
            if ratio_matches and distribution_matches
            else AnomalyStatus.NOT_ANOMALOUS
        ),
        sample_count=sample_count,
        distinct_dates=distinct_dates,
        median_minor_units=median,
        ratio_to_median=ratio,
        mad_minor_units=mad,
        robust_mad_z=robust_z,
        observed_range_minor_units=observed_range,
        detector_version=ANOMALY_DETECTOR_VERSION,
        thresholds=ANOMALY_THRESHOLDS,
    )


def _history_series_payload(key: HistorySeriesKey) -> dict[str, object]:
    baggage = key.baggage_key
    currency = key.currency_basis
    product = key.product_key
    return {
        "aggregation_mode": key.aggregation_mode.value,
        "baggage": {
            "pieces": baggage.pieces,
            "state": baggage.state.value,
            "weight_kg": _decimal_text(baggage.weight_kg),
        },
        "cabin": key.cabin,
        "currency_basis": {
            "comparison_currency": currency.comparison_currency,
            "fx_source": currency.fx_source,
            "provider_currency": currency.provider_currency,
        },
        "ordered_legs": [
            {
                "date_end": leg.date_end.isoformat(),
                "date_start": leg.date_start.isoformat(),
                "destination": leg.destination,
                "origin": leg.origin,
            }
            for leg in key.ordered_leg_keys
        ],
        "passenger_mix": {
            "adults": key.passenger_mix.adults,
            "children": key.passenger_mix.children,
            "infants": key.passenger_mix.infants,
        },
        "product": (
            None
            if product is None
            else {
                "fare_code": product.fare_code,
                "fare_family": product.fare_family,
                "provider_id": product.provider_id,
                "seller_or_gate": product.seller_or_gate,
            }
        ),
        "risk_class": key.risk_class.value,
        "stay": (
            None
            if key.stay is None
            else {
                "maximum_nights": key.stay.maximum_nights,
                "minimum_nights": key.stay.minimum_nights,
            }
        ),
        "ticket_structure": key.ticket_structure.value,
        "trip_shape": key.trip_shape.value,
    }


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _validated_history(
    history: Sequence[HistoryObservation],
    current: HistoryObservation,
) -> tuple[HistoryObservation, ...]:
    if not isinstance(current, HistoryObservation):
        raise TypeError("current must be HistoryObservation")
    if isinstance(history, (str, bytes, bytearray)):
        raise TypeError("history must be a sequence of HistoryObservation values")
    observations = tuple(history)
    if not all(isinstance(value, HistoryObservation) for value in observations):
        raise TypeError("history must contain HistoryObservation values")
    if any(
        observation.series_hash != current.series_hash
        or observation.amount.currency != current.amount.currency
        or observation.timezone != current.timezone
        for observation in observations
    ):
        raise ValueError("history observations must share one series, currency and timezone")
    return observations


def _nearest_rank_percentile(values: Sequence[int], percent: int) -> int:
    if not values:
        raise ValueError("percentile requires values")
    rank = max(1, (len(values) * percent + 99) // 100)
    return values[rank - 1]


def _median(values: Sequence[int]) -> Decimal:
    return _median_decimal(tuple(Decimal(value) for value in values))


def _median_decimal(values: Sequence[Decimal]) -> Decimal:
    if not values:
        raise ValueError("median requires values")
    ordered = tuple(sorted(values))
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _bucket_recommendation(
    history: Sequence[HistoryObservation],
    current: HistoryObservation,
    *,
    key: Callable[[HistoryObservation], int],
) -> tuple[int | None, Decimal | None]:
    current_band = _days_to_departure_band(current.days_to_departure)
    groups: dict[int, list[HistoryObservation]] = defaultdict(list)
    for observation in history:
        if _days_to_departure_band(observation.days_to_departure) == current_band:
            groups[key(observation)].append(observation)
    current_key = key(current)
    current_group = groups.get(current_key, ())
    if not _eligible_bucket(current_group):
        return None, None
    eligible = {bucket: values for bucket, values in groups.items() if _eligible_bucket(values)}
    if len(eligible) < 2:
        return None, None
    medians = {
        bucket: _median(tuple(value.amount.minor_units for value in values))
        for bucket, values in eligible.items()
    }
    current_median = medians[current_key]
    best_key = min(medians, key=lambda bucket: (medians[bucket], bucket))
    if best_key == current_key or current_median <= 0:
        return None, None
    difference = (current_median - medians[best_key]) * Decimal(100) / current_median
    if difference < BUY_TIMING_THRESHOLDS.minimum_recommendation_difference_percent:
        return None, None
    return best_key, difference


def _eligible_bucket(values: Sequence[HistoryObservation]) -> bool:
    weeks = {_iso_week(observation.local_observed_at.date()) for observation in values}
    return (
        len(values) >= BUY_TIMING_THRESHOLDS.minimum_bucket_observations
        and len(weeks) >= BUY_TIMING_THRESHOLDS.minimum_bucket_weeks
    )


def _iso_week(value: date) -> tuple[int, int]:
    calendar = value.isocalendar()
    return calendar.year, calendar.week


def _days_to_departure_band(days: int) -> str:
    if days <= 6:
        return "0-6"
    if days <= 13:
        return "7-13"
    if days <= 29:
        return "14-29"
    if days <= 59:
        return "30-59"
    return "60+"


def _material_currency_facts(offer: CurrencyOfferFacts) -> tuple[object, ...] | None:
    facts = (
        offer.seller_or_gate,
        offer.fare_code,
        offer.fare_family,
        offer.baggage_key,
        offer.ticket_structure,
        offer.refund_rule,
        offer.change_rule,
    )
    return None if any(value is None for value in facts) else facts


def _complete_fee(
    value: CardFeeAssumption | None,
    assessed_at: datetime,
) -> bool:
    return (
        value is not None
        and value.provenance is not None
        and value.effective_at is not None
        and value.effective_at <= assessed_at
    )


def _convert_minor_units(
    amount: Money,
    target_currency: str,
    fx_rate: FxRateObservation,
) -> Decimal | None:
    value = Decimal(amount.minor_units)
    if fx_rate.base_currency == amount.currency and fx_rate.quote_currency == target_currency:
        return value * fx_rate.rate
    if fx_rate.quote_currency == amount.currency and fx_rate.base_currency == target_currency:
        return value / fx_rate.rate
    return None


def _apply_percent(value: Decimal, percent: Decimal) -> Decimal:
    return value * (Decimal(100) + percent) / Decimal(100)


def _rounded_minor_units(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _currency_not_comparable(
    reference: CurrencyOfferFacts,
    candidate: CurrencyOfferFacts,
    fingerprint: str,
    reason_code: str,
    *,
    fx_rate: FxRateObservation | None = None,
) -> CurrencyComparison:
    return CurrencyComparison(
        status=CurrencyComparisonStatus.NOT_COMPARABLE,
        reference_amount=reference.amount,
        candidate_amount=candidate.amount,
        comparison_currency=reference.amount.currency,
        reference_effective_minor_units=None,
        candidate_effective_minor_units=None,
        savings_minor_units=None,
        savings_percent=None,
        flight_fingerprint=fingerprint,
        reason_code=reason_code,
        fx_source=fx_rate.source if fx_rate is not None else None,
        fx_observed_at=fx_rate.observed_at if fx_rate is not None else None,
        fee_provenance=(),
        calculation_version=CURRENCY_COMPARISON_VERSION,
    )


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
