from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.domain.money import Money
from flight_hunter.domain.search_results import Confidence, DealCandidate
from flight_hunter.persistence.models import mapper_registry
from flight_hunter.persistence.repositories import DealCandidateRepository, NewDealCandidate

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
OTHER_USER_ID = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_deal_candidate_repository_lists_only_scoped_unexpired_candidates() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealCandidateRepository(session)
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=1),
                user_id=USER_ID,
                title="Fresh owner deal",
                discovered_at=NOW,
                expires_at=NOW + timedelta(hours=2),
            )
        )
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=2),
                user_id=USER_ID,
                title="Expired owner deal",
                discovered_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(seconds=1),
            )
        )
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=3),
                user_id=OTHER_USER_ID,
                title="Other user deal",
                discovered_at=NOW + timedelta(minutes=2),
                expires_at=NOW + timedelta(hours=2),
            )
        )
        await session.commit()

    async with session_factory() as session:
        candidates = await DealCandidateRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert len(candidates) == 1
    assert candidates[0].title == "Fresh owner deal"
    assert candidates[0].extracted_price == Money(1_842_000, "RUB")
    assert candidates[0].requires_manual_verification is True
    assert candidates[0].expires_at == NOW + timedelta(hours=2)


@pytest.mark.anyio
async def test_deal_candidate_repository_cleans_expired_candidates() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealCandidateRepository(session)
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=1),
                user_id=USER_ID,
                title="Expired deal",
                discovered_at=NOW - timedelta(hours=3),
                expires_at=NOW - timedelta(hours=1),
            )
        )
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=2),
                user_id=USER_ID,
                title="Fresh deal",
                discovered_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(hours=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        deleted = await DealCandidateRepository(session).cleanup_expired(now=NOW)
        await session.commit()

    async with session_factory() as session:
        candidates = await DealCandidateRepository(session).list_recent(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            search_id="sha256:search",
            now=NOW,
        )

    assert deleted == 1
    assert [candidate.title for candidate in candidates] == ["Fresh deal"]


@pytest.mark.anyio
async def test_deal_candidate_repository_lists_user_scoped_export_rows() -> None:
    session_factory = await _session_factory()
    async with session_factory() as session:
        repository = DealCandidateRepository(session)
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=11),
                user_id=USER_ID,
                title="Fresh owner deal",
                discovered_at=NOW,
                expires_at=NOW + timedelta(hours=2),
            )
        )
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=12),
                user_id=USER_ID,
                title="Expired but retained owner deal",
                discovered_at=NOW - timedelta(hours=2),
                expires_at=NOW - timedelta(minutes=1),
            )
        )
        await repository.add_candidate(
            _new_candidate(
                id_value=UUID(int=13),
                user_id=OTHER_USER_ID,
                title="Other user deal",
                discovered_at=NOW + timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=2),
            )
        )
        await session.commit()

    async with session_factory() as session:
        exported = await DealCandidateRepository(session).list_for_export(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            limit=10,
        )
        limited = await DealCandidateRepository(session).list_for_export(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            limit=1,
        )

    assert [candidate.title for candidate in exported] == [
        "Fresh owner deal",
        "Expired but retained owner deal",
    ]
    assert [candidate.title for candidate in limited] == ["Fresh owner deal"]


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _new_candidate(
    *,
    id_value: UUID,
    user_id: UUID,
    title: str,
    discovered_at: datetime,
    expires_at: datetime,
) -> NewDealCandidate:
    return NewDealCandidate(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        user_id=user_id,
        search_id="sha256:search",
        candidate=DealCandidate(
            source_id="deal_discovery",
            url=f"https://example.com/{id_value.int}",
            title=title,
            summary_ru="Manual verification required.",
            extracted_price=Money(1_842_000, "RUB"),
            extracted_origin="MOW",
            extracted_destination="IST",
            extracted_date_window="2026-09-10",
            confidence=Confidence.MEDIUM,
            discovered_at=discovered_at,
            requires_manual_verification=True,
            expires_at=expires_at,
        ),
        expires_at=expires_at,
    )
