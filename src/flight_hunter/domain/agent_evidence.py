from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flight_hunter.domain.agent_search import TicketShape, TripShape
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import (
    FlightSegmentSummary,
    PassengerMix,
    PriceBasis,
)

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class DiscoverySource(StrEnum):
    CALENDAR = "calendar"
    HOT_OFFER = "hot_offer"
    REFERENCE = "reference"


class ConfirmationState(StrEnum):
    INDICATIVE = "indicative"
    CONFIRMED = "confirmed"


class ProtectionStatus(StrEnum):
    EXPLICITLY_PROTECTED = "explicitly_protected"
    SELF_TRANSFER = "self_transfer"
    UNKNOWN = "unknown"


class PriceComparisonStatus(StrEnum):
    FULLY_PRICED = "fully_priced"
    MANDATORY_COST_UNKNOWN = "mandatory_cost_unknown"
    NON_COMPARABLE = "non_comparable"


class UnknownCostKind(StrEnum):
    GROUND_TRANSFER = "ground_transfer"
    CURRENCY_CONVERSION = "currency_conversion"


class CheckedBaggageState(StrEnum):
    INCLUDED = "included"
    NOT_INCLUDED = "not_included"
    UNKNOWN = "unknown"


class HistoryAggregationMode(StrEnum):
    MARKET_MINIMUM = "market_minimum"
    SAME_PRODUCT = "same_product"


class TicketStructure(StrEnum):
    SINGLE_TICKET = "single_ticket"
    SPLIT_TICKET = "split_ticket"
    SELF_TRANSFER = "self_transfer"
    HIDDEN_CITY = "hidden_city"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class HistoryLegKey:
    origin: str
    destination: str
    date_start: date
    date_end: date

    def __post_init__(self) -> None:
        origin, destination = _normalized_route(self.origin, self.destination)
        if type(self.date_start) is not date or type(self.date_end) is not date:
            raise TypeError("history leg dates must be dates")
        if self.date_end < self.date_start:
            raise ValueError("history leg date_end cannot precede date_start")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)


@dataclass(frozen=True, slots=True)
class StayWindow:
    minimum_nights: int
    maximum_nights: int

    def __post_init__(self) -> None:
        if type(self.minimum_nights) is not int or self.minimum_nights < 0:
            raise ValueError("minimum_nights must be a non-negative integer")
        if type(self.maximum_nights) is not int or self.maximum_nights < self.minimum_nights:
            raise ValueError("maximum_nights must be at least minimum_nights")
        if self.maximum_nights - self.minimum_nights not in {0, 2}:
            raise ValueError("stay window must be exact or a symmetric approved +/-1 night band")


@dataclass(frozen=True, slots=True)
class BaggageKey:
    state: CheckedBaggageState
    pieces: int | None
    weight_kg: Decimal | None

    def __post_init__(self) -> None:
        state = CheckedBaggageState(self.state)
        if self.pieces is not None and (type(self.pieces) is not int or self.pieces < 0):
            raise ValueError("baggage pieces must be a non-negative integer or None")
        weight = self.weight_kg
        if weight is not None:
            if not isinstance(weight, Decimal):
                raise TypeError("baggage weight_kg must be Decimal or None")
            if not weight.is_finite() or weight < 0:
                raise ValueError("baggage weight_kg must be finite and non-negative")
        if state is CheckedBaggageState.UNKNOWN and (self.pieces is not None or weight is not None):
            raise ValueError("unknown baggage cannot contain count or weight facts")
        object.__setattr__(self, "state", state)


@dataclass(frozen=True, slots=True)
class CurrencyBasis:
    provider_currency: str
    comparison_currency: str
    fx_source: str | None

    def __post_init__(self) -> None:
        provider = _normalized_currency(self.provider_currency, "provider_currency")
        comparison = _normalized_currency(self.comparison_currency, "comparison_currency")
        source = self.fx_source.strip() if isinstance(self.fx_source, str) else self.fx_source
        if provider == comparison:
            if source is not None:
                raise ValueError("same-currency basis cannot contain fx_source")
        elif not source:
            raise ValueError("cross-currency basis requires fx_source")
        object.__setattr__(self, "provider_currency", provider)
        object.__setattr__(self, "comparison_currency", comparison)
        object.__setattr__(self, "fx_source", source)


