from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.domain.manual_confirmation import (
    ManualConfirmationStatus,
    ManualPriceConfirmation,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.search_results import ResultKind
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import ManualPriceConfirmationRepository

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 29, 21, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_manual_confirmation_repository_lists_scoped_recent_confirmations() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = ManualPriceConfirmationRepository(session)
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=1),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                target_id="obs-1",
                status=ManualConfirmationStatus.CONFIRMED,
                confirmed_at=NOW,
                price=Money(12_300_00, "RUB"),
            )
        )
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=2),
                household_id=OTHER_HOUSEHOLD_ID,
                user_id=OTHER_USER_ID,
                target_id="obs-1",
                status=ManualConfirmationStatus.PRICE_CHANGED,
                confirmed_at=NOW + timedelta(minutes=1),
                price=None,
            )
        )
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=3),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                target_id="obs-2",
                status=ManualConfirmationStatus.SOLD_OUT,
                confirmed_at=NOW + timedelta(minutes=2),
                price=None,
            )
        )
        await session.commit()

    async with session_factory() as session:
        recent = await ManualPriceConfirmationRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
        )
        target_filtered = await ManualPriceConfirmationRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            target_kind=ResultKind.BROWSER_OBSERVATION.value,
            target_id="obs-1",
        )

    assert [confirmation.target_id for confirmation in recent] == ["obs-2", "obs-1"]
    assert recent[0].status == ManualConfirmationStatus.SOLD_OUT
    assert target_filtered[0].confirmed_price == Money(12_300_00, "RUB")
    assert target_filtered[0].status == ManualConfirmationStatus.CONFIRMED


@pytest.mark.anyio
async def test_manual_confirmation_repository_lists_user_scoped_export_rows() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = ManualPriceConfirmationRepository(session)
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=11),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                target_id="obs-1",
                status=ManualConfirmationStatus.CONFIRMED,
                confirmed_at=NOW,
                price=Money(12_300_00, "RUB"),
            )
        )
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=12),
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                target_id="obs-2",
                status=ManualConfirmationStatus.SOLD_OUT,
                confirmed_at=NOW + timedelta(minutes=1),
                price=None,
            )
        )
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=13),
                household_id=HOUSEHOLD_ID,
                user_id=OTHER_USER_ID,
                target_id="other-user",
                status=ManualConfirmationStatus.PRICE_CHANGED,
                confirmed_at=NOW + timedelta(minutes=2),
                price=None,
            )
        )
        await repository.add_confirmation(
            _confirmation(
                id_value=UUID(int=14),
                household_id=OTHER_HOUSEHOLD_ID,
                user_id=USER_ID,
                target_id="other-household",
                status=ManualConfirmationStatus.CONFIRMED,
                confirmed_at=NOW + timedelta(minutes=3),
                price=Money(99_000, "RUB"),
            )
        )
        await session.commit()

    async with session_factory() as session:
        exported = await ManualPriceConfirmationRepository(session).list_for_export(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            limit=10,
        )
        limited = await ManualPriceConfirmationRepository(session).list_for_export(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            limit=1,
        )

    assert [confirmation.target_id for confirmation in exported] == ["obs-2", "obs-1"]
    assert [confirmation.target_id for confirmation in limited] == ["obs-2"]


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _confirmation(
    *,
    id_value: UUID,
    household_id: UUID,
    user_id: UUID,
    target_id: str,
    status: ManualConfirmationStatus,
    confirmed_at: datetime,
    price: Money | None,
) -> ManualPriceConfirmation:
    return ManualPriceConfirmation(
        id=id_value,
        household_id=household_id,
        user_id=user_id,
        target_kind=ResultKind.BROWSER_OBSERVATION,
        target_id=target_id,
        source_id="tutu",
        status=status,
        confirmed_price=price,
        note="checked manually",
        confirmed_at=confirmed_at,
    )
