from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.domain.auth import HouseholdRole, token_hash
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import IdentityRepository

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
INVITATION_ID = UUID("aaaaaaaa-0000-0000-0000-000000000002")
SESSION_ID = UUID("aaaaaaaa-0000-0000-0000-000000000003")
NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_identity_repository_round_trips_invitation_and_active_session() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = IdentityRepository(session)
        await repository.add_household(
            household_id=HOUSEHOLD_ID,
            name="Family",
            created_at=NOW,
        )
        await repository.add_invitation(
            invitation_id=INVITATION_ID,
            household_id=HOUSEHOLD_ID,
            role=HouseholdRole.OWNER,
            code_hash=token_hash("invite-token"),
            recipient_label="owner",
            created_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )
        await repository.add_user(user_id=USER_ID, display_name="Kiwun", created_at=NOW)
        await repository.add_membership(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            role=HouseholdRole.OWNER,
            created_at=NOW,
        )
        await repository.add_session(
            session_id=SESSION_ID,
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            token_hash=token_hash("session-token"),
            created_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        await session.commit()

    async with session_factory() as session:
        repository = IdentityRepository(session)
        invitation = await repository.invitation_by_code_hash(token_hash("invite-token"))
        auth_session = await repository.session_by_token_hash(
            token_hash=token_hash("session-token"),
            now=NOW,
        )
        expired_session = await repository.session_by_token_hash(
            token_hash=token_hash("session-token"),
            now=NOW + timedelta(days=31),
        )

    assert invitation is not None
    assert invitation.household_id == HOUSEHOLD_ID
    assert invitation.role == HouseholdRole.OWNER
    assert auth_session is not None
    assert auth_session.household_id == HOUSEHOLD_ID
    assert auth_session.user_id == USER_ID
    assert auth_session.role == HouseholdRole.OWNER
    assert expired_session is None


@pytest.mark.anyio
async def test_identity_repository_revokes_sessions_and_disables_membership() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = IdentityRepository(session)
        await repository.add_household(
            household_id=HOUSEHOLD_ID,
            name="Family",
            created_at=NOW,
        )
        await repository.add_user(user_id=USER_ID, display_name="Kiwun", created_at=NOW)
        await repository.add_membership(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            role=HouseholdRole.OWNER,
            created_at=NOW,
        )
        await repository.add_session(
            session_id=SESSION_ID,
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            token_hash=token_hash("session-token"),
            created_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )
        await session.commit()

    async with session_factory() as session:
        repository = IdentityRepository(session)
        revoked = await repository.revoke_sessions(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            revoked_at=NOW + timedelta(minutes=1),
        )
        disabled = await repository.disable_membership(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            disabled_at=NOW + timedelta(minutes=1),
        )
        replay_revoked = await repository.revoke_sessions(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            revoked_at=NOW + timedelta(minutes=2),
        )
        replay_disabled = await repository.disable_membership(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            disabled_at=NOW + timedelta(minutes=2),
        )
        await session.commit()

    async with session_factory() as session:
        auth_session = await IdentityRepository(session).session_by_token_hash(
            token_hash=token_hash("session-token"),
            now=NOW + timedelta(minutes=3),
        )

    assert revoked == 1
    assert disabled
    assert replay_revoked == 0
    assert not replay_disabled
    assert auth_session is None


@pytest.mark.anyio
async def test_active_owner_identities_are_enabled_deterministic_and_bounded() -> None:
    session_factory = await _session_factory()
    identities = (
        (
            UUID("10000000-0000-0000-0000-000000000001"),
            UUID("20000000-0000-0000-0000-000000000001"),
            NOW,
        ),
        (
            UUID("10000000-0000-0000-0000-000000000002"),
            UUID("20000000-0000-0000-0000-000000000002"),
            NOW + timedelta(seconds=1),
        ),
        (
            UUID("10000000-0000-0000-0000-000000000003"),
            UUID("20000000-0000-0000-0000-000000000003"),
            NOW + timedelta(seconds=2),
        ),
        (
            UUID("10000000-0000-0000-0000-000000000004"),
            UUID("20000000-0000-0000-0000-000000000004"),
            NOW - timedelta(seconds=1),
        ),
    )
    async with session_factory() as session:
        repository = IdentityRepository(session)
        for household_id, user_id, created_at in identities:
            await repository.add_household(
                household_id=household_id,
                name=f"Family {household_id}",
                created_at=created_at,
            )
            await repository.add_user(
                user_id=user_id,
                display_name=f"Owner {user_id}",
                created_at=created_at,
            )
            await repository.add_membership(
                household_id=household_id,
                user_id=user_id,
                role=HouseholdRole.OWNER,
                created_at=created_at,
            )
        disabled = await repository.disable_membership(
            household_id=identities[3][0],
            user_id=identities[3][1],
            disabled_at=NOW,
        )
        await session.commit()

    async with session_factory() as session:
        owners = await IdentityRepository(session).active_owner_identities(limit=2)

    assert disabled
    assert [(owner.household_id, owner.user_id) for owner in owners] == [
        identities[0][:2],
        identities[1][:2],
    ]


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)