@dataclass(frozen=True, slots=True)
class ProductKey:
    provider_id: str
    seller_or_gate: str
    fare_code: str
    fare_family: str

    def __post_init__(self) -> None:
        for field_name in ("provider_id", "seller_or_gate", "fare_code", "fare_family"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value.strip())


@dataclass(frozen=True, slots=True)
class HistorySeriesKey:
    ordered_leg_keys: tuple[HistoryLegKey, ...]
    trip_shape: TripShape
    stay: StayWindow | None
    cabin: str
    passenger_mix: PassengerMix
    ticket_structure: TicketStructure
    risk_class: RiskClass
    baggage_key: BaggageKey
    currency_basis: CurrencyBasis
    aggregation_mode: HistoryAggregationMode
    product_key: ProductKey | None

    def __post_init__(self) -> None:
        legs = tuple(self.ordered_leg_keys)
        if not legs or not all(isinstance(leg, HistoryLegKey) for leg in legs):
            raise ValueError("ordered_leg_keys must contain HistoryLegKey values")
        trip_shape = TripShape(self.trip_shape)
        if trip_shape is TripShape.ONE_WAY and self.stay is not None:
            raise ValueError("one-way history cannot contain a stay window")
        if trip_shape is not TripShape.ONE_WAY and not isinstance(self.stay, StayWindow):
            raise ValueError("non-one-way history requires a stay window")
        if not isinstance(self.cabin, str) or not self.cabin.strip():
            raise ValueError("cabin is required")
        if not isinstance(self.passenger_mix, PassengerMix):
            raise TypeError("passenger_mix must be PassengerMix")
        if not isinstance(self.baggage_key, BaggageKey):
            raise TypeError("baggage_key must be BaggageKey")
        if not isinstance(self.currency_basis, CurrencyBasis):
            raise TypeError("currency_basis must be CurrencyBasis")
        mode = HistoryAggregationMode(self.aggregation_mode)
        if mode is HistoryAggregationMode.MARKET_MINIMUM and self.product_key is not None:
            raise ValueError("market_minimum cannot contain product_key")
        if mode is HistoryAggregationMode.SAME_PRODUCT and not isinstance(
            self.product_key,
            ProductKey,
        ):
            raise ValueError("same_product requires product_key")
        object.__setattr__(self, "ordered_leg_keys", legs)
        object.__setattr__(self, "trip_shape", trip_shape)
        object.__setattr__(self, "cabin", self.cabin.strip().lower())
        object.__setattr__(self, "ticket_structure", TicketStructure(self.ticket_structure))
        object.__setattr__(self, "risk_class", RiskClass(self.risk_class))
        object.__setattr__(self, "aggregation_mode", mode)


@dataclass(frozen=True, slots=True)
class HistoryObservation:
    series_hash: str
    amount: Money
    observed_at: datetime
    departure_date: date
    timezone: str

    def __post_init__(self) -> None:
        if not isinstance(self.series_hash, str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            self.series_hash,
        ):
            raise ValueError("series_hash must use the sha256: project convention")
        _require_money(self.amount, "amount")
        _require_aware_datetime(self.observed_at)
        if type(self.departure_date) is not date:
            raise TypeError("departure_date must be a date")
        if not isinstance(self.timezone, str) or not self.timezone.strip():
            raise ValueError("timezone is required")
        timezone = self.timezone.strip()
        try:
            local_date = self.observed_at.astimezone(_timezone(timezone)).date()
        except ZoneInfoNotFoundError:
            raise ValueError("timezone must be a valid IANA timezone") from None
        if self.departure_date < local_date:
            raise ValueError("history observation cannot occur after departure")
        object.__setattr__(self, "timezone", timezone)

    @property
    def local_observed_at(self) -> datetime:
        return self.observed_at.astimezone(_timezone(self.timezone))

    @property
    def days_to_departure(self) -> int:
        return (self.departure_date - self.local_observed_at.date()).days


