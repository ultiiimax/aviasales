from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.application.agent_scope import CoverageMode, FrozenAirportScope, ScopeResolver
from flight_hunter.domain.agent_search import LocationScope, LocationScopeKind
from flight_hunter.geo.airports import Airport, AirportImportBatch, AirportType
from flight_hunter.geo.ourairports_importer import OurAirportsAirportImporter
from flight_hunter.persistence import repositories as persistence_repositories
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


@pytest.mark.anyio
async def test_airport_repository_rejects_missing_commercial_evidence() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        batch = AirportImportBatch(
            source_path="unknown.csv",
            rows_seen=1,
            rows_imported=1,
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
                ),
            ),
        )

        with pytest.raises(ValueError, match="explicit commercial evidence"):
            await repository.import_airports(batch, imported_at=NOW)


@pytest.mark.anyio
async def test_full_snapshot_deactivates_only_observed_filtered_legacy_rows(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "airports.csv"
    _write_ourairports_snapshot(
        csv_path,
        (
            _ourairports_row("LEG", "Legacy", "large_airport", "no"),
            _ourairports_row("MAN", "Manual", "small_airport", "yes"),
            _ourairports_row("CUR", "Current", "large_airport", "yes"),
        ),
    )
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        await repository.import_airports(
            AirportImportBatch(
                source_path="legacy-backfill",
                rows_seen=2,
                rows_imported=2,
                airports=(
                    _reference_airport("LEG", "Legacy", "legacy_import_filter"),
                    _reference_airport("ABS", "Absent Legacy", "legacy_import_filter"),
                ),
            ),
            imported_at=NOW,
            source="legacy",
        )
        await repository.import_airports(
            AirportImportBatch(
                source_path="manual-reference",
                rows_seen=1,
                rows_imported=1,
                airports=(_reference_airport("MAN", "Manual", "manual.reference"),),
            ),
            imported_at=NOW + timedelta(seconds=1),
            source="manual",
        )

        await repository.import_airports(
            OurAirportsAirportImporter().read_airports(csv_path),
            imported_at=NOW + timedelta(seconds=2),
        )
        snapshot = await repository.catalog_snapshot()

    airports = {airport.iata_code: airport for airport in snapshot.airports}
    assert not airports["LEG"].active
    assert airports["LEG"].commercial_provenance == "legacy_import_filter"
    assert airports["ABS"].active
    assert airports["ABS"].commercial_provenance == "legacy_import_filter"
    assert airports["MAN"].active
    assert airports["MAN"].commercial_provenance == "manual.reference"
    assert airports["CUR"].active
    assert airports["CUR"].commercial_provenance == "ourairports.scheduled_service"


@pytest.mark.anyio
async def test_header_only_snapshot_is_rejected_without_catalog_mutation(tmp_path: Path) -> None:
    csv_path = tmp_path / "airports.csv"
    _write_ourairports_snapshot(
        csv_path,
        (_ourairports_row("AAA", "Alpha", "large_airport", "yes"),),
    )
    importer = OurAirportsAirportImporter()
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        await repository.import_airports(importer.read_airports(csv_path), imported_at=NOW)
        before = await repository.catalog_snapshot()
        _write_ourairports_snapshot(csv_path, ())

        with pytest.raises(ValueError, match=r"^ourairports_snapshot_has_no_valid_iata$"):
            importer.read_airports(csv_path)

        after = await repository.catalog_snapshot()
        latest = await repository.latest_import_run()

    assert after == before
    assert latest is not None
    assert latest.rows_seen == 1


@pytest.mark.anyio
async def test_repository_rejects_empty_full_snapshot_marker_before_mutation(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "airports.csv"
    _write_ourairports_snapshot(
        csv_path,
        (_ourairports_row("AAA", "Alpha", "large_airport", "yes"),),
    )
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        await repository.import_airports(
            OurAirportsAirportImporter().read_airports(csv_path),
            imported_at=NOW,
        )
        before = await repository.catalog_snapshot()

        with pytest.raises(ValueError, match=r"^ourairports_snapshot_has_no_valid_iata$"):
            await repository.import_airports(
                AirportImportBatch(
                    source_path="empty.csv",
                    rows_seen=0,
                    rows_imported=0,
                    airports=(),
                    observed_iata_codes=(),
                ),
                imported_at=NOW + timedelta(seconds=1),
            )

        after = await repository.catalog_snapshot()

    assert after == before


@pytest.mark.anyio
async def test_repository_rejects_inconsistent_full_snapshot_marker() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)

        with pytest.raises(
            ValueError,
            match=r"^ourairports_snapshot_observed_iata_exceeds_rows_seen$",
        ):
            await repository.import_airports(
                AirportImportBatch(
                    source_path="inconsistent.csv",
                    rows_seen=1,
                    rows_imported=0,
                    airports=(),
                    observed_iata_codes=("AAA", "BBB"),
                ),
                imported_at=NOW,
            )


@pytest.mark.anyio
async def test_truncated_full_snapshot_is_rejected_before_any_mutation(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "airports.csv"
    _write_ourairports_snapshot(
        csv_path,
        tuple(
            _ourairports_row(code, municipality, "large_airport", "yes")
            for code, municipality in (
                ("AAA", "Alpha"),
                ("BBB", "Bravo"),
                ("CCC", "Charlie"),
                ("DDD", "Delta"),
                ("EEE", "Echo"),
            )
        ),
    )
    importer = OurAirportsAirportImporter()
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        await repository.import_airports(importer.read_airports(csv_path), imported_at=NOW)
        await repository.import_airports(
            AirportImportBatch(
                source_path="manual-reference",
                rows_seen=1,
                rows_imported=1,
                airports=(_reference_airport("MAN", "Manual", "manual.reference"),),
            ),
            imported_at=NOW + timedelta(seconds=1),
            source="manual",
        )
        before = await repository.catalog_snapshot()
        _write_ourairports_snapshot(
            csv_path,
            (
                _ourairports_row("AAA", "Changed Alpha", "large_airport", "yes"),
                _ourairports_row("BBB", "Bravo", "large_airport", "yes"),
                _ourairports_row("NEW", "New", "large_airport", "yes"),
            ),
        )

        with pytest.raises(
            ValueError,
            match=r"^ourairports_snapshot_retention_below_0\.80$",
        ):
            await repository.import_airports(
                importer.read_airports(csv_path),
                imported_at=NOW + timedelta(seconds=2),
            )

        after = await repository.catalog_snapshot()
        latest = await repository.latest_import_run()

    assert after == before
    assert latest is not None
    assert latest.source == "manual"


@pytest.mark.anyio
async def test_full_ourairports_snapshot_deactivates_filtered_and_disappeared_rows(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "airports.csv"
    _write_ourairports_snapshot(
        csv_path,
        (
            _ourairports_row("AAA", "Alpha", "large_airport", "yes"),
            _ourairports_row("BBB", "Bravo", "large_airport", "yes"),
            _ourairports_row("CCC", "Charlie", "large_airport", "yes"),
            _ourairports_row("DDD", "Delta", "large_airport", "yes"),
            _ourairports_row("FFF", "Foxtrot", "large_airport", "yes"),
        ),
    )
    importer = OurAirportsAirportImporter()
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = AirportReferenceRepository(session)
        await repository.import_airports(importer.read_airports(csv_path), imported_at=NOW)
        await repository.import_airports(
            AirportImportBatch(
                source_path="manual-reference",
                rows_seen=1,
                rows_imported=1,
                airports=(
                    Airport(
                        iata_code="EEE",
                        name="Echo Reference Airport",
                        municipality="Echo",
                        country_code="FR",
                        latitude=48.5,
                        longitude=2.5,
                        airport_type=AirportType.LARGE_AIRPORT,
                        active=True,
                        scheduled_service=True,
                        commercial_provenance="manual.reference",
                    ),
                ),
            ),
            imported_at=NOW + timedelta(seconds=1),
            source="manual",
        )
        _write_ourairports_snapshot(
            csv_path,
            (
                _ourairports_row("AAA", "Alpha", "large_airport", "no"),
                _ourairports_row("BBB", "Bravo", "small_airport", "yes"),
                _ourairports_row("CCC", "Charlie", "closed", "yes"),
                _ourairports_row("FFF", "Foxtrot", "large_airport", "yes"),
            ),
        )

        replacement = importer.read_airports(csv_path)
        await repository.import_airports(
            replacement,
            imported_at=NOW + timedelta(seconds=2),
        )
        snapshot = await repository.catalog_snapshot()
        resolved = await ScopeResolver(repository=repository).resolve_finite(
            LocationScope(LocationScopeKind.COUNTRY, "FR"),
            coverage=CoverageMode.FULL,
        )

    airports = {airport.iata_code: airport for airport in snapshot.airports}
    assert Decimal("0.80") == persistence_repositories.MIN_OURAIRPORTS_SNAPSHOT_RETENTION_RATIO
    assert replacement.rows_seen == 4
    assert replacement.observed_iata_codes == ("AAA", "BBB", "CCC", "FFF")
    assert all(not airports[code].active for code in ("AAA", "BBB", "CCC", "DDD"))
    assert all(not airports[code].is_searchable for code in ("AAA", "BBB", "CCC", "DDD"))
    assert airports["EEE"].is_searchable
    assert airports["EEE"].commercial_provenance == "manual.reference"
    assert airports["FFF"].is_searchable
    assert isinstance(resolved, FrozenAirportScope)
    assert resolved.airport_codes == ("EEE", "FFF")


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _write_ourairports_snapshot(path: Path, rows: tuple[str, ...]) -> None:
    path.write_text(
        "\n".join(
            (
                "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,"
                "iso_country,iso_region,municipality,scheduled_service,gps_code,icao_code,"
                "iata_code,local_code,home_link,wikipedia_link,keywords",
                *rows,
            )
        ),
        encoding="utf-8",
    )


def _ourairports_row(
    iata_code: str,
    municipality: str,
    airport_type: str,
    scheduled_service: str,
) -> str:
    return (
        f"1,{iata_code},{airport_type},{municipality} Airport,48.0,2.0,100,EU,FR,FR-IDF,"
        f"{municipality},{scheduled_service},{iata_code},{iata_code},{iata_code},,,,"
    )


def _reference_airport(iata_code: str, municipality: str, provenance: str) -> Airport:
    return Airport(
        iata_code=iata_code,
        name=f"{municipality} Airport",
        municipality=municipality,
        country_code="FR",
        latitude=48.0,
        longitude=2.0,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance=provenance,
    )
