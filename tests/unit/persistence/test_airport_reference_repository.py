from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import AirportReferenceRepository

NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_airport_repository_imports_idempotently_and_searches_city_keywords() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        batch = AirportImportBatch(
            source_path="airports.csv",
            rows_seen=3,
            rows_imported=3,
            airports=(
                Airport(
                    iata_code="WAW",
                    name="Warsaw Chopin Airport",
                    municipality="Warsaw",
                    country_code="PL",
                    latitude=52.1657,
                    longitude=20.9671,
                    airport_type=AirportType.LARGE_AIRPORT,
                    active=True,
                    keywords=("Varsovia",),
                    scheduled_service=True,
                    commercial_provenance="ourairports.scheduled_service",
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
                    keywords=("Warsaw",),
                    scheduled_service=True,
                    commercial_provenance="ourairports.scheduled_service",
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
                    keywords=("Barcelone",),
                    scheduled_service=True,
                    commercial_provenance="ourairports.scheduled_service",
                ),
            ),
        )

        first = await repository.import_airports(batch, imported_at=NOW)
        second = await repository.import_airports(batch, imported_at=NOW)
        warsaw = await repository.search("Варшава")
        waw = await repository.get("WAW")
        original_snapshot = await repository.catalog_snapshot()
        await repository.import_airports(
            AirportImportBatch(
                source_path="later.csv",
                rows_seen=1,
                rows_imported=1,
                airports=(
                    Airport(
                        iata_code="CDG",
                        name="Charles de Gaulle Airport",
                        municipality="Paris",
                        country_code="FR",
                        latitude=49.0097,
                        longitude=2.5479,
                        airport_type=AirportType.LARGE_AIRPORT,
                        active=True,
                        scheduled_service=True,
                        commercial_provenance="ourairports.scheduled_service",
                    ),
                ),
            ),
            imported_at=NOW + timedelta(seconds=1),
        )
        later_snapshot = await repository.catalog_snapshot()
        imported = await repository.latest_import_run()

    assert first.rows_imported == 3
    assert second.rows_imported == 3
    assert [match.airport.iata_code for match in warsaw] == ["WAW", "WMI"]
    assert waw is not None
    assert waw.scheduled_service is True
    assert waw.commercial_provenance == "ourairports.scheduled_service"
    assert tuple(airport.iata_code for airport in original_snapshot.airports) == (
        "BCN",
        "WAW",
        "WMI",
    )
    assert original_snapshot.checksum != later_snapshot.checksum
    assert imported is not None
    assert imported.rows_seen == 1
    assert imported.rows_imported == 1


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