@dataclass(frozen=True, slots=True)
class FlightFingerprintSegment:
    origin: str
    destination: str
    carrier_code: str
    flight_number: str
    local_departure: datetime

    def __post_init__(self) -> None:
        origin, destination = _normalized_route(self.origin, self.destination)
        if not isinstance(self.carrier_code, str) or not self.carrier_code.strip():
            raise ValueError("carrier_code is required")
        if not isinstance(self.flight_number, str) or not self.flight_number.strip():
            raise ValueError("flight_number is required")
        _require_aware_datetime(self.local_departure)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "carrier_code", self.carrier_code.strip().upper())
        object.__setattr__(self, "flight_number", self.flight_number.strip().upper())


@dataclass(frozen=True, slots=True)
class CurrencyOfferFacts:
    market: str
    amount: Money
    segments: tuple[FlightFingerprintSegment, ...]
    cabin: str
    seller_or_gate: str | None
    fare_code: str | None
    fare_family: str | None
    baggage_key: BaggageKey | None
    ticket_structure: TicketStructure | None
    refund_rule: str | None
    change_rule: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.market, str) or not self.market.strip():
            raise ValueError("market is required")
        _require_money(self.amount, "amount")
        segments = tuple(self.segments)
        if not segments or not all(
            isinstance(segment, FlightFingerprintSegment) for segment in segments
        ):
            raise ValueError("segments must contain FlightFingerprintSegment values")
        if any(previous.destination != current.origin for previous, current in pairwise(segments)):
            raise ValueError("currency offer segments must be continuous and ordered")
        if not isinstance(self.cabin, str) or not self.cabin.strip():
            raise ValueError("cabin is required")
        for field_name in (
            "seller_or_gate",
            "fare_code",
            "fare_family",
            "refund_rule",
            "change_rule",
        ):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{field_name} must be non-empty or None")
                object.__setattr__(self, field_name, value.strip())
        if self.baggage_key is not None and not isinstance(self.baggage_key, BaggageKey):
            raise TypeError("baggage_key must be BaggageKey or None")
        ticket_structure = (
            None if self.ticket_structure is None else TicketStructure(self.ticket_structure)
        )
        object.__setattr__(self, "market", self.market.strip().upper())
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "cabin", self.cabin.strip().lower())
        object.__setattr__(self, "ticket_structure", ticket_structure)


@dataclass(frozen=True, slots=True)
class FxRateObservation:
    source: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("FX source is required")
        base = _normalized_currency(self.base_currency, "base_currency")
        quote = _normalized_currency(self.quote_currency, "quote_currency")
        if base == quote:
            raise ValueError("FX base and quote currencies must differ")
        if not isinstance(self.rate, Decimal):
            raise TypeError("FX rate must be Decimal")
        if not self.rate.is_finite() or self.rate <= 0:
            raise ValueError("FX rate must be finite and positive")
        _require_aware_datetime(self.observed_at)
        object.__setattr__(self, "source", self.source.strip())
        object.__setattr__(self, "base_currency", base)
        object.__setattr__(self, "quote_currency", quote)


@dataclass(frozen=True, slots=True)
class CardFeeAssumption:
    percent: Decimal
    provenance: str | None
    effective_at: datetime | None

    def __post_init__(self) -> None:
        if not isinstance(self.percent, Decimal):
            raise TypeError("card fee percent must be Decimal")
        if not self.percent.is_finite() or not Decimal(0) <= self.percent <= Decimal(100):
            raise ValueError("card fee percent must be between 0 and 100")
        provenance = self.provenance
        if provenance is not None:
            if not isinstance(provenance, str) or not provenance.strip():
                raise ValueError("card fee provenance must be non-empty or None")
            provenance = provenance.strip()
        if self.effective_at is not None:
            _require_aware_datetime(self.effective_at)
        object.__setattr__(self, "provenance", provenance)


