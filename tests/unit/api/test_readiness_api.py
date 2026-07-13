from dataclasses import replace
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.persistence.database import create_database_engine


def test_readyz_accepts_database_at_current_migration_head(tmp_path: Path) -> None:
    database_url = _migrated_database_url(tmp_path / "ready.sqlite")
    client = TestClient(
        create_app(
            watch_session_factory=_session_factory(database_url),
            settings=replace(AppSettings.from_env(), database_url=database_url),
        )
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_readyz_rejects_database_without_migration_revision(tmp_path: Path) -> None:
    database_url = f"sqlite+aiosqlite:///{(tmp_path / 'empty.sqlite').as_posix()}"
    client = TestClient(
        create_app(
            watch_session_factory=_session_factory(database_url),
            settings=replace(AppSettings.from_env(), database_url=database_url),
        )
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "code": "migration_pending",
        "message": "database migration is pending",
    }


def test_readyz_rejects_unopenable_database(tmp_path: Path) -> None:
    database_url = (
        f"sqlite+aiosqlite:///{(tmp_path / 'missing-directory' / 'db.sqlite').as_posix()}"
    )
    client = TestClient(
        create_app(
            watch_session_factory=_session_factory(database_url),
            settings=replace(AppSettings.from_env(), database_url=database_url),
        )
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json() == {
        "code": "database_unavailable",
        "message": "database is unavailable",
    }


def _migrated_database_url(database_path: Path) -> str:
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


def _session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_database_engine(database_url), expire_on_commit=False)
