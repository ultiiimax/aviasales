from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.domain.search_results import BrowserObservedOffer
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import BrowserObservedOfferRepository
from flight_hunter.providers.personal_observer.cli import main

FIXTURE = Path("tests/fixtures/browser/tutu/search_result_source_specific.html")
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_observe_cli_prints_sanitized_fixture_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-observe",
            "--source",
            "tutu",
            "--origin",
            "MOW",
            "--destination",
            "IST",
            "--depart",
            "2026-09-10",
            "--return-date",
            "2026-09-20",
            "--fixture-html",
            str(FIXTURE),
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["source_id"] == "tutu"
    assert body["confidence"] == "medium"
    assert body["offers"][0]["amount_minor"] == 1_842_000
    assert "html" not in body


def test_observe_cli_returns_typed_error_without_fixture_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-observe",
            "--source",
            "tutu",
            "--origin",
            "MOW",
            "--destination",
            "IST",
            "--depart",
            "2026-09-10",
            "--return-date",
            "2026-09-20",
            "--interactive",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    body = json.loads(capsys.readouterr().out)
    assert body["code"] == "observer_disabled"


def test_observe_cli_can_persist_normalized_fixture_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "observations.db"
    database_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    asyncio.run(_create_schema(database_url))
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "www.tutu.ru,tutu.ru,avia.tutu.ru")
    monkeypatch.setattr(
        "sys.argv",
        [
            "flight-hunter-observe",
            "--source",
            "tutu",
            "--origin",
            "MOW",
            "--destination",
            "IST",
            "--depart",
            "2026-09-10",
            "--return-date",
            "2026-09-20",
            "--fixture-html",
            str(FIXTURE),
            "--persist",
            "--household-id",
            str(HOUSEHOLD_ID),
            "--user-id",
            str(USER_ID),
            "--search-id",
            "sha256:test-search",
            "--database-url",
            database_url,
        ],
    )

    main()

    body = json.loads(capsys.readouterr().out)
    assert body["persisted_count"] == 1

    stored = asyncio.run(
        _list_stored(
            database_url=database_url,
            now=datetime.fromisoformat(body["offers"][0]["observed_at"]),
        )
    )

    assert len(stored) == 1
    assert stored[0].source_id == "tutu"


async def _create_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    await engine.dispose()


async def _list_stored(*, database_url: str, now: datetime) -> tuple[BrowserObservedOffer, ...]:
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        stored = await BrowserObservedOfferRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:test-search",
            now=now,
        )
    await engine.dispose()
    return stored
