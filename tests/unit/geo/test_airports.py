from __future__ import annotations

from flight_hunter.geo.airports import Airport, AirportType, distance_km


def test_distance_between_warsaw_airports_is_approximately_correct() -> None:
    waw = Airport(
        iata_code="WAW",
        name="Warsaw Chopin Airport",
        municipality="Warsaw",
        country_code="PL",
        latitude=52.1657,
        longitude=20.9671,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
    )
    wmi = Airport(
        iata_code="WMI",
        name="Warsaw Modlin Airport",
        municipality="Nowy Dwor Mazowiecki",
        country_code="PL",
        latitude=52.4511,
        longitude=20.6518,
        airport_type=AirportType.MEDIUM_AIRPORT,
        active=True,
    )

    assert distance_km(waw, wmi) == 38


def test_airport_normalizes_iata_and_rejects_closed_airports_for_commercial_search() -> None:
    airport = Airport(
        iata_code="waw",
        name="Warsaw Chopin Airport",
        municipality="Warsaw",
        country_code="pl",
        latitude=52.1657,
        longitude=20.9671,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance="ourairports.scheduled_service",
    )

    assert airport.iata_code == "WAW"
    assert airport.country_code == "PL"
    assert airport.is_searchable


def test_airport_without_explicit_commercial_evidence_is_not_searchable() -> None:
    airport = Airport(
        iata_code="WAW",
        name="Warsaw Chopin Airport",
        municipality="Warsaw",
        country_code="PL",
        latitude=52.1657,
        longitude=20.9671,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
    )

    assert airport.scheduled_service is None
    assert airport.commercial_provenance is None
    assert not airport.is_searchable
