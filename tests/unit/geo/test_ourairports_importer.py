from __future__ import annotations

from flight_hunter.geo.ourairports_importer import OurAirportsAirportImporter


def test_ourairports_importer_reads_searchable_iata_airports(tmp_path) -> None:
    csv_path = tmp_path / "airports.csv"
    csv_path.write_text(
        "\n".join(
            (
                "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,"
                "iso_country,iso_region,municipality,scheduled_service,gps_code,icao_code,"
                "iata_code,local_code,home_link,wikipedia_link,keywords",
                "1,EPWA,large_airport,Warsaw Chopin Airport,52.1657,20.9671,361,EU,"
                "PL,PL-MZ,Warsaw,yes,EPWA,EPWA,WAW,,https://example.test,,Varsovia",
                "2,EPMO,medium_airport,Warsaw Modlin Airport,52.4511,20.6518,341,EU,"
                "PL,PL-MZ,Nowy Dwor Mazowiecki,yes,EPMO,EPMO,WMI,,,Warsaw",
                "3,LEBL,large_airport,Barcelona-El Prat Airport,41.2971,2.0785,14,EU,"
                "ES,ES-CT,Barcelona,yes,LEBL,LEBL,BCN,,,Barcelone",
                "4,ZZZZ,small_airport,Tiny Field,1,2,0,EU,PL,PL-MZ,Tiny,no,ZZZZ,,TIN,,,,",
                "5,NOIA,large_airport,No IATA Airport,1,2,0,EU,PL,PL-MZ,Nowhere,yes,NOIA,,,,,,",
                "6,CLOS,closed,Closed Airport,1,2,0,EU,PL,PL-MZ,Closed,yes,CLOS,CLOS,CLS,,,,",
                "7,NOSV,medium_airport,No Service Airport,1,2,0,EU,PL,PL-MZ,Idle,no,NOSV,"
                "NOSV,NSV,,,,",
            )
        ),
        encoding="utf-8",
    )

    batch = OurAirportsAirportImporter().read_airports(csv_path)

    assert batch.rows_seen == 7
    assert batch.rows_imported == 3
    assert batch.observed_iata_codes == ("BCN", "CLS", "NSV", "TIN", "WAW", "WMI")
    assert [airport.iata_code for airport in batch.airports] == ["BCN", "WAW", "WMI"]
    assert batch.airports[1].keywords == ("Varsovia",)
    assert all(airport.scheduled_service for airport in batch.airports)
    assert {airport.commercial_provenance for airport in batch.airports} == {
        "ourairports.scheduled_service"
    }
