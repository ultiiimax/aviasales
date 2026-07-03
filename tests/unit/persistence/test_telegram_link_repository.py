from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import NewTelegramLinkCode, TelegramLinkRepository

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
NOW = datetime(2026, 6, 29, 16, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_telegram_link_repository_revokes_account_for_user() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = TelegramLinkRepository(session)
        await repository.add_code(
            NewTelegramLinkCode(
                code="ABC123",
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                created_at=NOW,
                expires_at=NOW + timedelta(minutes=5),
            )
        )
        consumed = await repository.consume_code(
            code="ABC123",
            telegram_user_id=12345,
            chat_id=98765,
            now=NOW + timedelta(minutes=1),
        )
        await session.commit()

    assert consumed is not None

    async with session_factory() as session:
        repository = TelegramLinkRepository(session)
        revoked = await repository.revoke_account_for_user(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            revoked_at=NOW + timedelta(minutes=2),
        )
        replay = await repository.revoke_account_for_user(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            revoked_at=NOW + timedelta(minutes=3),
        )
        by_user = await repository.get_account_for_user(USER_ID)
        by_telegram = await repository.get_account_for_telegram_user(12345)
        await session.commit()

    assert revoked
    assert not replay
    assert by_user is None
    assert by_telegram is None


async def _session_factory() -> async_sessionmaker:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
