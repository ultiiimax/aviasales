from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.persistence.agent_repositories import (
    AgentIntegrityConstraint,
    AgentPlanApprovalSnapshot,
    AgentPlanConflict,
    AgentPlanNotFound,
    AgentPlanRepository,
    AgentPlanRevisionRecord,
    AgentPlanRunRecord,
    AgentRunRepository,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    _acquire_sqlite_write_transaction,
    classify_agent_integrity_constraint,
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
SESSION_ID = UUID("12121212-1212-1212-1212-121212121212")
NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_approval_and_execution_are_household_scoped(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "run-household-scope.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        with pytest.raises(AgentPlanNotFound, match="agent_plan_not_found"):
            await repository.create_approval(
                _approval(
                    revision.content_hash,
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
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
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
async def test_approval_snapshot_roundtrips_canonical_immutable_values(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "approval-snapshot.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        stored = await AgentRunRepository(session).create_approval(
            _approval(
                revision.content_hash,
                approved_budget={
                    "logical_operations": 3,
                    "deadline_seconds": 60,
                    "http_attempts": 7,
                },
                approved_strategies=("direct", "self_transfer"),
                risk_warning_versions={
                    "new_future_warning": "warning-v2",
                    "hidden_city": "hidden-city-warning-v3",
                },
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = await AgentRunRepository(session).get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        raw = (
            await session.execute(
                select(
                    agent_plan_execution_approvals_table.c.revision_content_hash,
                    agent_plan_execution_approvals_table.c.approved_by_session_id,
                    agent_plan_execution_approvals_table.c.approved_budget_json,
                    agent_plan_execution_approvals_table.c.approved_strategies_json,
                    agent_plan_execution_approvals_table.c.risk_warning_versions_json,
                ).where(agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID))
            )
        ).one()

        assert stored is not None
        assert stored.snapshot.revision_content_hash == revision.content_hash
        assert stored.snapshot.approved_by_session_id == SESSION_ID
        assert stored.snapshot.approved_budget == {
            "deadline_seconds": 60,
            "http_attempts": 7,
            "logical_operations": 3,
        }
        assert stored.snapshot.approved_strategies == ("direct", "self_transfer")
        assert stored.snapshot.risk_warning_versions == {
            "hidden_city": "hidden-city-warning-v3",
            "new_future_warning": "warning-v2",
        }
        with pytest.raises(FrozenInstanceError):
            stored.snapshot.revision_content_hash = "sha256:changed"  # type: ignore[misc]
        assert raw.revision_content_hash == revision.content_hash
        assert raw.approved_by_session_id == str(SESSION_ID)
        assert raw.approved_budget_json == (
            '{"deadline_seconds":60,"http_attempts":7,"logical_operations":3}'
        )
        assert raw.approved_strategies_json == '["direct","self_transfer"]'
        assert raw.risk_warning_versions_json == (
            '{"hidden_city":"hidden-city-warning-v3","new_future_warning":"warning-v2"}'
        )

    await engine.dispose()


@pytest.mark.anyio
async def test_approval_snapshot_is_recursively_defensive_and_immutable(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "deep-approval-snapshot.db")
    attempts: list[object] = [7, {"deadline_seconds": 60}]
    provider_limits: dict[str, object] = {"attempts": attempts}
    budget: dict[str, object] = {
        "logical_operations": 3,
        "provider_limits": provider_limits,
    }
    strategies = ["direct", "self_transfer"]
    warning_versions = {"hidden_city": "hidden-city-warning-v3"}

    async with session_factory() as session:
        revision = await _create_plan(session)
        approval = _approval(
            revision.content_hash,
            approved_budget=budget,
            approved_strategies=cast(tuple[str, ...], strategies),
            risk_warning_versions=warning_versions,
        )
        created = await AgentRunRepository(session).create_approval(approval)

        attempts.append(99)
        provider_limits["new_limit"] = 10
        strategies.append("hidden_city")
        warning_versions["hidden_city"] = "mutated"

        assert approval.snapshot.approved_budget == {
            "logical_operations": 3,
            "provider_limits": {"attempts": (7, {"deadline_seconds": 60})},
        }
        assert approval.snapshot.approved_strategies == ("direct", "self_transfer")
        assert approval.snapshot.risk_warning_versions == {"hidden_city": "hidden-city-warning-v3"}
        assert created.snapshot.approved_budget == {
            "logical_operations": 3,
            "provider_limits": {"attempts": (7, {"deadline_seconds": 60})},
        }
        assert created.snapshot.approved_strategies == ("direct", "self_transfer")
        assert created.snapshot.risk_warning_versions == {"hidden_city": "hidden-city-warning-v3"}
        await session.commit()

    async with session_factory() as session:
        stored = await AgentRunRepository(session).get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        raw_budget = (
            await session.execute(
                select(agent_plan_execution_approvals_table.c.approved_budget_json).where(
                    agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID)
                )
            )
        ).scalar_one()

        assert stored is not None
        nested_limits = stored.snapshot.approved_budget["provider_limits"]
        assert isinstance(nested_limits, Mapping)
        nested_attempts = nested_limits["attempts"]
        assert nested_attempts == (7, {"deadline_seconds": 60})
        with pytest.raises(TypeError):
            nested_limits["new_limit"] = 10  # type: ignore[index]
        assert isinstance(nested_attempts, tuple)
        with pytest.raises(AttributeError):
            nested_attempts.append(99)  # type: ignore[attr-defined]
        nested_deadline = nested_attempts[1]
        assert isinstance(nested_deadline, Mapping)
        with pytest.raises(TypeError):
            nested_deadline["deadline_seconds"] = 1  # type: ignore[index]
        assert raw_budget == (
            '{"logical_operations":3,"provider_limits":{"attempts":[7,{"deadline_seconds":60}]}}'
        )

    await engine.dispose()


@pytest.mark.anyio
async def test_execute_rejects_approval_snapshot_for_different_revision_content(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "approval-hash-mismatch.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.execute(
            update(agent_plan_execution_approvals_table)
            .where(agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID))
            .where(agent_plan_execution_approvals_table.c.household_id == str(HOUSEHOLD_ID))
            .values(revision_content_hash="sha256:" + "f" * 64)
        )

        with pytest.raises(AgentPlanConflict, match="agent_approval_snapshot_mismatch"):
            await AgentRunRepository(session).execute(
                household_id=HOUSEHOLD_ID,
                approval_id=APPROVAL_ID,
                run=_run(),
            )

        assert await AgentRunRepository(session).list_runs(HOUSEHOLD_ID, PLAN_ID) == ()

    await engine.dispose()


@pytest.mark.anyio
async def test_approval_run_and_consumption_are_removed_by_external_rollback(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "execute-rollback.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await session.commit()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.rollback()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        stored_revision = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            REVISION_ID,
        )
        assert await repository.get_approval(HOUSEHOLD_ID, APPROVAL_ID) is None
        assert await repository.list_runs(HOUSEHOLD_ID, PLAN_ID) == ()
        assert stored_revision is not None
        assert stored_revision.state == "awaiting_approval"
        assert stored_revision.consumed_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_precommitted_approval_execute_is_removed_by_external_rollback(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(
        tmp_path,
        "precommitted-execute-rollback.db",
    )
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.commit()

    async with session_factory() as session:
        await AgentRunRepository(session).execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.rollback()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        approval = await repository.get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        revision = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            REVISION_ID,
        )
        assert approval is not None
        assert approval.run_id is None
        assert approval.consumed_at is None
        assert revision is not None
        assert revision.state == "awaiting_approval"
        assert revision.consumed_at is None
        assert await repository.list_runs(HOUSEHOLD_ID, PLAN_ID) == ()

    await engine.dispose()


@pytest.mark.anyio
async def test_sqlite_execute_rejects_caller_savepoint_before_mutation(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "execute-savepoint.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.commit()

    async with session_factory() as session:
        caller_savepoint = await session.begin_nested()
        with pytest.raises(AgentPlanConflict) as captured:
            await AgentRunRepository(session).execute(
                household_id=HOUSEHOLD_ID,
                approval_id=APPROVAL_ID,
                run=_run(),
            )
        assert captured.value.code == "agent_sqlite_nested_transaction_unsupported"
        await caller_savepoint.rollback()
        await session.rollback()

    async with session_factory() as session:
        repository = AgentRunRepository(session)
        approval = await repository.get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        revision = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            REVISION_ID,
        )
        assert approval is not None
        assert approval.run_id is None
        assert approval.consumed_at is None
        assert revision is not None
        assert revision.state == "awaiting_approval"
        assert revision.consumed_at is None
        assert await repository.list_runs(HOUSEHOLD_ID, PLAN_ID) == ()

    async with session_factory() as session:
        created = await AgentRunRepository(session).execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.commit()
        assert created.id == RUN_ID

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_same_key_executes_converge_to_original_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "execute-idempotency-race.db")
    second_approval_id = UUID("66666666-6666-6666-6666-666666666666")
    second_run_id = UUID("77777777-7777-7777-7777-777777777777")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.create_approval(
            _approval(revision.content_hash, id_value=second_approval_id)
        )
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def execute(approval_id: UUID, run: NewAgentPlanRun) -> UUID:
        nonlocal ready
        async with session_factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            stored = await AgentRunRepository(session).execute(
                household_id=HOUSEHOLD_ID,
                approval_id=approval_id,
                run=run,
            )
            await session.commit()
            return stored.id

    run_ids = await asyncio.gather(
        execute(APPROVAL_ID, _run(execute_idempotency_key="execute:race:1")),
        execute(
            second_approval_id,
            _run(
                id_value=second_run_id,
                execute_idempotency_key="execute:race:1",
            ),
        ),
    )

    assert run_ids[0] == run_ids[1]
    async with session_factory() as session:
        runs = await AgentRunRepository(session).list_runs(HOUSEHOLD_ID, PLAN_ID)
        assert len(runs) == 1
        assert runs[0].execute_idempotency_key == "execute:race:1"

    await engine.dispose()


@pytest.mark.anyio
async def test_non_utc_writes_roundtrip_as_utc_across_the_lifecycle(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "utc-roundtrip.db")
    local_now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    async with session_factory() as session:
        revision = await _create_plan(session, now=local_now)
        repository = AgentRunRepository(session)
        approval = await repository.create_approval(
            _approval(
                revision.content_hash,
                approved_at=local_now + timedelta(seconds=10),
                expires_at=local_now + timedelta(minutes=30),
            )
        )
        run = await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(created_at=local_now + timedelta(minutes=1)),
        )
        running = await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=local_now + timedelta(minutes=2),
        )
        completed = await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="completed",
            changed_at=local_now + timedelta(minutes=3),
        )
        plan = await AgentPlanRepository(session).get_plan(HOUSEHOLD_ID, PLAN_ID)
        consumed_revision = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            REVISION_ID,
        )

        assert plan is not None
        assert plan.created_at == local_now.astimezone(UTC)
        assert revision.created_at == local_now.astimezone(UTC)
        assert revision.expires_at == (local_now + timedelta(hours=1)).astimezone(UTC)
        assert approval.approved_at == (local_now + timedelta(seconds=10)).astimezone(UTC)
        assert approval.expires_at == (local_now + timedelta(minutes=30)).astimezone(UTC)
        assert run.created_at == (local_now + timedelta(minutes=1)).astimezone(UTC)
        assert run.deadline_at == (local_now + timedelta(minutes=11)).astimezone(UTC)
        assert running.started_at == (local_now + timedelta(minutes=2)).astimezone(UTC)
        assert completed.finished_at == (local_now + timedelta(minutes=3)).astimezone(UTC)
        assert consumed_revision is not None
        assert consumed_revision.consumed_at == (local_now + timedelta(minutes=1)).astimezone(UTC)
        consumed_approval = await repository.get_approval(HOUSEHOLD_ID, APPROVAL_ID)
        assert consumed_approval is not None
        assert consumed_approval.consumed_at == (local_now + timedelta(minutes=1)).astimezone(UTC)

    await engine.dispose()


