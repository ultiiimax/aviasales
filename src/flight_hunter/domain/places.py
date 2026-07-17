from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_IATA_RE = re.compile(r"[A-Z]{3}")
_COUNTRY_RE = re.compile(r"[A-Z]{2}")


class PlaceKind(StrEnum):
    CITY = "city"
    AIRPORT = "airport"


@dataclass(frozen=True, slots=True)
class PlaceRef:
    kind: PlaceKind
    code: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PlaceKind):
            raise TypeError("kind must be a PlaceKind")
        if not isinstance(self.code, str):
            raise TypeError("place code must be a string")
        code = self.code.strip().upper()
        if not _IATA_RE.fullmatch(code):
            raise ValueError("place code must be a three-letter IATA code")
        object.__setattr__(self, "code", code)


@dataclass(frozen=True, slots=True)
class PlaceLabel:
    text: str
    resolved_locale: str
    provenance: str
    fallback_reason: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("text", "resolved_locale", "provenance"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            value = value.strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
        if self.fallback_reason is not None:
            if not isinstance(self.fallback_reason, str):
                raise TypeError("fallback_reason must be a string or None")
            fallback_reason = self.fallback_reason.strip()
            if not fallback_reason:
                raise ValueError("fallback_reason cannot be empty")
            object.__setattr__(self, "fallback_reason", fallback_reason)


@dataclass(frozen=True, slots=True)
class PlaceOption:
    ref: PlaceRef
    display_name: PlaceLabel
    city_name: PlaceLabel | None
    country_code: str | None
    country_name: PlaceLabel | None
    airport_codes: tuple[str, ...]
    directory_version: str
    membership_version: str
    membership_observed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.ref, PlaceRef):
            raise TypeError("ref must be a PlaceRef")
        if not isinstance(self.display_name, PlaceLabel):
            raise TypeError("display_name must be a PlaceLabel")
        if self.city_name is not None and not isinstance(self.city_name, PlaceLabel):
            raise TypeError("city_name must be a PlaceLabel or None")
        if self.country_name is not None and not isinstance(self.country_name, PlaceLabel):
            raise TypeError("country_name must be a PlaceLabel or None")
        if self.country_code is not None:
            if not isinstance(self.country_code, str):
                raise TypeError("country_code must be a string or None")
            country_code = self.country_code.strip().upper()
            if not _COUNTRY_RE.fullmatch(country_code):
                raise ValueError("country_code must be an ISO 3166 alpha-2 code")
            object.__setattr__(self, "country_code", country_code)
        if not isinstance(self.airport_codes, tuple):
            raise TypeError("airport_codes must be a tuple")
        airport_codes = tuple(code.strip().upper() for code in self.airport_codes)
        if not airport_codes or any(not _IATA_RE.fullmatch(code) for code in airport_codes):
            raise ValueError("airport_codes must contain valid IATA codes")
        if len(set(airport_codes)) != len(airport_codes):
            raise ValueError("airport_codes cannot contain duplicates")
        object.__setattr__(self, "airport_codes", airport_codes)
        for field_name in (
            "directory_version",
            "membership_version",
            "membership_observed_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise TypeError(f"{field_name} must be a string")
            value = value.strip()
            if not value:
                raise ValueError(f"{field_name} cannot be empty")
            object.__setattr__(self, field_name, value)
