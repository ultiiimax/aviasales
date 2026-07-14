from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.persistence.agent_repositories import (
    AgentPlanConflict,
    AgentPlanNotFound,
    AgentPlanRepository,
    NewAgentPlan,
    NewAgentPlanRevision,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import agent_search_plan_revisions_table, mapper_registry

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PLAN_ID = UUID("22222222-2222-2222-2222-222222222222")
REVISION_ID = UUID("33333333-3333-3333-3333-333333333333")
NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_plan_reads_and_successor_mutations_are_household_scoped(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "household-scope.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    async with session_factory() as session:
        repository = AgentPlanRepository(session)

        assert await repository.get_plan(OTHER_HOUSEHOLD_ID, PLAN_ID) is None
        assert await repository.get_revision(OTHER_HOUSEHOLD_ID, REVISION_ID) is None
        with pytest.raises(AgentPlanNotFound, match="agent_plan_not_found"):
            await repository.create_successor(
                household_id=OTHER_HOUSEHOLD_ID,
                source_revision_id=REVISION_ID,
                revision=_revision(
                    id_value=UUID("44444444-4444-4444-4444-444444444444"),
                    plan={"route": ["MOW", "KZN"]},
                    created_at=NOW + timedelta(minutes=1),
                ),
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_successor_is_monotonic_and_source_content_stays_immutable(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "immutable-revisions.db")
    successor_id = UUID("44444444-4444-4444-4444-444444444444")
    async with session_factory() as session:
        repository = AgentPlanRepository(session)
        initial = await repository.create_plan(_plan(), _revision())
        await session.commit()

        successor = await repository.create_successor(
            household_id=HOUSEHOLD_ID,
            source_revision_id=REVISION_ID,
            revision=_revision(
                id_value=successor_id,
                plan={"route": ["MOW", "KZN"], "filters": {"cabin": "economy"}},
                created_at=NOW + timedelta(minutes=1),
            ),
        )
        source = await repository.get_revision(HOUSEHOLD_ID, REVISION_ID)

        assert initial.revision_number == 1
        assert initial.plan_json == '{"filters":{"cabin":"economy"},"route":["MOW","LED"]}'
        assert initial.scope_snapshot_json == '{"airport_codes":["LED","MOW"]}'
        assert initial.capability_snapshot_json == '{"provider":"aviasales","version":"v1"}'
        assert initial.cost_model_snapshot_json == '{"start_attempts":1,"version":"cost-v1"}'
        assert initial.content_hash.startswith("sha256:")
        assert successor.revision_number == 2
        assert successor.content_hash != initial.content_hash
        assert source is not None
        assert source.plan_json == initial.plan_json
        assert source.state == "superseded"
        assert source.superseded_at == NOW + timedelta(minutes=1)

        with pytest.raises(AgentPlanConflict, match="agent_plan_stale"):
            await repository.create_successor(
                household_id=HOUSEHOLD_ID,
                source_revision_id=REVISION_ID,
                revision=_revision(
                    id_value=UUID("55555555-5555-5555-5555-555555555555"),
                    plan={"route": ["MOW", "AER"]},
                    created_at=NOW + timedelta(minutes=2),
                ),
            )

        revisions = await repository.list_revisions(HOUSEHOLD_ID, PLAN_ID)
        assert [revision.revision_number for revision in revisions] == [1, 2]
        await session.commit()

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_successor_compare_and_swap_has_one_winner(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "successor-cas.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def create_successor(id_value: UUID, destination: str) -> str:
        nonlocal ready
        async with session_factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            try:
                await AgentPlanRepository(session).create_successor(
                    household_id=HOUSEHOLD_ID,
                    source_revision_id=REVISION_ID,
                    revision=_revision(
                        id_value=id_value,
                        plan={"route": ["MOW", destination]},
                        created_at=NOW + timedelta(minutes=1),
                    ),
                )
                await session.commit()
            except AgentPlanConflict:
                await session.rollback()
                return "stale"
            return "winner"

    outcomes = await asyncio.gather(
        create_successor(UUID("44444444-4444-4444-4444-444444444444"), "KZN"),
        create_successor(UUID("55555555-5555-5555-5555-555555555555"), "AER"),
    )

    assert sorted(outcomes) == ["stale", "winner"]
    async with session_factory() as session:
        revisions = await AgentPlanRepository(session).list_revisions(HOUSEHOLD_ID, PLAN_ID)
        assert [revision.revision_number for revision in revisions] == [1, 2]

    await engine.dispose()


@pytest.mark.anyio
async def test_clone_idempotency_returns_the_original_cloned_revision(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "clone-idempotency.db")
    first_clone_id = UUID("44444444-4444-4444-4444-444444444444")
    async with session_factory() as session:
        repository = AgentPlanRepository(session)
        await repository.create_plan(_plan(), _revision())
        first = await repository.create_successor(
            household_id=HOUSEHOLD_ID,
            source_revision_id=REVISION_ID,
            revision=_revision(
                id_value=first_clone_id,
                plan={"route": ["MOW", "KZN"]},
                created_at=NOW + timedelta(minutes=1),
                clone_idempotency_key="clone:clarification:1",
            ),
        )
        await session.commit()

    async with session_factory() as session:
        duplicate = await AgentPlanRepository(session).create_successor(
            household_id=HOUSEHOLD_ID,
            source_revision_id=REVISION_ID,
            revision=_revision(
                id_value=UUID("55555555-5555-5555-5555-555555555555"),
                plan={"route": ["MOW", "AER"]},
                created_at=NOW + timedelta(minutes=2),
                clone_idempotency_key="clone:clarification:1",
            ),
        )

        assert duplicate.id == first.id == first_clone_id
        assert duplicate.plan_json == first.plan_json
        assert len(await AgentPlanRepository(session).list_revisions(HOUSEHOLD_ID, PLAN_ID)) == 2

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_same_key_clones_converge_to_one_revision(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "clone-idempotency-race.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def clone(id_value: UUID, destination: str) -> UUID:
        nonlocal ready
        async with session_factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            stored = await AgentPlanRepository(session).create_successor(
                household_id=HOUSEHOLD_ID,
                source_revision_id=REVISION_ID,
                revision=_revision(
                    id_value=id_value,
                    plan={"route": ["MOW", destination]},
                    created_at=NOW + timedelta(minutes=1),
                    clone_idempotency_key="clone:race:1",
                ),
            )
            await session.commit()
            return stored.id

    clone_ids = await asyncio.gather(
        clone(UUID("44444444-4444-4444-4444-444444444444"), "KZN"),
        clone(UUID("55555555-5555-5555-5555-555555555555"), "AER"),
    )

    assert clone_ids[0] == clone_ids[1]
    async with session_factory() as session:
        revisions = await AgentPlanRepository(session).list_revisions(HOUSEHOLD_ID, PLAN_ID)
        assert [revision.revision_number for revision in revisions] == [1, 2]
        assert revisions[1].clone_idempotency_key == "clone:race:1"

    await engine.dispose()


@pytest.mark.anyio
async def test_plan_and_revision_are_removed_by_external_transaction_rollback(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "plan-rollback.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.rollback()

    async with session_factory() as session:
        repository = AgentPlanRepository(session)
        assert await repository.get_plan(HOUSEHOLD_ID, PLAN_ID) is None
        assert await repository.get_revision(HOUSEHOLD_ID, REVISION_ID) is None

    await engine.dispose()


@pytest.mark.anyio
async def test_successor_is_removed_by_external_transaction_rollback(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "successor-rollback.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    async with session_factory() as session:
        await AgentPlanRepository(session).create_successor(
            household_id=HOUSEHOLD_ID,
            source_revision_id=REVISION_ID,
            revision=_revision(
                id_value=UUID("44444444-4444-4444-4444-444444444444"),
                plan={"route": ["MOW", "KZN"]},
                created_at=NOW + timedelta(minutes=1),
            ),
        )
        await session.rollback()

    async with session_factory() as session:
        revisions = await AgentPlanRepository(session).list_revisions(HOUSEHOLD_ID, PLAN_ID)
        assert len(revisions) == 1
        assert revisions[0].state == "awaiting_approval"
        assert revisions[0].superseded_at is None

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("estimated_calendar_searches", None),
        ("estimated_exact_searches", None),
        ("estimated_logical_operations", None),
        ("estimated_http_attempts", None),
        ("estimated_deadline_seconds", None),
        ("estimated_calendar_searches", -1),
        ("estimated_exact_searches", -1),
        ("estimated_logical_operations", 0),
        ("estimated_http_attempts", 0),
        ("estimated_deadline_seconds", 0),
        ("estimated_logical_operations", 4),
    ],
)
async def test_awaiting_approval_requires_complete_consistent_estimates(
    tmp_path: Path,
    field_name: str,
    invalid_value: int | None,
) -> None:
    engine, session_factory = await _session_factory(
        tmp_path,
        f"invalid-estimate-{field_name}-{invalid_value}.db",
    )
    invalid_revision = replace(_revision(), **{field_name: invalid_value})

    async with session_factory() as session:
        with pytest.raises(ValueError, match="awaiting_approval estimates"):
            await AgentPlanRepository(session).create_plan(_plan(), invalid_revision)

    await engine.dispose()


@pytest.mark.anyio
async def test_draft_revision_may_omit_estimates(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "draft-without-estimates.db")
    draft = replace(
        _revision(),
        state="draft",
        estimated_calendar_searches=None,
        estimated_exact_searches=None,
        estimated_logical_operations=None,
        estimated_http_attempts=None,
        estimated_deadline_seconds=None,
    )

    async with session_factory() as session:
        stored = await AgentPlanRepository(session).create_plan(_plan(), draft)
        await session.commit()

        assert stored.state == "draft"
        assert stored.estimated_logical_operations is None

    await engine.dispose()


@pytest.mark.anyio
async def test_database_check_rejects_incomplete_awaiting_approval_estimates(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "estimate-check.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError, match="ck_agent_plan_revision_estimates"):
            async with session.begin_nested():
                await session.execute(
                    insert(agent_search_plan_revisions_table).values(
                        id="44444444-4444-4444-4444-444444444444",
                        plan_id=str(PLAN_ID),
                        household_id=str(HOUSEHOLD_ID),
                        revision_number=2,
                        state="awaiting_approval",
                        plan_json='{"route":["MOW","KZN"]}',
                        scope_snapshot_json='{"airport_codes":["KZN","MOW"]}',
                        capability_snapshot_json='{"version":"v1"}',
                        cost_model_snapshot_json='{"version":"cost-v1"}',
                        parser_version="intent-parser-v1",
                        planner_version="agent-plan-builder-v2",
                        estimated_calendar_searches=None,
                        estimated_exact_searches=1,
                        estimated_logical_operations=1,
                        estimated_http_attempts=1,
                        estimated_deadline_seconds=60,
                        content_hash="sha256:" + "4" * 64,
                        created_at=NOW,
                        expires_at=NOW + timedelta(hours=1),
                    )
                )

    await engine.dispose()


@pytest.mark.anyio
async def test_naive_plan_and_revision_datetimes_are_rejected(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "naive-plan-time.db")
    naive = NOW.replace(tzinfo=None)

    async with session_factory() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await AgentPlanRepository(session).create_plan(
                _plan(created_at=naive),
                _revision(),
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            await AgentPlanRepository(session).create_plan(
                _plan(),
                replace(_revision(), expires_at=naive),
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_unknown_primary_key_integrity_error_is_not_reclassified(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "unknown-integrity.db")
    async with session_factory() as session:
        await AgentPlanRepository(session).create_plan(_plan(), _revision())
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError, match=r"agent_search_plans\.id"):
            await AgentPlanRepository(session).create_plan(
                _plan(),
                _revision(id_value=UUID("44444444-4444-4444-4444-444444444444")),
            )
        await session.rollback()

    await engine.dispose()


async def _session_factory(
    tmp_path: Path,
    filename: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / filename
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _plan(*, created_at: datetime = NOW) -> NewAgentPlan:
    return NewAgentPlan(
        id=PLAN_ID,
        household_id=HOUSEHOLD_ID,
        created_by_user_id=USER_ID,
        created_at=created_at,
    )


def _revision(
    *,
    id_value: UUID = REVISION_ID,
    plan: dict[str, object] | None = None,
    created_at: datetime = NOW,
    clone_idempotency_key: str | None = None,
) -> NewAgentPlanRevision:
    return NewAgentPlanRevision(
        id=id_value,
        state="awaiting_approval",
        plan=plan or {"route": ["MOW", "LED"], "filters": {"cabin": "economy"}},
        scope_snapshot={"airport_codes": ["LED", "MOW"]},
        capability_snapshot={"provider": "aviasales", "version": "v1"},
        cost_model_snapshot={"version": "cost-v1", "start_attempts": 1},
        parser_version="intent-parser-v1",
        planner_version="agent-plan-builder-v2",
        estimated_calendar_searches=1,
        estimated_exact_searches=2,
        estimated_logical_operations=3,
        estimated_http_attempts=7,
        estimated_deadline_seconds=60,
        expires_at=created_at + timedelta(hours=1),
        created_at=created_at,
        clone_idempotency_key=clone_idempotency_key,
    )