@pytest.mark.anyio
async def test_non_utc_cancel_timestamps_roundtrip_as_utc(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "utc-cancel-roundtrip.db")
    local_now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    async with session_factory() as session:
        revision = await _create_plan(session, now=local_now)
        repository = AgentRunRepository(session)
        await repository.create_approval(
            _approval(
                revision.content_hash,
                approved_at=local_now + timedelta(seconds=10),
                expires_at=local_now + timedelta(minutes=30),
            )
        )
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(created_at=local_now + timedelta(minutes=1)),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancel_requested",
            changed_at=local_now + timedelta(minutes=2),
        )
        cancelled = await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancelled",
            changed_at=local_now + timedelta(minutes=3),
        )

        assert cancelled.cancel_requested_at == (local_now + timedelta(minutes=2)).astimezone(UTC)
        assert cancelled.finished_at == (local_now + timedelta(minutes=3)).astimezone(UTC)

    await engine.dispose()


@pytest.mark.anyio
async def test_naive_approval_run_and_transition_datetimes_are_rejected(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "naive-run-time.db")
    naive = NOW.replace(tzinfo=None)
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.create_approval(_approval(revision.content_hash, approved_at=naive))
        await repository.create_approval(_approval(revision.content_hash))
        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.execute(
                household_id=HOUSEHOLD_ID,
                approval_id=APPROVAL_ID,
                run=_run(created_at=naive),
            )
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="running",
                changed_at=naive,
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_plan_has_only_one_active_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "one-active-run.db")
    second_approval_id = UUID("66666666-6666-6666-6666-666666666666")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.create_approval(
            _approval(revision.content_hash, id_value=second_approval_id)
        )
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
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.create_approval(
            _approval(revision.content_hash, id_value=second_approval_id)
        )
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def race_execute(
        approval_id: UUID,
        run: NewAgentPlanRun,
    ) -> tuple[str, str, UUID, UUID]:
        nonlocal ready
        async with session_factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            repository = AgentRunRepository(session)
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
            status="running",
            changed_at=NOW + timedelta(seconds=30),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=winner[2],
            status="completed",
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
                finished_at=NOW + timedelta(minutes=3),
                error_code="provider_failed",
                error_message="provider failed",
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
        assert {run.status for run in runs} == {"completed", "failed"}

    await engine.dispose()


