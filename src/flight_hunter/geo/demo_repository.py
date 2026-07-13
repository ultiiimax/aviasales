from __future__ import annotations

from flight_hunter.geo.airports import Airport, AirportType


class DemoAirportRepository:
    def __init__(self) -> None:
        self._airports = (
            Airport(
                iata_code="WAW",
                name="Warsaw Chopin Airport",
                municipality="Warsaw",
                country_code="PL",
                latitude=52.1657,
                longitude=20.9671,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="WMI",
                name="Warsaw Modlin Airport",
                municipality="Nowy Dwor Mazowiecki",
                country_code="PL",
                latitude=52.4511,
                longitude=20.6518,
                airport_type=AirportType.MEDIUM_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="LCJ",
                name="Lodz Wladyslaw Reymont Airport",
                municipality="Lodz",
                country_code="PL",
                latitude=51.7219,
                longitude=19.3981,
                airport_type=AirportType.MEDIUM_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="KRK",
                name="John Paul II International Airport Krakow-Balice",
                municipality="Krakow",
                country_code="PL",
                latitude=50.0777,
                longitude=19.7848,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="BCN",
                name="Barcelona-El Prat Airport",
                municipality="Barcelona",
                country_code="ES",
                latitude=41.2971,
                longitude=2.0785,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="LED",
                name="Pulkovo Airport",
                municipality="Saint Petersburg",
                country_code="RU",
                latitude=59.8003,
                longitude=30.2625,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                keywords=(
                    "spb",
                    "piter",
                    "saint petersburg",
                    "st petersburg",
                    "санкт-петербург",
                    "санкт петербург",
                    "спб",
                    "питер",
                ),
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="PVG",
                name="Shanghai Pudong International Airport",
                municipality="Shanghai",
                country_code="CN",
                latitude=31.1434,
                longitude=121.8052,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                keywords=("shanghai", "шанхай", "pudong", "пудун"),
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
            Airport(
                iata_code="SHA",
                name="Shanghai Hongqiao International Airport",
                municipality="Shanghai",
                country_code="CN",
                latitude=31.1979,
                longitude=121.3363,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                keywords=("shanghai", "шанхай", "hongqiao", "хунцяо", "хунцяо"),
                scheduled_service=True,
                commercial_provenance="demo.reference_catalog",
            ),
        )

    def all(self) -> tuple[Airport, ...]:
        return self._airports

    def get(self, iata_code: str) -> Airport | None:
        normalized_code = iata_code.upper()
        return next(
            (airport for airport in self._airports if airport.iata_code == normalized_code),
            None,
        )
