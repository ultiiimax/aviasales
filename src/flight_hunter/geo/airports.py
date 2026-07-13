from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

_IATA_RE = re.compile(r"^[A-Z]{3}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_EARTH_RADIUS_KM = 6371.0088


class AirportType(StrEnum):
    LARGE_AIRPORT = "large_airport"
    MEDIUM_AIRPORT = "medium_airport"
    SMALL_AIRPORT = "small_airport"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class Airport:
    iata_code: str
    name: str
    municipality: str
    country_code: str
    latitude: float
    longitude: float
    airport_type: AirportType
    active: bool
    keywords: tuple[str, ...] = ()
    scheduled_service: bool | None = None
    commercial_provenance: str | None = None

    def __post_init__(self) -> None:
        iata_code = self.iata_code.upper()
        country_code = self.country_code.upper()
        if not _IATA_RE.fullmatch(iata_code):
            raise ValueError("iata_code must be a 3-letter IATA code")
        if not _COUNTRY_RE.fullmatch(country_code):
            raise ValueError("country_code must be an ISO 3166 alpha-2 code")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not self.name:
            raise ValueError("name is required")
        if not self.municipality:
            raise ValueError("municipality is required")
        if self.scheduled_service is not None and type(self.scheduled_service) is not bool:
            raise TypeError("scheduled_service must be a boolean or None")
        commercial_provenance = self.commercial_provenance
        if commercial_provenance is not None:
            if not isinstance(commercial_provenance, str):
                raise TypeError("commercial_provenance must be a string or None")
            commercial_provenance = commercial_provenance.strip()
            if not commercial_provenance:
                raise ValueError("commercial_provenance cannot be empty")

        object.__setattr__(self, "iata_code", iata_code)
        object.__setattr__(self, "country_code", country_code)
        object.__setattr__(
            self,
            "keywords",
            tuple(keyword.strip() for keyword in self.keywords if keyword.strip()),
        )
        object.__setattr__(self, "commercial_provenance", commercial_provenance)

    @property
    def is_searchable(self) -> bool:
        return (
            self.active
            and self.scheduled_service is True
            and self.commercial_provenance is not None
            and self.airport_type
            in {
                AirportType.LARGE_AIRPORT,
                AirportType.MEDIUM_AIRPORT,
            }
        )


@dataclass(frozen=True, slots=True)
class AirportCatalogSnapshot:
    airports: tuple[Airport, ...]
    checksum: str


def freeze_airport_catalog(airports: tuple[Airport, ...]) -> AirportCatalogSnapshot:
    ordered = tuple(sorted(airports, key=lambda airport: airport.iata_code))
    if not all(isinstance(airport, Airport) for airport in ordered):
        raise TypeError("airports must contain Airport values")
    codes = tuple(airport.iata_code for airport in ordered)
    if len(set(codes)) != len(codes):
        raise ValueError("airport catalog cannot contain duplicate IATA codes")
    payload = [
        {
            "iata": airport.iata_code,
            "country": airport.country_code,
            "type": airport.airport_type.value,
            "scheduled_service": airport.scheduled_service,
            "active": airport.active,
        }
        for airport in ordered
    ]
    checksum = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AirportCatalogSnapshot(airports=ordered, checksum=checksum)


def distance_km(origin: Airport, destination: Airport) -> int:
    origin_latitude = math.radians(origin.latitude)
    destination_latitude = math.radians(destination.latitude)
    latitude_delta = math.radians(destination.latitude - origin.latitude)
    longitude_delta = math.radians(destination.longitude - origin.longitude)

    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(origin_latitude)
        * math.cos(destination_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    angular_distance = 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
    return round(_EARTH_RADIUS_KM * angular_distance)


@dataclass(frozen=True, slots=True)
class AirportImportBatch:
    source_path: str | Path
    rows_seen: int
    rows_imported: int
    airports: tuple[Airport, ...]
    observed_iata_codes: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.observed_iata_codes is None:
            return
        if not all(isinstance(code, str) for code in self.observed_iata_codes):
            raise TypeError("observed_iata_codes must contain strings")
        observed = tuple(sorted({code.strip().upper() for code in self.observed_iata_codes}))
        if any(not _IATA_RE.fullmatch(code) for code in observed):
            raise ValueError("observed_iata_codes must contain valid IATA codes")
        imported = {airport.iata_code for airport in self.airports}
        if not imported.issubset(observed):
            raise ValueError("imported airports must be present in observed_iata_codes")
        object.__setattr__(self, "observed_iata_codes", observed)


@dataclass(frozen=True, slots=True)
class AirportImportRun:
    source: str
    source_path: str
    imported_at: datetime
    rows_seen: int
    rows_imported: int
