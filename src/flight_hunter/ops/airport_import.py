from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from flight_hunter.config import AppSettings, load_env_file
from flight_hunter.geo.ourairports_importer import OurAirportsAirportImporter
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import AirportReferenceRepository


async def run_import(*, airports_csv: Path, database_url: str) -> dict[str, object]:
    if not airports_csv.exists():
        return {
            "status": "file_missing",
            "rows_seen": 0,
            "rows_imported": 0,
        }

    batch = OurAirportsAirportImporter().read_airports(airports_csv)
    engine = create_database_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        imported = await AirportReferenceRepository(session).import_airports(
            batch,
            imported_at=datetime.now(UTC),
        )
        await session.commit()

    await engine.dispose()
    return {
        "status": "imported",
        "source": imported.source,
        "rows_seen": imported.rows_seen,
        "rows_imported": imported.rows_imported,
    }


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Import OurAirports airports.csv into Flight Hunter."
    )
    parser.add_argument("--airports-csv", required=True, type=Path)
    parser.add_argument("--database-url", default=AppSettings.from_env().database_url)
    args = parser.parse_args()

    result = asyncio.run(
        run_import(
            airports_csv=args.airports_csv,
            database_url=args.database_url,
        )
    )
    print(
        " ".join(
            (
                f"status={result['status']}",
                f"rows_seen={result['rows_seen']}",
                f"rows_imported={result['rows_imported']}",
            )
        )
    )
