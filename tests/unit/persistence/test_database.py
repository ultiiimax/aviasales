from pathlib import Path

import pytest

from flight_hunter.persistence.database import create_database_engine


@pytest.mark.anyio
async def test_file_sqlite_engine_enables_local_safety_pragmas(tmp_path: Path) -> None:
    database_path = tmp_path / "flight-hunter.sqlite"
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")

    async with engine.connect() as connection:
        journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
        busy_timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
        foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
        synchronous = (await connection.exec_driver_sql("PRAGMA synchronous")).scalar_one()

    await engine.dispose()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 30_000
    assert foreign_keys == 1
    assert synchronous == 1


@pytest.mark.anyio
async def test_memory_sqlite_engine_keeps_compatible_journal_mode() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")

    async with engine.connect() as connection:
        journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
        foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()

    await engine.dispose()

    assert str(journal_mode).lower() == "memory"
    assert foreign_keys == 1
