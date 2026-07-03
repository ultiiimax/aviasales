from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from flight_hunter.domain.money import Money
from flight_hunter.domain.policy import require_aware_datetime

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class Freshness(StrEnum):
    LIVE_OBSERVED = "live_observed"
    USER_CONFIRMED = "user_confirmed"
    BROWSER_OBSERVED = "browser_observed"
    API_CACHED = "api_cached"
    LIVE = "live"
    RECENT = "recent"
    CACHED = "cached"
    STALE = "stale"
    UNKNOWN_EXTERNAL = "unknown_external"


class PriceBasis(StrEnum):
    TOTAL_FOR_PASSENGERS = "total_for_passengers"
    PROVIDER_SINGLE_ADULT_TICKET = "provider_single_adult_ticket"


class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"


@dataclass(frozen=True, slots=True)
class PassengerMix:
    adults: int
    children: int = 0
    infants: int = 0

    def __post_init__(self) -> None:
        if type(self.adults) is not int or self.adults < 1:
            raise ValueError("adults must be positive")
        if type(self.children) is not int or self.children < 0:
            raise ValueError("children cannot be negative")
        if type(self.infants) is not int or self.infants < 0:
            raise ValueError("infants cannot be negative")

    @property
    def total(self) -> int:
        return self.adults + self.children + self.infants


@dataclass(frozen=True, slots=True)
class SearchIntent:
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    passengers: int
    currency: str
    adults: int | None = None
    children: int = 0
    infants: int = 0
    trip_type: TripType | str | None = None

    def __post_init__(self) -> None:
        origin = self.origin.upper()
        destination = self.destination.upper()
        currency = self.currency.upper()
        if not _IATA_RE.fullmatch(origin):
            raise ValueError("origin must be an IATA code")
        if not _IATA_RE.fullmatch(destination):
            raise ValueError("destination must be an IATA code")
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be an ISO 4217 alpha-3 code")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("passengers must be a positive integer")
        passenger_mix = PassengerMix(
            adults=self.adults if self.adults is not None else self.passengers,
            children=self.children,
            infants=self.infants,
        )
        if passenger_mix.total != self.passengers:
            raise ValueError("passengers must match passenger mix total")
        trip_type = _trip_type(self.trip_type, return_date=self.return_date)
        if trip_type == TripType.ROUND_TRIP and self.return_date is None:
            raise ValueError("round trip requires return_date")
        if trip_type == TripType.ONE_WAY and self.return_date is not None:
            raise ValueError("one-way trip cannot have return_date")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "adults", passenger_mix.adults)
        object.__setattr__(self, "children", passenger_mix.children)
        object.__setattr__(self, "infants", passenger_mix.infants)
        object.__setattr__(self, "trip_type", trip_type)

    @property
    def passenger_mix(self) -> PassengerMix:
        return PassengerMix(
            adults=self.adults if self.adults is not None else self.passengers,
            children=self.children,
            infants=self.infants,
        )


def _trip_type(value: TripType | str | None, *, return_date: str | None) -> TripType:
    if value is None:
        return TripType.ROUND_TRIP if return_date is not None else TripType.ONE_WAY
    return TripType(value)


@dataclass(frozen=True, slots=True)
class FlightOffer:
    provider_id: str
    provider_offer_id: str
    origin: str
    destination: str
    departure_date: str
    return_date: str | None
    total_price: Money
    passengers: int
    observed_at: datetime
    freshness: Freshness
    requires_live_confirmation: bool
    baggage_summary: str | None
    price_basis: PriceBasis | str = PriceBasis.TOTAL_FOR_PASSENGERS

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        if not self.provider_offer_id:
            raise ValueError("provider_offer_id is required")
        if type(self.passengers) is not int or self.passengers < 1:
            raise ValueError("passengers must be a positive integer")
        price_basis = PriceBasis(self.price_basis)
        if price_basis == PriceBasis.PROVIDER_SINGLE_ADULT_TICKET and self.passengers != 1:
            raise ValueError("single-adult ticket prices require passengers=1")
        object.__setattr__(self, "price_basis", price_basis)
        require_aware_datetime(self.observed_at, "observed_at")