@dataclass(frozen=True, slots=True)
class ComposedRouteLeg:
    ordinal: int
    origin: str
    destination: str
    departure_date: date
    component_evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        origin, destination = _normalized_route(self.origin, self.destination)
        if type(self.departure_date) is not date:
            raise TypeError("departure_date must be a date")
        component_ids = tuple(self.component_evidence_ids)
        if not component_ids or not all(isinstance(value, UUID) for value in component_ids):
            raise ValueError("component_evidence_ids must contain UUID values")
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("component_evidence_ids must be unique within a leg")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "component_evidence_ids", component_ids)


@dataclass(frozen=True, slots=True)
class TicketBoundary:
    ticket_index: int
    leg_ordinal: int
    component_evidence_id: UUID
    segment_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.ticket_index) is not int or self.ticket_index < 0:
            raise ValueError("ticket_index must be a non-negative integer")
        if type(self.leg_ordinal) is not int or self.leg_ordinal < 0:
            raise ValueError("leg_ordinal must be a non-negative integer")
        if not isinstance(self.component_evidence_id, UUID):
            raise TypeError("component_evidence_id must be UUID")
        refs = _normalized_segment_ids(self.segment_refs, allow_empty=False)
        object.__setattr__(self, "segment_refs", refs)


@dataclass(frozen=True, slots=True)
class ConnectionAssumption:
    leg_ordinal: int
    inbound_component_id: UUID
    outbound_component_id: UUID
    arrival_airport: str
    departure_airport: str
    layover: timedelta
    required_minimum: timedelta
    airport_change: bool
    provenance: str | None = None
    transfer_cost: Money | None = None

    def __post_init__(self) -> None:
        if type(self.leg_ordinal) is not int or self.leg_ordinal < 0:
            raise ValueError("leg_ordinal must be a non-negative integer")
        if not isinstance(self.inbound_component_id, UUID) or not isinstance(
            self.outbound_component_id, UUID
        ):
            raise TypeError("connection component IDs must be UUID values")
        arrival, departure = _normalized_route(
            self.arrival_airport,
            self.departure_airport,
        )
        if not isinstance(self.layover, timedelta) or self.layover < timedelta(0):
            raise ValueError("layover must be a non-negative timedelta")
        if not isinstance(self.required_minimum, timedelta) or self.required_minimum <= timedelta(
            0
        ):
            raise ValueError("required_minimum must be a positive timedelta")
        if type(self.airport_change) is not bool:
            raise TypeError("airport_change must be bool")
        if self.airport_change != (arrival != departure):
            raise ValueError("airport_change must match connection airports")
        if self.airport_change and not self.provenance:
            raise ValueError("airport changes require provenance")
        if self.transfer_cost is not None:
            _require_money(self.transfer_cost, "transfer_cost")
        object.__setattr__(self, "arrival_airport", arrival)
        object.__setattr__(self, "departure_airport", departure)


@dataclass(frozen=True, slots=True)
class UnknownCost:
    kind: UnknownCostKind
    leg_ordinal: int
    description: str

    def __post_init__(self) -> None:
        kind = UnknownCostKind(self.kind)
        if type(self.leg_ordinal) is not int or self.leg_ordinal < 0:
            raise ValueError("leg_ordinal must be a non-negative integer")
        if not self.description:
            raise ValueError("unknown cost description is required")
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True, slots=True)
class DiscoverySignal:
    id: UUID
    provider_id: str
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    observed_amount: Money
    observed_at: datetime
    source_kind: DiscoverySource
    passengers: int = 1
    segment_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_evidence_identity(self.id, self.provider_id)
        origin, destination = _normalized_route(self.origin, self.destination)
        _require_dates(self.departure_date, self.return_date)
        _require_money(self.observed_amount, "observed_amount")
        _require_passengers(self.passengers)
        _require_aware_datetime(self.observed_at)
        segment_ids = _normalized_segment_ids(self.segment_ids, allow_empty=True)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "source_kind", DiscoverySource(self.source_kind))
        object.__setattr__(self, "segment_ids", segment_ids)

    @property
    def confirmation_state(self) -> ConfirmationState:
        return ConfirmationState.INDICATIVE


