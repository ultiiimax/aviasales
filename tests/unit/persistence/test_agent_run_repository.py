from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.persistence.agent_repositories import (
    AgentPlanConflict,
    AgentPlanNotFound,
    AgentPlanRepository,
    AgentPlanRunRecord,
    AgentRunRepository,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import (
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
    mapper_registry,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PLAN_ID = UUID("22222222-2222-2222-2222-222222222222")
REVISION_ID = UUID("33333333-3333-3333-3333-333333333333")
APPROVAL_ID = UUID("44444444-4444-4444-4444-444444444444")
RUN_ID = UUID("55555555-5555-5555-5555-555555555555")
NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_approval_and_execution_are_household_scoped(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "run-household-scope.db")
    async with session_factory() as session:
        await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval())
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        with pytest.raises(AgentPlanNotFound, match="agent_plan_not_found"):
            await repository.create_approval(
                _approval(
                    id_value=UUID("66666666-6666-6666-6666-666666666666"),
                    household_id=OTHER_HOUSEHOLD_ID,
                )
            )
        with pytest.raises(AgentPlanNotFound, match="agent_plan_not_found"):
            await repository.execute(
                household_id=OTHER_HOUSEHOLD_ID,
                approval_id=APPROVAL_ID,
                run=_run(),
            )

        assert await repository.get_run(OTHER_HOUSEHOLD_ID, RUN_ID) is None
        assert await repository.list_runs(HOUSEHOLD_ID, PLAN_ID) == ()

    await engine.dispose()


@pytest.mark.anyio
async def test_execute_idempotency_returns_original_run_and_consumes_snapshot(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "execute-idempotency.db")
    async with session_factory() as session:
        await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval())
        first = await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        duplicate = await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(id_value=UUID("66666666-6666-6666-6666-666666666666")),
        )
        approval = await repository.get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        revision = await AgentPlanRepository(session).get_revision(HOUSEHOLD_ID, REVISION_ID)

        assert duplicate.id == first.id == RUN_ID
        assert duplicate.execute_idempotency_key == "execute:plan:1"
        assert approval is not None
        assert approval.run_id == RUN_ID
        assert approval.consumed_at == NOW
        assert revision is not None
        assert revision.state == "consumed"
        assert revision.consumed_at == NOW
        assert len(await repository.list_runs(HOUSEHOLD_ID, PLAN_ID)) == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_plan_has_only_one_active_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "one-active-run.db")
    second_approval_id = UUID("66666666-6666-6666-6666-666666666666")
    async with session_factory() as session:
        await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval())
        await repository.create_approval(_approval(id_value=second_approval_id))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        with pytest.raises(AgentPlanConflict, match="agent_plan_active_run"):
            await repository.execute(
                household_id=HOUSEHOLD_ID,
                approval_id=second_approval_id,
                run=_run(
                    id_value=UUID("77777777-7777-7777-7777-777777777777"),
                    execute_idempotency_key="execute:plan:2",
                ),
            )
        await session.rollback()

    async with session_factory() as session:
        runs = await AgentRunRepository(session).list_runs(HOUSEHOLD_ID, PLAN_ID)
        assert [run.id for run in runs] == [RUN_ID]

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_active_run_race_has_typed_loser_and_allows_terminal_history(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "active-run-race.db")
    second_approval_id = UUID("66666666-6666-6666-6666-666666666666")
    second_run_id = UUID("77777777-7777-7777-7777-777777777777")
    async with session_factory() as session:
        await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval())
        await repository.create_approval(_approval(id_value=second_approval_id))
        await session.commit()

    gate = _RaceGate()

    async def race_execute(
        approval_id: UUID,
        run: NewAgentPlanRun,
    ) -> tuple[str, str, UUID, UUID]:
        async with session_factory() as session:
            repository = _RacingAgentRunRepository(session, gate)
            try:
                stored = await repository.execute(
                    household_id=HOUSEHOLD_ID,
                    approval_id=approval_id,
                    run=run,
                )
                await session.commit()
            except AgentPlanConflict as error:
                await session.rollback()
                return "conflict", error.code, run.id, approval_id
            return "winner", str(stored.id), run.id, approval_id

    outcomes = await asyncio.gather(
        race_execute(APPROVAL_ID, _run()),
        race_execute(
            second_approval_id,
            _run(
                id_value=second_run_id,
                execute_idempotency_key="execute:plan:2",
            ),
        ),
    )

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "winner"]
    loser = next(outcome for outcome in outcomes if outcome[0] == "conflict")
    winner = next(outcome for outcome in outcomes if outcome[0] == "winner")
    assert loser[1] == "agent_plan_active_run"

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=winner[2],
            status="succeeded",
            changed_at=NOW + timedelta(minutes=1),
        )
        await session.execute(
            insert(agent_plan_runs_table).values(
                id=str(loser[2]),
                household_id=str(HOUSEHOLD_ID),
                plan_id=str(PLAN_ID),
                revision_id=str(REVISION_ID),
                approval_id=str(loser[3]),
                execute_idempotency_key=(
                    "execute:plan:1" if loser[2] == RUN_ID else "execute:plan:2"
                ),
                status="failed",
                created_at=NOW + timedelta(minutes=2),
                deadline_at=NOW + timedelta(minutes=12),
                completed_at=NOW + timedelta(minutes=3),
            )
        )
        await session.execute(
            update(agent_plan_execution_approvals_table)
            .where(agent_plan_execution_approvals_table.c.id == str(loser[3]))
            .where(agent_plan_execution_approvals_table.c.household_id == str(HOUSEHOLD_ID))
            .values(run_id=str(loser[2]), consumed_at=NOW + timedelta(minutes=2))
        )
        await session.commit()

    async with session_factory() as session:
        runs = await AgentRunRepository(session).list_runs(HOUSEHOLD_ID, PLAN_ID)
        assert {run.status for run in runs} == {"succeeded", "failed"}

    await engine.dispose()