@pytest.mark.anyio
async def test_consumed_approval_cannot_bind_a_second_run(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "approval-consumption.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=NOW + timedelta(seconds=30),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="completed",
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
@pytest.mark.parametrize(
    "transitions",
    [
        ("running", "completed"),
        ("running", "partial"),
        ("running", "failed"),
        ("cancel_requested", "cancelled"),
        ("running", "cancel_requested", "cancelled"),
    ],
)
async def test_run_lifecycle_allows_only_approved_paths_and_records_timestamps(
    tmp_path: Path,
    transitions: tuple[str, ...],
) -> None:
    engine, session_factory = await _session_factory(
        tmp_path,
        "lifecycle-" + "-".join(transitions) + ".db",
    )
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )

        stored: AgentPlanRunRecord | None = None
        transition_times: dict[str, datetime] = {}
        for index, status in enumerate(transitions, start=1):
            changed_at = NOW + timedelta(minutes=index)
            transition_times[status] = changed_at
            stored = await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status=status,
                changed_at=changed_at,
                error_code=(
                    "provider_partial"
                    if status == "partial"
                    else "provider_failed"
                    if status == "failed"
                    else None
                ),
                error_message=(
                    "some providers failed"
                    if status == "partial"
                    else "provider failed"
                    if status == "failed"
                    else None
                ),
            )

        assert stored is not None
        assert stored.status == transitions[-1]
        if "running" in transition_times:
            assert stored.started_at == transition_times["running"]
        if "cancel_requested" in transition_times:
            assert stored.cancel_requested_at == transition_times["cancel_requested"]
        assert stored.finished_at == transition_times[transitions[-1]]
        if transitions[-1] in {"partial", "failed"}:
            assert stored.error_code is not None
            assert stored.error_message is not None
        else:
            assert stored.error_code is None
            assert stored.error_message is None

        with pytest.raises(AgentPlanConflict, match="agent_run_transition_conflict"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="running",
                changed_at=NOW + timedelta(hours=1),
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_run_lifecycle_rejects_skips_and_stale_transitions(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "invalid-transitions.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )

        with pytest.raises(AgentPlanConflict, match="agent_run_transition_conflict"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="completed",
                changed_at=NOW + timedelta(minutes=1),
            )
        queued = await repository.get_run(HOUSEHOLD_ID, RUN_ID)
        assert queued is not None
        assert queued.status == "queued"

        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=NOW + timedelta(minutes=2),
        )
        with pytest.raises(AgentPlanConflict, match="agent_run_transition_conflict"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancelled",
                changed_at=NOW + timedelta(minutes=3),
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_run_transition_rejects_changed_at_before_run_created(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "transition-before-created.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )

        with pytest.raises(AgentPlanConflict) as captured:
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancel_requested",
                changed_at=NOW - timedelta(microseconds=1),
            )
        assert captured.value.code == "agent_run_transition_conflict"
        stored = await repository.get_run(HOUSEHOLD_ID, RUN_ID)
        assert stored is not None
        assert stored.status == "queued"
        assert stored.cancel_requested_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_terminal_transition_rejects_time_before_started_at(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "terminal-before-start.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=NOW + timedelta(minutes=2),
        )

        with pytest.raises(AgentPlanConflict) as captured:
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="completed",
                changed_at=NOW + timedelta(minutes=1),
            )
        assert captured.value.code == "agent_run_transition_conflict"
        stored = await repository.get_run(HOUSEHOLD_ID, RUN_ID)
        assert stored is not None
        assert stored.status == "running"
        assert stored.finished_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_running_cancel_request_rejects_time_before_start_and_accepts_equality(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "cancel-request-before-start.db")
    started_at = NOW + timedelta(minutes=2)
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=started_at,
        )

        with pytest.raises(AgentPlanConflict) as captured:
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancel_requested",
                changed_at=NOW + timedelta(minutes=1),
            )
        assert captured.value.code == "agent_run_transition_conflict"

        stored = await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancel_requested",
            changed_at=started_at,
        )
        assert stored.status == "cancel_requested"
        assert stored.started_at == started_at
        assert stored.cancel_requested_at == started_at

    await engine.dispose()