@dataclass(frozen=True, slots=True)
class ConfirmedOfferEvidence:
    id: UUID
    provider_id: str
    provider_offer_id: str
    origin: str
    destination: str
    departure_date: date
    return_date: date | None
    total_amount: Money
    passengers: int
    observed_at: datetime
    segment_ids: tuple[str, ...]
    segments: tuple[FlightSegmentSummary, ...]
    protection_status: ProtectionStatus
    seller_name: str | None = None
    baggage_summary: str | None = None
    passenger_mix: PassengerMix | None = None
    price_basis: PriceBasis = PriceBasis.TOTAL_FOR_PASSENGERS
    ticket_shape: TicketShape | None = None
    checked_baggage: CheckedBaggageState | None = None
    provider_airport_changes: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_evidence_identity(self.id, self.provider_id)
        if not self.provider_offer_id:
            raise ValueError("provider_offer_id is required")
        origin, destination = _normalized_route(self.origin, self.destination)
        _require_dates(self.departure_date, self.return_date)
        _require_money(self.total_amount, "total_amount")
        _require_passengers(self.passengers)
        _require_aware_datetime(self.observed_at)
        segment_ids = _normalized_segment_ids(self.segment_ids, allow_empty=False)
        segments = _normalized_segments(self.segments)
        if len(segment_ids) != len(segments):
            raise ValueError("segment_ids must match segments")
        provider_airport_changes = _normalized_provider_airport_changes(
            self.provider_airport_changes,
            segments,
        )
        passenger_mix = self.passenger_mix or PassengerMix(adults=self.passengers)
        if not isinstance(passenger_mix, PassengerMix):
            raise TypeError("passenger_mix must be PassengerMix")
        if passenger_mix.total != self.passengers:
            raise ValueError("passengers must match passenger_mix total")
        price_basis = PriceBasis(self.price_basis)
        if price_basis is PriceBasis.PROVIDER_SINGLE_ADULT_TICKET and self.passengers != 1:
            raise ValueError("single-adult ticket prices require passengers=1")
        ticket_shape = (
            TicketShape.ROUND_TRIP
            if self.ticket_shape is None and self.return_date is not None
            else TicketShape.ONE_WAY
            if self.ticket_shape is None
            else TicketShape(self.ticket_shape)
        )
        if ticket_shape is TicketShape.ONE_WAY and self.return_date is not None:
            raise ValueError("one-way ticket evidence cannot contain a return date")
        if ticket_shape is TicketShape.ROUND_TRIP and self.return_date is None:
            raise ValueError("round-trip ticket evidence requires a return date")
        checked_baggage = (
            _inferred_checked_baggage(self.baggage_summary)
            if self.checked_baggage is None
            else CheckedBaggageState(self.checked_baggage)
        )
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "segment_ids", segment_ids)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "passenger_mix", passenger_mix)
        object.__setattr__(self, "price_basis", price_basis)
        object.__setattr__(self, "ticket_shape", ticket_shape)
        object.__setattr__(self, "checked_baggage", checked_baggage)
        object.__setattr__(self, "provider_airport_changes", provider_airport_changes)
        object.__setattr__(
            self,
            "protection_status",
            ProtectionStatus(self.protection_status),
        )

    @property
    def confirmation_state(self) -> ConfirmationState:
        return ConfirmationState.CONFIRMED


