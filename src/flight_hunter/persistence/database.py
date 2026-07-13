from __future__ import annotations

from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_database_engine(database_url: str) -> AsyncEngine:
    """Create an async engine with safe defaults for the local SQLite runtime."""

    url = make_url(database_url)
    is_sqlite = url.drivername.startswith("sqlite")
    connect_args = {"timeout": 30.0} if is_sqlite else {}
    engine = create_async_engine(database_url, connect_args=connect_args)
    if not is_sqlite:
        return engine

    file_backed = url.database not in {None, "", ":memory:"}

    @event.listens_for(engine.sync_engine, "connect")
    def configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if file_backed:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()

    return engine


def current_alembic_head(config_path: str = "alembic.ini") -> str:
    """Return the single migration head shipped with the application."""

    head = ScriptDirectory.from_config(Config(config_path)).get_current_head()
    if head is None:
        raise RuntimeError("alembic migration head is missing")
    return head