@pytest.mark.anyio
async def test_cancelled_transition_rejects_time_before_cancel_request(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "cancel-before-request.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancel_requested",
            changed_at=NOW + timedelta(minutes=2),
        )

        with pytest.raises(AgentPlanConflict) as captured:
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancelled",
                changed_at=NOW + timedelta(minutes=1),
            )
        assert captured.value.code == "agent_run_transition_conflict"
        stored = await repository.get_run(HOUSEHOLD_ID, RUN_ID)
        assert stored is not None
        assert stored.status == "cancel_requested"
        assert stored.finished_at is None

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "transitions",
    [
        ("running", "completed"),
        ("cancel_requested", "cancelled"),
    ],
)
async def test_run_transition_accepts_equal_chronology_boundaries(
    tmp_path: Path,
    transitions: tuple[str, str],
) -> None:
    engine, session_factory = await _session_factory(
        tmp_path,
        "equal-boundary-" + transitions[0] + ".db",
    )
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        for status in transitions:
            stored = await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status=status,
                changed_at=NOW,
            )

        assert stored.status == transitions[-1]
        assert stored.finished_at == NOW

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("case_name", "status", "started_at", "cancel_requested_at", "finished_at"),
    [
        ("started-before-created", "running", NOW - timedelta(seconds=1), None, None),
        (
            "finished-before-started",
            "completed",
            NOW + timedelta(seconds=2),
            None,
            NOW + timedelta(seconds=1),
        ),
        (
            "finished-before-cancel-request",
            "cancelled",
            None,
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=1),
        ),
        (
            "cancel-request-before-started",
            "cancel_requested",
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=1),
            None,
        ),
    ],
)
async def test_database_rejects_invalid_run_chronology(
    tmp_path: Path,
    case_name: str,
    status: str,
    started_at: datetime | None,
    cancel_requested_at: datetime | None,
    finished_at: datetime | None,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, f"chronology-{case_name}.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        with pytest.raises(IntegrityError, match="ck_agent_plan_run_chronology"):
            async with session.begin_nested():
                await session.execute(
                    insert(agent_plan_runs_table).values(
                        id=str(RUN_ID),
                        household_id=str(HOUSEHOLD_ID),
                        plan_id=str(PLAN_ID),
                        revision_id=str(REVISION_ID),
                        approval_id=str(APPROVAL_ID),
                        execute_idempotency_key=f"execute:{case_name}",
                        status=status,
                        created_at=NOW,
                        deadline_at=NOW + timedelta(minutes=10),
                        started_at=started_at,
                        cancel_requested_at=cancel_requested_at,
                        finished_at=finished_at,
                    )
                )

    await engine.dispose()


@pytest.mark.anyio
async def test_database_accepts_cancel_request_equal_to_started_at(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "equal-cancel-start.db")
    started_at = NOW + timedelta(minutes=2)
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.execute(
            insert(agent_plan_runs_table).values(
                id=str(RUN_ID),
                household_id=str(HOUSEHOLD_ID),
                plan_id=str(PLAN_ID),
                revision_id=str(REVISION_ID),
                approval_id=str(APPROVAL_ID),
                execute_idempotency_key="execute:equal-cancel-start",
                status="cancel_requested",
                created_at=NOW,
                deadline_at=NOW + timedelta(minutes=10),
                started_at=started_at,
                cancel_requested_at=started_at,
                finished_at=None,
            )
        )
        await session.commit()

    async with session_factory() as session:
        stored = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert stored is not None
        assert stored.status == "cancel_requested"
        assert stored.started_at == started_at
        assert stored.cancel_requested_at == started_at

    await engine.dispose()


@pytest.mark.anyio
async def test_run_lifecycle_rejects_error_fields_for_incompatible_statuses(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "invalid-error-fields.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )

        with pytest.raises(ValueError, match="error fields"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="running",
                changed_at=NOW + timedelta(minutes=1),
                error_code="not_allowed",
            )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=NOW + timedelta(minutes=1),
        )
        with pytest.raises(ValueError, match="failed transition requires error_code"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="failed",
                changed_at=NOW + timedelta(minutes=2),
            )
        with pytest.raises(ValueError, match="error fields"):
            await repository.set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="completed",
                changed_at=NOW + timedelta(minutes=2),
                error_code="not_allowed",
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_run_transition_compare_and_swap_has_one_winner(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "transition-race.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.execute(
            household_id=HOUSEHOLD_ID,
            approval_id=APPROVAL_ID,
            run=_run(),
        )
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def transition(status: str) -> tuple[str, str]:
        nonlocal ready
        async with session_factory() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            try:
                stored = await AgentRunRepository(session).set_status(
                    household_id=HOUSEHOLD_ID,
                    run_id=RUN_ID,
                    status=status,
                    changed_at=NOW + timedelta(minutes=1),
                )
                await session.commit()
            except AgentPlanConflict as error:
                await session.rollback()
                return "conflict", error.code
            return "winner", stored.status

    outcomes = await asyncio.gather(
        transition("running"),
        transition("cancel_requested"),
    )

    assert sorted(outcome[0] for outcome in outcomes) == ["conflict", "winner"]
    assert next(outcome[1] for outcome in outcomes if outcome[0] == "conflict") == (
        "agent_run_transition_conflict"
    )

    await engine.dispose()


@pytest.mark.anyio
async def test_postgresql_nested_transaction_path_is_sql_free_and_not_rejected() -> None:
    session = _FakePostgresNestedSession()

    await _acquire_sqlite_write_transaction(cast(AsyncSession, session))

    assert session.connection_calls == 0


@pytest.mark.parametrize(
    ("signature", "expected"),
    [
        (
            "UNIQUE constraint failed: agent_search_plan_revisions.plan_id, "
            "agent_search_plan_revisions.revision_number",
            AgentIntegrityConstraint.REVISION_NUMBER,
        ),
        (
            "UNIQUE constraint failed: agent_search_plan_revisions.plan_id, "
            "agent_search_plan_revisions.content_hash",
            AgentIntegrityConstraint.REVISION_HASH,
        ),
        (
            "UNIQUE constraint failed: agent_search_plan_revisions.household_id, "
            "agent_search_plan_revisions.clone_idempotency_key",
            AgentIntegrityConstraint.CLONE_IDEMPOTENCY,
        ),
        (
            "UNIQUE constraint failed: agent_plan_runs.household_id, "
            "agent_plan_runs.execute_idempotency_key",
            AgentIntegrityConstraint.EXECUTE_IDEMPOTENCY,
        ),
        (
            "UNIQUE constraint failed: agent_plan_runs.plan_id",
            AgentIntegrityConstraint.ACTIVE_RUN,
        ),
        (
            "UNIQUE constraint failed: agent_plan_execution_approvals.run_id",
            AgentIntegrityConstraint.APPROVAL_RUN,
        ),
        (
            "UNIQUE constraint failed: agent_plan_runs.approval_id",
            AgentIntegrityConstraint.RUN_APPROVAL,
        ),
    ],
)
def test_sqlite_integrity_classifier_maps_only_exact_known_unique_signatures(
    signature: str,
    expected: AgentIntegrityConstraint,
) -> None:
    error = IntegrityError("insert", {}, sqlite3.IntegrityError(signature))

    assert classify_agent_integrity_constraint(error) is expected


def test_postgresql_integrity_classifier_uses_diagnostic_constraint_name() -> None:
    error = IntegrityError(
        "insert",
        {},
        _PostgresIntegrity("uq_agent_run_execute_idempotency"),
    )

    assert (
        classify_agent_integrity_constraint(error) is AgentIntegrityConstraint.EXECUTE_IDEMPOTENCY
    )


@pytest.mark.parametrize(
    "message",
    [
        "FOREIGN KEY constraint failed",
        "CHECK constraint failed: ck_agent_plan_run_status",
        "UNIQUE constraint failed: agent_search_plans.id",
        "UNIQUE constraint failed: agent_plan_runs.plan_id, agent_plan_runs.status",
        "unique constraint failed: agent_plan_runs.plan_id",
    ],
)
def test_integrity_classifier_does_not_guess_unknown_fk_check_or_near_match(
    message: str,
) -> None:
    error = IntegrityError("insert", {}, sqlite3.IntegrityError(message))

    assert classify_agent_integrity_constraint(error) is None


@pytest.mark.anyio
async def test_real_sqlite_fk_and_check_integrity_errors_remain_unclassified(
    tmp_path: Path,
) -> None:
    engine, session_factory = await _session_factory(tmp_path, "negative-integrity.db")
    async with session_factory() as session:
        revision = await _create_plan(session)
        await AgentRunRepository(session).create_approval(_approval(revision.content_hash))
        await session.commit()

    async with session_factory() as session:
        try:
            async with session.begin_nested():
                await session.execute(
                    insert(agent_plan_runs_table).values(
                        id=str(RUN_ID),
                        household_id=str(HOUSEHOLD_ID),
                        plan_id=str(PLAN_ID),
                        revision_id="ffffffff-ffff-ffff-ffff-ffffffffffff",
                        approval_id=str(APPROVAL_ID),
                        execute_idempotency_key="execute:foreign-key",
                        status="queued",
                        created_at=NOW,
                        deadline_at=NOW + timedelta(minutes=10),
                    )
                )
        except IntegrityError as error:
            foreign_key_error = error
        else:
            raise AssertionError("foreign-key insert unexpectedly succeeded")

        try:
            async with session.begin_nested():
                await session.execute(
                    insert(agent_plan_runs_table).values(
                        id=str(RUN_ID),
                        household_id=str(HOUSEHOLD_ID),
                        plan_id=str(PLAN_ID),
                        revision_id=str(REVISION_ID),
                        approval_id=str(APPROVAL_ID),
                        execute_idempotency_key="execute:check",
                        status="succeeded",
                        created_at=NOW,
                        deadline_at=NOW + timedelta(minutes=10),
                    )
                )
        except IntegrityError as error:
            check_error = error
        else:
            raise AssertionError("check-constraint insert unexpectedly succeeded")

        assert classify_agent_integrity_constraint(foreign_key_error) is None
        assert classify_agent_integrity_constraint(check_error) is None

    await engine.dispose()


@pytest.mark.anyio
async def test_latest_run_orders_by_created_at_then_id(tmp_path: Path) -> None:
    engine, session_factory = await _session_factory(tmp_path, "latest-run.db")
    higher_plan_id = UUID("77777777-7777-7777-7777-777777777777")
    higher_revision_id = UUID("88888888-8888-8888-8888-888888888888")
    higher_approval_id = UUID("99999999-9999-9999-9999-999999999999")
    higher_run_id = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    async with session_factory() as session:
        revision = await _create_plan(session)
        higher_revision = await _create_plan(
            session,
            plan_id=higher_plan_id,
            revision_id=higher_revision_id,
        )
        repository = AgentRunRepository(session)
        await repository.create_approval(_approval(revision.content_hash))
        await repository.create_approval(
            _approval(
                higher_revision.content_hash,
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
    now: datetime = NOW,
) -> AgentPlanRevisionRecord:
    return await AgentPlanRepository(session).create_plan(
        NewAgentPlan(
            id=plan_id,
            household_id=HOUSEHOLD_ID,
            created_by_user_id=USER_ID,
            created_at=now,
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
            expires_at=now + timedelta(hours=1),
            created_at=now,
        ),
    )


def _approval(
    revision_content_hash: str,
    *,
    id_value: UUID = APPROVAL_ID,
    household_id: UUID = HOUSEHOLD_ID,
    revision_id: UUID = REVISION_ID,
    approved_at: datetime = NOW - timedelta(seconds=1),
    expires_at: datetime = NOW + timedelta(minutes=30),
    approved_budget: dict[str, object] | None = None,
    approved_strategies: tuple[str, ...] = ("direct",),
    risk_warning_versions: dict[str, str] | None = None,
) -> NewAgentPlanApproval:
    return NewAgentPlanApproval(
        id=id_value,
        household_id=household_id,
        revision_id=revision_id,
        approved_by_user_id=USER_ID,
        approved_at=approved_at,
        expires_at=expires_at,
        snapshot=AgentPlanApprovalSnapshot(
            revision_content_hash=revision_content_hash,
            approved_by_session_id=SESSION_ID,
            approved_budget=approved_budget
            or {
                "deadline_seconds": 60,
                "http_attempts": 7,
                "logical_operations": 3,
            },
            approved_strategies=approved_strategies,
            risk_warning_versions=risk_warning_versions
            or {"hidden_city": "hidden-city-warning-v1"},
        ),
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


class _PostgresDiagnostic:
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class _PostgresIntegrity(Exception):
    def __init__(self, constraint_name: str) -> None:
        self.diag = _PostgresDiagnostic(constraint_name)
        super().__init__(constraint_name)


class _FakePostgresDialect:
    name = "postgresql"


class _FakePostgresBind:
    dialect = _FakePostgresDialect()


class _FakePostgresNestedSession:
    def __init__(self) -> None:
        self.connection_calls = 0

    def get_bind(self) -> _FakePostgresBind:
        return _FakePostgresBind()

    def in_nested_transaction(self) -> bool:
        return True

    async def connection(self) -> None:
        self.connection_calls += 1
        raise AssertionError("PostgreSQL boundary check must not acquire or query a connection")
