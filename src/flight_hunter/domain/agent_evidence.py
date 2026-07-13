from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary

_IATA_RE = re.compile(r"^[A-Z]{3}$")


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
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "segment_ids", segment_ids)
        object.__setattr__(self, "segments", segments)
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
    component_evidence_ids: tuple[UUID, ...]
    total_amount: Money
    passengers: int
    observed_at: datetime
    segment_ids: tuple[str, ...]
    segments: tuple[FlightSegmentSummary, ...]
    protection_status: ProtectionStatus

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("id must be UUID")
        component_ids = tuple(self.component_evidence_ids)
        if not component_ids:
            raise ValueError("component_evidence_ids cannot be empty")
        if not all(isinstance(component_id, UUID) for component_id in component_ids):
            raise TypeError("component_evidence_ids must contain UUID values")
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("component_evidence_ids must be unique")
        _require_money(self.total_amount, "total_amount")
        _require_passengers(self.passengers)
        _require_aware_datetime(self.observed_at)
        segment_ids = _normalized_segment_ids(self.segment_ids, allow_empty=False)
        segments = _normalized_segments(self.segments)
        if len(segment_ids) != len(segments):
            raise ValueError("segment_ids must match segments")
        object.__setattr__(self, "component_evidence_ids", component_ids)
        object.__setattr__(self, "segment_ids", segment_ids)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(
            self,
            "protection_status",
            ProtectionStatus(self.protection_status),
        )

    @property
    def confirmation_state(self) -> ConfirmationState:
        return ConfirmationState.CONFIRMED


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