@pytest.mark.anyio
async def test_consumed_approval_cannot_bind_a_second_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "approval-consumption.db")
    async with session_factory() as session:
        await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval())
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="succeeded",
            changed_at=NOW + timedelta(minutes=1),
        )
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        with pytest.raises(AgentPlanConflict, match="agent_approval_consumed"):
            await repository.execute(
                household_id=HOUSEHOLD_ID,
                approval_id=APPROVAL_ID,
                run=_run(
                    id_value=UUID("66666666-6666-6666-6666-666666666666"),
                    execute_idempotency_key="execute:plan:2",
                    created_at=NOW + timedelta(minutes=2),
                ),
            )
        await session.rollback()

    async with session_factory() as session:
        assert len(await AgentRunRepository(session).list_runs(HOUSEHOLD_ID, PLAN_ID)) == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_latest_run_orders_by_created_at_then_id(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "latest-run.db")
    higher_plan_id = UUID("77777777-7777-7777-7777-777777777777")
    higher_revision_id = UUID("88888888-8888-8888-8888-888888888888")
    higher_approval_id = UUID("99999999-9999-9999-9999-999999999999")
    higher_run_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    async with session_factory() as session:
        await _create_plan(session)
        await _create_plan(
            session,
            plan_id=higher_plan_id,
            revision_id=higher_revision_id,
        )
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval())
        await repository.create_approval(
            _approval(
                id_value=higher_approval_id,
                revision_id=higher_revision_id,
            )
        )
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=higher_approval_id,
            run=_run(
                id_value=higher_run_id,
                execute_idempotency_key="execute:plan:2",
            ),
        )
        await session.commit()

    async with session_factory() as session:
        latest = await AgentRunRepository(session).get_latest_run(HOUSEHOLD_ID)

        assert latest is not None
        assert latest.id == higher_run_id
        assert latest.created_at == NOW

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


async def _create_plan(
    session: AsyncSession,
    *,
    plan_id: UUID = PLAN_ID,
    revision_id: UUID = REVISION_ID,
) -> None:
    await AgentPlanRepository(session).create_plan(
        NewAgentPlan(
            id=plan_id,
            household_id=HOUSEHOLD_ID,
            created_by_user_id=USER_ID,
            created_at=NOW,
        ),
        NewAgentPlanRevision(
            id=revision_id,
            state="awaiting_approval",
            plan={"route": ["MOW", "LED"]},
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
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW,
        ),
    )


def _approval(
    *,
    id_value: UUID = APPROVAL_ID,
    household_id: UUID = HOUSEHOLD_ID,
    revision_id: UUID = REVISION_ID,
) -> NewAgentPlanApproval:
    return NewAgentPlanApproval(
        id=id_value,
        household_id=household_id,
        revision_id=revision_id,
        approved_by_user_id=USER_ID,
        approved_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=30),
    )


def _run(
    *,
    id_value: UUID = RUN_ID,
    execute_idempotency_key: str = "execute:plan:1",
    created_at: datetime = NOW,
) -> NewAgentPlanRun:
    return NewAgentPlanRun(
        id=id_value,
        execute_idempotency_key=execute_idempotency_key,
        created_at=created_at,
        deadline_at=created_at + timedelta(minutes=10),
    )


class _RaceGate:
    def __init__(self) -> None:
        self._ready = 0
        self._lock = asyncio.Lock()
        self._start = asyncio.Event()

    async def wait(self) -> None:
        async with self._lock:
            self._ready += 1
            if self._ready == 2:
                self._start.set()
        await self._start.wait()


class _RacingAgentRunRepository(AgentRunRepository):
    def __init__(self, session: AsyncSession, gate: _RaceGate) -> None:
        super().__init__(session)
        self._gate = gate
        self._precheck_gated = False

    async def _get_active_run(
        self,
        household_id: UUID,
        plan_id: UUID,
    ) -> AgentPlanRunRecord | None:
        active = await super()._get_active_run(household_id, plan_id)
        if active is None and not self._precheck_gated:
            self._precheck_gated = True
            await self._gate.wait()
        return active
