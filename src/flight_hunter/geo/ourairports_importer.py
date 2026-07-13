from __future__ import annotations

import csv
import re
from pathlib import Path

from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType

_SEARCHABLE_TYPES = {
    AirportType.LARGE_AIRPORT.value,
    AirportType.MEDIUM_AIRPORT.value,
}
_IATA_CODE_RE = re.compile(r"^[A-Z]{3}$")


class OurAirportsAirportImporter:
    def read_airports(self, path: str | Path) -> AirportImportBatch:
        source_path = Path(path)
        rows_seen = 0
        airports: list[Airport] = []
        observed_iata_codes: set[str] = set()

        with source_path.open("r", encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                rows_seen += 1
                iata_code = row.get("iata_code", "").strip().upper()
                if _IATA_CODE_RE.fullmatch(iata_code):
                    observed_iata_codes.add(iata_code)
                airport = _airport_from_row(row)
                if airport is not None:
                    airports.append(airport)

        airports.sort(key=lambda airport: airport.iata_code)
        return AirportImportBatch(
            source_path=str(source_path),
            rows_seen=rows_seen,
            rows_imported=len(airports),
            airports=tuple(airports),
            observed_iata_codes=tuple(sorted(observed_iata_codes)),
        )


def _airport_from_row(row: dict[str, str]) -> Airport | None:
    airport_type = row.get("type", "").strip()
    iata_code = row.get("iata_code", "").strip().upper()
    if airport_type not in _SEARCHABLE_TYPES or not iata_code:
        return None
    if row.get("scheduled_service", "").strip().lower() != "yes":
        return None

    try:
        latitude = float(row.get("latitude_deg", ""))
        longitude = float(row.get("longitude_deg", ""))
        parsed_type = AirportType(airport_type)
        return Airport(
            iata_code=iata_code,
            name=row.get("name", "").strip(),
            municipality=row.get("municipality", "").strip() or row.get("name", "").strip(),
            country_code=row.get("iso_country", "").strip().upper(),
            latitude=latitude,
            longitude=longitude,
            airport_type=parsed_type,
            active=True,
            keywords=_keywords(row.get("keywords", "")),
            scheduled_service=True,
            commercial_provenance="ourairports.scheduled_service",
        )
    except ValueError:
        return None


def _keywords(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(keyword.strip() for keyword in value.split(",") if keyword.strip())
