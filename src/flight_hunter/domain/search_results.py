from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightOffer, Freshness
from flight_hunter.domain.policy import require_aware_datetime

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

SourceType = Literal["aggregator", "carrier", "search", "deal"]
PurchaseFlow = Literal["external_clickout", "external_search", "manual_check"]


class ResultKind(StrEnum):
    PRICED_OFFER = "priced_offer"
    EXTERNAL_SEARCH_LINK = "external_search_link"
    BROWSER_OBSERVATION = "browser_observation"
    DEAL_CANDIDATE = "deal_candidate"
    CARRIER_CONFIRMATION_LINK = "carrier_confirmation_link"


class Confidence(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceErrorCode(StrEnum):
    SOURCE_DISABLED = "source_disabled"
    CREDENTIALS_MISSING = "credentials_missing"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    PARSER_NO_PRICE = "parser_no_price"
    PARSER_ROUTE_MISMATCH = "parser_route_mismatch"
    BROWSER_TIMEOUT = "browser_timeout"
    WAITING_FOR_USER = "waiting_for_user"
    SOURCE_LAYOUT_CHANGED = "source_layout_changed"
    SOURCE_BLOCKED = "source_blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExternalSearchLink:
    source_id: str
    source_name: str
    url: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    adults: int
    children: int
    infants: int
    currency: str
    source_type: SourceType
    purchase_flow: PurchaseFlow
    price_known: bool = False
    requires_external_confirmation: bool = True
    notes_ru: str | None = None
    warnings: tuple[str, ...] = ()
    provider_link_path: str | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.source_id, "source_id")
        _require_nonempty(self.source_name, "source_name")
        _require_url(self.url)
        origin = self.origin.upper()
        destination = self.destination.upper()
        currency = self.currency.upper()
        _require_iata(origin, "origin")
        _require_iata(destination, "destination")
        _require_currency(currency)
        _require_passenger_mix(
            passengers=self.passengers,
            adults=self.adults,
            children=self.children,
            infants=self.infants,
        )
        if self.source_type not in {"aggregator", "carrier", "search", "deal"}:
            raise ValueError("unsupported source_type")
        if self.purchase_flow not in {"external_clickout", "external_search", "manual_check"}:
            raise ValueError("unsupported purchase_flow")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "currency", currency)

    @property
    def kind(self) -> ResultKind:
        if self.source_type == "carrier":
            return ResultKind.CARRIER_CONFIRMATION_LINK
        return ResultKind.EXTERNAL_SEARCH_LINK


@dataclass(frozen=True, slots=True)
class BrowserObservedOffer:
    observation_id: UUID
    source_id: str
    source_name: str
    provider_offer_id: str
    origin: str
    destination: str
    departure_date: str | None
    return_date: str | None
    total_price: Money | None
    passengers: int
    observed_at: datetime
    final_url: str
    display_url: str
    freshness: Freshness
    confidence: Confidence | str
    parser_version: str
    parser_warnings: tuple[str, ...]
    airline_name: str | None = None
    airline_iata: str | None = None
    flight_number: str | None = None
    departure_time_local: str | None = None
    arrival_time_local: str | None = None
    duration_minutes: int | None = None
    stops: int | None = None
    baggage_summary: str | None = None
    seller_name: str | None = None
    requires_external_confirmation: bool = True

    def __post_init__(self) -> None:
        _require_nonempty(self.source_id, "source_id")
        _require_nonempty(self.source_name, "source_name")
        _require_nonempty(self.provider_offer_id, "provider_offer_id")
        _require_url(self.final_url)
        _require_nonempty(self.display_url, "display_url")
        _require_iata(self.origin.upper(), "origin")
        _require_iata(self.destination.upper(), "destination")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("passengers must be a positive integer")
        require_aware_datetime(self.observed_at, "observed_at")
        confidence = Confidence(self.confidence)
        if self.freshness not in {
            Freshness.BROWSER_OBSERVED,
            Freshness.USER_CONFIRMED,
            Freshness.LIVE_OBSERVED,
            Freshness.STALE,
        }:
            raise ValueError("browser observation freshness must describe observed data")
        object.__setattr__(self, "origin", self.origin.upper())
        object.__setattr__(self, "destination", self.destination.upper())
        object.__setattr__(self, "confidence", confidence)

    @property
    def kind(self) -> ResultKind:
        return ResultKind.BROWSER_OBSERVATION


@dataclass(frozen=True, slots=True)
class DealCandidate:
    source_id: str
    url: str
    title: str
    summary_ru: str
    extracted_price: Money | None
    extracted_origin: str | None
    extracted_destination: str | None
    extracted_date_window: str | None
    confidence: Confidence | str
    discovered_at: datetime
    requires_manual_verification: bool = True
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.source_id, "source_id")
        _require_url(self.url)
        _require_nonempty(self.title, "title")
        _require_nonempty(self.summary_ru, "summary_ru")
        require_aware_datetime(self.discovered_at, "discovered_at")
        if self.expires_at is not None:
            require_aware_datetime(self.expires_at, "expires_at")
            if self.expires_at <= self.discovered_at:
                raise ValueError("expires_at must be after discovered_at")
        object.__setattr__(self, "confidence", Confidence(self.confidence))

    @property
    def kind(self) -> ResultKind:
        return ResultKind.DEAL_CANDIDATE


@dataclass(frozen=True, slots=True)
class FreshnessSummary:
    best_price_source: str | None
    freshest_observation_at: datetime | None
    needs_external_confirmation: bool

    def __post_init__(self) -> None:
        if self.freshest_observation_at is not None:
            require_aware_datetime(self.freshest_observation_at, "freshest_observation_at")


@dataclass(frozen=True, slots=True)
class SearchBundle:
    search_id: str
    priced_offers: tuple[FlightOffer, ...]
    provider_isolated_offers: tuple[FlightOffer, ...]
    browser_observed_offers: tuple[BrowserObservedOffer, ...]
    external_links: tuple[ExternalSearchLink, ...]
    deal_candidates: tuple[DealCandidate, ...]
    denied_sources: Mapping[str, object]
    warnings: tuple[str, ...]
    freshness_summary: FreshnessSummary


def _require_nonempty(value: str, field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} is required")


def _require_url(value: str) -> None:
    if not value.startswith(("https://", "http://")):
        raise ValueError("url must be http(s)")


def _require_iata(value: str, field_name: str) -> None:
    if not _IATA_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be an IATA code")


def _require_currency(value: str) -> None:
    if not _ISO_CURRENCY_RE.fullmatch(value):
        raise ValueError("currency must be an ISO 4217 alpha-3 code")


def _require_passenger_mix(
    *,
    passengers: int,
    adults: int,
    children: int,
    infants: int,
) -> None:
    values = (passengers, adults, children, infants)
    if any(type(value) is not int for value in values):
        raise ValueError("passenger counts must be integers")
    if passengers < 1 or adults < 1 or children < 0 or infants < 0:
        raise ValueError("invalid passenger mix")
    if adults + children + infants != passengers:
        raise ValueError("passengers must match passenger mix total")