@dataclass(frozen=True, slots=True)
class ComposedRouteCandidate:
    id: UUID
    components: tuple[ConfirmedOfferEvidence, ...]
    total_amount: Money | None
    passengers: int
    observed_at: datetime
    segment_ids: tuple[str, ...]
    segments: tuple[FlightSegmentSummary, ...]
    protection_status: ProtectionStatus
    trip_shape: TripShape = TripShape.ONE_WAY
    passenger_mix: PassengerMix | None = None
    price_basis: PriceBasis = PriceBasis.TOTAL_FOR_PASSENGERS
    target_currency: str | None = None
    price_comparison_status: PriceComparisonStatus = PriceComparisonStatus.FULLY_PRICED
    ordered_legs: tuple[ComposedRouteLeg, ...] = ()
    ticket_boundaries: tuple[TicketBoundary, ...] = ()
    connection_assumptions: tuple[ConnectionAssumption, ...] = ()
    unknown_costs: tuple[UnknownCost, ...] = ()
    fingerprint: str = ""
    composition_version: str = "route-composer-v1"
    ranking_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("id must be UUID")
        components = tuple(self.components)
        if not components:
            raise ValueError("components cannot be empty")
        if not all(isinstance(component, ConfirmedOfferEvidence) for component in components):
            raise TypeError("components must contain ConfirmedOfferEvidence values")
        component_ids = tuple(component.id for component in components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("components must be unique")
        comparison_status = PriceComparisonStatus(self.price_comparison_status)
        if self.total_amount is None:
            if comparison_status is not PriceComparisonStatus.NON_COMPARABLE:
                raise ValueError("only non-comparable candidates may omit total_amount")
        else:
            _require_money(self.total_amount, "total_amount")
        _require_passengers(self.passengers)
        _require_aware_datetime(self.observed_at)
        segment_ids = _normalized_segment_ids(self.segment_ids, allow_empty=False)
        segments = _normalized_segments(self.segments)
        if len(segment_ids) != len(segments):
            raise ValueError("segment_ids must match segments")
        passenger_mix = self.passenger_mix or PassengerMix(adults=self.passengers)
        if not isinstance(passenger_mix, PassengerMix):
            raise TypeError("passenger_mix must be PassengerMix")
        if passenger_mix.total != self.passengers:
            raise ValueError("passengers must match passenger_mix total")
        price_basis = PriceBasis(self.price_basis)
        target_currency = self.target_currency
        if target_currency is None:
            if self.total_amount is None:
                raise ValueError("non-comparable candidates require target_currency")
            target_currency = self.total_amount.currency
        if not isinstance(target_currency, str):
            raise TypeError("target_currency must be a string")
        target_currency = target_currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(target_currency):
            raise ValueError("target_currency must be an ISO 4217 alpha-3 code")
        trip_shape = TripShape(self.trip_shape)
        ordered_legs = tuple(self.ordered_legs)
        if not all(isinstance(leg, ComposedRouteLeg) for leg in ordered_legs):
            raise TypeError("ordered_legs must contain ComposedRouteLeg values")
        ticket_boundaries = tuple(self.ticket_boundaries)
        if not all(isinstance(boundary, TicketBoundary) for boundary in ticket_boundaries):
            raise TypeError("ticket_boundaries must contain TicketBoundary values")
        connection_assumptions = tuple(self.connection_assumptions)
        if not all(
            isinstance(assumption, ConnectionAssumption) for assumption in connection_assumptions
        ):
            raise TypeError("connection_assumptions must contain ConnectionAssumption values")
        unknown_costs = tuple(self.unknown_costs)
        if not all(isinstance(cost, UnknownCost) for cost in unknown_costs):
            raise TypeError("unknown_costs must contain UnknownCost values")
        if self.fingerprint and not re.fullmatch(r"[0-9a-f]{64}", self.fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 digest")
        if not self.composition_version:
            raise ValueError("composition_version is required")
        ranking_reasons = tuple(self.ranking_reasons)
        if not all(isinstance(reason, str) and reason for reason in ranking_reasons):
            raise ValueError("ranking_reasons must contain non-empty strings")
        object.__setattr__(self, "components", components)
        object.__setattr__(self, "segment_ids", segment_ids)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "passenger_mix", passenger_mix)
        object.__setattr__(self, "price_basis", price_basis)
        object.__setattr__(self, "target_currency", target_currency)
        object.__setattr__(self, "trip_shape", trip_shape)
        object.__setattr__(self, "price_comparison_status", comparison_status)
        object.__setattr__(self, "ordered_legs", ordered_legs)
        object.__setattr__(self, "ticket_boundaries", ticket_boundaries)
        object.__setattr__(self, "connection_assumptions", connection_assumptions)
        object.__setattr__(self, "unknown_costs", unknown_costs)
        object.__setattr__(self, "ranking_reasons", ranking_reasons)
        object.__setattr__(
            self,
            "protection_status",
            ProtectionStatus(self.protection_status),
        )

    @property
    def confirmation_state(self) -> ConfirmationState:
        return ConfirmationState.CONFIRMED

    @property
    def component_evidence_ids(self) -> tuple[UUID, ...]:
        return tuple(component.id for component in self.components)

    @property
    def known_total(self) -> Money | None:
        return self.total_amount

    @property
    def component_amounts(self) -> tuple[Money, ...]:
        return tuple(component.total_amount for component in self.components)

    @property
    def canonical_facts(self) -> dict[str, Any]:
        amount = self.total_amount
        passenger_mix = self.passenger_mix
        if passenger_mix is None:  # Defensive narrowing for static callers.
            raise RuntimeError("passenger_mix invariant was not normalized")
        return {
            "composition_version": self.composition_version,
            "trip_shape": self.trip_shape.value,
            "components": [str(value) for value in self.component_evidence_ids],
            "component_amounts": [
                {
                    "minor_units": component.total_amount.minor_units,
                    "currency": component.total_amount.currency,
                }
                for component in self.components
            ],
            "ordered_legs": [
                {
                    "ordinal": leg.ordinal,
                    "origin": leg.origin,
                    "destination": leg.destination,
                    "departure_date": leg.departure_date.isoformat(),
                    "components": [str(value) for value in leg.component_evidence_ids],
                }
                for leg in self.ordered_legs
            ],
            "passenger_mix": {
                "adults": passenger_mix.adults,
                "children": passenger_mix.children,
                "infants": passenger_mix.infants,
            },
            "price_basis": self.price_basis.value,
            "target_currency": self.target_currency,
            "known_total": (
                None
                if amount is None
                else {"minor_units": amount.minor_units, "currency": amount.currency}
            ),
            "price_comparison_status": self.price_comparison_status.value,
            "tickets": [
                {
                    "ticket_index": boundary.ticket_index,
                    "leg_ordinal": boundary.leg_ordinal,
                    "component_evidence_id": str(boundary.component_evidence_id),
                    "segment_refs": list(boundary.segment_refs),
                }
                for boundary in self.ticket_boundaries
            ],
            "connections": [
                {
                    "leg_ordinal": assumption.leg_ordinal,
                    "inbound_component_id": str(assumption.inbound_component_id),
                    "outbound_component_id": str(assumption.outbound_component_id),
                    "arrival_airport": assumption.arrival_airport,
                    "departure_airport": assumption.departure_airport,
                    "layover_seconds": int(assumption.layover.total_seconds()),
                    "required_minimum_seconds": int(assumption.required_minimum.total_seconds()),
                    "airport_change": assumption.airport_change,
                    "provenance": assumption.provenance,
                    "transfer_cost": (
                        None
                        if assumption.transfer_cost is None
                        else {
                            "minor_units": assumption.transfer_cost.minor_units,
                            "currency": assumption.transfer_cost.currency,
                        }
                    ),
                }
                for assumption in self.connection_assumptions
            ],
            "unknown_costs": [
                {
                    "kind": cost.kind.value,
                    "leg_ordinal": cost.leg_ordinal,
                    "description": cost.description,
                }
                for cost in self.unknown_costs
            ],
            "protection_status": self.protection_status.value,
            "ranking_reasons": list(self.ranking_reasons),
        }


def require_confirmed_rank_input(
    value: ConfirmedOfferEvidence | ComposedRouteCandidate,
) -> ConfirmedOfferEvidence | ComposedRouteCandidate:
    if not isinstance(value, (ConfirmedOfferEvidence, ComposedRouteCandidate)):
        raise TypeError("confirmed evidence required")
    return value


def _require_evidence_identity(evidence_id: UUID, provider_id: str) -> None:
    if not isinstance(evidence_id, UUID):
        raise TypeError("id must be UUID")
    if not provider_id:
        raise ValueError("provider_id is required")


def _normalized_route(origin: str, destination: str) -> tuple[str, str]:
    if not isinstance(origin, str) or not isinstance(destination, str):
        raise TypeError("origin and destination must be strings")
    normalized_origin = origin.upper()
    normalized_destination = destination.upper()
    if not _IATA_RE.fullmatch(normalized_origin):
        raise ValueError("origin must be an IATA code")
    if not _IATA_RE.fullmatch(normalized_destination):
        raise ValueError("destination must be an IATA code")
    return normalized_origin, normalized_destination


def _normalized_currency(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.upper()
    if not _ISO_CURRENCY_RE.fullmatch(normalized):
        raise ValueError(f"{field_name} must be an ISO 4217 alpha-3 code")
    return normalized


def _timezone(value: str) -> tzinfo:
    return UTC if value == "UTC" else ZoneInfo(value)


def _require_dates(departure_date: date, return_date: date | None) -> None:
    if type(departure_date) is not date:
        raise TypeError("departure_date must be a date")
    if return_date is not None:
        if type(return_date) is not date:
            raise TypeError("return_date must be a date")
        if return_date < departure_date:
            raise ValueError("return_date cannot be before departure_date")


def _require_money(value: Money, field_name: str) -> None:
    if not isinstance(value, Money):
        raise TypeError(f"{field_name} must be Money")
    if value.minor_units < 0:
        raise ValueError(f"{field_name} cannot be negative")


def _inferred_checked_baggage(summary: str | None) -> CheckedBaggageState:
    if summary is not None and re.search(
        r"(?:^|,\s*)(?:baggage:|checked baggage )[1-9][0-9]*",
        summary,
    ):
        return CheckedBaggageState.INCLUDED
    return CheckedBaggageState.UNKNOWN


def _require_passengers(passengers: int) -> None:
    if type(passengers) is not int or passengers < 1:
        raise ValueError("passengers must be a positive integer")


def _require_aware_datetime(observed_at: datetime) -> None:
    if not isinstance(observed_at, datetime):
        raise TypeError("observed_at must be a datetime")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")


def _normalized_segment_ids(
    segment_ids: tuple[str, ...],
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    if isinstance(segment_ids, str):
        raise TypeError("segment_ids must be an ordered collection")
    normalized = tuple(segment_ids)
    if not allow_empty and not normalized:
        raise ValueError("segment_ids cannot be empty")
    if not all(isinstance(segment_id, str) and segment_id for segment_id in normalized):
        raise ValueError("segment_ids must contain non-empty strings")
    if len(set(normalized)) != len(normalized):
        raise ValueError("segment_ids must be unique")
    return normalized


def _normalized_segments(
    segments: tuple[FlightSegmentSummary, ...],
) -> tuple[FlightSegmentSummary, ...]:
    normalized = tuple(segments)
    if not normalized:
        raise ValueError("segments cannot be empty")
    if not all(isinstance(segment, FlightSegmentSummary) for segment in normalized):
        raise TypeError("segments must contain FlightSegmentSummary values")
    return normalized


def _normalized_provider_airport_changes(
    value: tuple[tuple[str, str], ...],
    segments: tuple[FlightSegmentSummary, ...],
) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        raise TypeError("provider_airport_changes must be an ordered collection")
    normalized: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise TypeError("provider_airport_changes must contain airport pairs")
        from_airport, to_airport = item
        if not isinstance(from_airport, str) or not isinstance(to_airport, str):
            raise TypeError("provider airport change codes must be strings")
        pair = (from_airport.upper(), to_airport.upper())
        if pair[0] == pair[1] or not _IATA_RE.fullmatch(pair[0]) or not _IATA_RE.fullmatch(pair[1]):
            raise ValueError("provider airport change codes must be distinct IATA codes")
        normalized.append(pair)
    actual = tuple(
        (previous.destination, current.origin)
        for previous, current in pairwise(segments)
        if previous.destination != current.origin
    )
    result = tuple(normalized)
    if result != actual:
        raise ValueError("provider airport changes must match segment gaps")
    return result
