from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_ISO_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class LocationScopeKind(StrEnum):
    AIRPORT = "airport"
    CITY = "city"
    COUNTRY = "country"
    REGION = "region"
    ANYWHERE = "anywhere"


class TripShape(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"
    OPEN_JAW = "open_jaw"
    MULTI_CITY = "multi_city"


class DateMode(StrEnum):
    EXACT = "exact"
    FLEXIBLE = "flexible"
    RANGE = "range"
    ROLLING_90_DAYS = "rolling_90_days"


class RouteStrategy(StrEnum):
    DIRECT = "direct"
    THROUGH_TICKET = "through_ticket"
    SPLIT_TICKET = "split_ticket"
    SELF_TRANSFER = "self_transfer"
    HIDDEN_CITY = "hidden_city"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LocationScope:
    kind: LocationScopeKind
    value: str | None

    def __post_init__(self) -> None:
        kind = LocationScopeKind(self.kind)
        value = self.value
        if kind is LocationScopeKind.ANYWHERE:
            if value is not None:
                raise ValueError("anywhere scope cannot have a value")
        else:
            if not isinstance(value, str) or not value.strip():
                raise ValueError("location scope value is required")
            value = value.strip()
            if kind in {LocationScopeKind.AIRPORT, LocationScopeKind.CITY}:
                value = value.upper()
                if not _IATA_RE.fullmatch(value):
                    raise ValueError(f"{kind.value} scope must be an IATA code")
            elif kind is LocationScopeKind.COUNTRY:
                value = value.upper()
                if not _ISO_COUNTRY_RE.fullmatch(value):
                    raise ValueError("country scope must be an ISO 3166 alpha-2 code")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class DateConstraint:
    mode: DateMode
    start_date: date
    end_date: date | None = None
    flex_days: int = 0

    def __post_init__(self) -> None:
        mode = DateMode(self.mode)
        if type(self.start_date) is not date:
            raise TypeError("start_date must be a date")
        if self.end_date is not None and type(self.end_date) is not date:
            raise TypeError("end_date must be a date")
        if type(self.flex_days) is not int:
            raise TypeError("flex_days must be an integer")
        if self.flex_days < 0:
            raise ValueError("flex_days cannot be negative")

        if mode is DateMode.EXACT:
            if self.end_date is not None or self.flex_days != 0:
                raise ValueError("exact date cannot have a range or flexibility")
        elif mode is DateMode.FLEXIBLE:
            if self.end_date is not None or self.flex_days <= 0:
                raise ValueError("flexible date requires positive flex_days and no end_date")
        else:
            if self.end_date is None:
                raise ValueError(f"{mode.value} date requires end_date")
            if self.end_date < self.start_date:
                raise ValueError("end_date cannot be before start_date")
            if self.flex_days != 0:
                raise ValueError(f"{mode.value} date cannot also have flex_days")
            if mode is DateMode.ROLLING_90_DAYS and (self.end_date - self.start_date).days != 89:
                raise ValueError("rolling_90_days must contain exactly 90 inclusive dates")
        object.__setattr__(self, "mode", mode)


@dataclass(frozen=True, slots=True)
class TravelLeg:
    origin: LocationScope
    destination: LocationScope
    date_constraint: DateConstraint

    def __post_init__(self) -> None:
        if not isinstance(self.origin, LocationScope):
            raise TypeError("origin must be LocationScope")
        if not isinstance(self.destination, LocationScope):
            raise TypeError("destination must be LocationScope")
        if not isinstance(self.date_constraint, DateConstraint):
            raise TypeError("date_constraint must be DateConstraint")


@dataclass(frozen=True, slots=True)
class TravelIntent:
    trip_shape: TripShape
    legs: tuple[TravelLeg, ...]
    adults: int
    currency: str
    children: int = 0
    infants: int = 0
    requested_strategies: tuple[RouteStrategy, ...] = ()

    def __post_init__(self) -> None:
        trip_shape = TripShape(self.trip_shape)
        legs = tuple(self.legs)
        if not all(isinstance(leg, TravelLeg) for leg in legs):
            raise TypeError("legs must contain TravelLeg values")

        passenger_counts = (self.adults, self.children, self.infants)
        if any(type(count) is not int for count in passenger_counts):
            raise TypeError("passenger counts must be integers")
        if self.adults <= 0:
            raise ValueError("adults must be positive")
        if self.children < 0 or self.infants < 0:
            raise ValueError("children and infants cannot be negative")

        if not isinstance(self.currency, str):
            raise TypeError("currency must be a string")
        currency = self.currency.upper()
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError("currency must be an ISO 4217 alpha-3 code")

        required_leg_count = {
            TripShape.ONE_WAY: 1,
            TripShape.ROUND_TRIP: 2,
            TripShape.OPEN_JAW: 2,
        }.get(trip_shape)
        if required_leg_count is not None and len(legs) != required_leg_count:
            raise ValueError(f"{trip_shape.value} requires {required_leg_count} leg(s)")
        if trip_shape is TripShape.MULTI_CITY and len(legs) < 2:
            raise ValueError("multi_city requires at least two legs")

        strategies = tuple(RouteStrategy(strategy) for strategy in self.requested_strategies)
        if len(set(strategies)) != len(strategies):
            raise ValueError("requested_strategies must be unique")

        object.__setattr__(self, "trip_shape", trip_shape)
        object.__setattr__(self, "legs", legs)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "requested_strategies", strategies)

    @property
    def passengers(self) -> int:
        return self.adults + self.children + self.infants


@dataclass(frozen=True, slots=True)
class PlanBudget:
    logical_operations: int
    http_attempts: int
    deadline_seconds: int

    def __post_init__(self) -> None:
        values = (self.logical_operations, self.http_attempts, self.deadline_seconds)
        if any(type(value) is not int for value in values):
            raise TypeError("plan budgets must be integers")
        if min(values) <= 0:
            raise ValueError("plan budgets must be positive")


@dataclass(frozen=True, slots=True)
class ProviderHttpCostModel:
    version: str
    start_attempts: int
    poll_rounds: int
    attempts_per_poll: int
    requests_per_minute: int = 20

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("cost model version is required")
        values = (
            self.start_attempts,
            self.poll_rounds,
            self.attempts_per_poll,
            self.requests_per_minute,
        )
        if any(type(value) is not int for value in values):
            raise TypeError("provider HTTP costs must be integers")
        if min(values) <= 0:
            raise ValueError("provider HTTP costs must be positive")

    @property
    def worst_case_exact_http_attempts(self) -> int:
        return self.start_attempts + self.poll_rounds * self.attempts_per_poll


@dataclass(frozen=True, slots=True)
class ProviderCapabilitySnapshot:
    provider_id: str
    version: str
    one_way: CapabilityState
    round_trip: CapabilityState
    native_open_jaw: CapabilityState
    native_multi_city: CapabilityState
    explicit_connection_protection: CapabilityState
    airport_location_semantics: CapabilityState
    city_location_semantics: CapabilityState
    cost_model: ProviderHttpCostModel

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        if not self.version:
            raise ValueError("capability version is required")
        if not isinstance(self.cost_model, ProviderHttpCostModel):
            raise TypeError("cost_model must be ProviderHttpCostModel")
        for field_name in (
            "one_way",
            "round_trip",
            "native_open_jaw",
            "native_multi_city",
            "explicit_connection_protection",
            "airport_location_semantics",
            "city_location_semantics",
        ):
            object.__setattr__(self, field_name, CapabilityState(getattr(self, field_name)))
