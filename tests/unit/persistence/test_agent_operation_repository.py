from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.application.agent_operations import (
    OperationScheduler,
    OperationSpec,
    logical_workflow_fingerprint,
    operation_fingerprint,
)
from flight_hunter.persistence.agent_repositories import (
    AgentOperationConflict,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationStatus,
    AgentPlanApprovalSnapshot,
    AgentPlanRepository,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    AttemptKind,
    AttemptReservationStatus,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    NewAgentPlanStage,
    NewAgentRunScopeSnapshot,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import (
    agent_plan_runs_table,
    agent_provider_http_attempts_table,
    agent_run_operations_table,
    mapper_registry,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
PLAN_ID = UUID("22222222-2222-2222-2222-222222222222")
REVISION_ID = UUID("33333333-3333-3333-3333-333333333333")
APPROVAL_ID = UUID("44444444-4444-4444-4444-444444444444")
RUN_ID = UUID("55555555-5555-5555-5555-555555555555")
STAGE_ID = UUID("66666666-6666-6666-6666-666666666666")
OPERATION_ID = UUID("77777777-7777-7777-7777-777777777777")
EVIDENCE_RESULT_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
SESSION_ID = UUID("12121212-1212-1212-1212-121212121212")
NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_two_independent_claimers_cannot_lease_the_same_operation(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "claim-race.db")
    await _seed_operation(sessions)
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def claim(worker_id: str) -> UUID | None:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            lease = await AgentOperationRepository(session).claim_next_operation(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                worker_id=worker_id,
                now=NOW + timedelta(seconds=1),
                lease_seconds=30,
            )
            await session.commit()
            return lease.operation.id if lease is not None else None

    claimed = await asyncio.gather(claim("worker-a"), claim("worker-b"))

    assert sorted(item is not None for item in claimed) == [False, True]
    assert next(item for item in claimed if item is not None) == OPERATION_ID
    await engine.dispose()


@pytest.mark.anyio
async def test_expired_lease_is_recovered_without_losing_attempts_and_live_lease_is_not_stolen(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "lease-recovery.db")
    await _seed_operation(sessions)

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        first = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        await session.commit()
        assert first is not None
        assert first.operation.attempt_count == 1

    async with sessions() as session:
        live = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=20),
            lease_seconds=30,
        )
        assert live is None

    async with sessions() as session:
        recovered = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=31),
            lease_seconds=30,
        )
        await session.commit()
        assert recovered is not None
        assert recovered.operation.id == OPERATION_ID
        assert recovered.operation.attempt_count == 2
        assert recovered.operation.lease_owner == "worker-b"

    await engine.dispose()


@pytest.mark.anyio
async def test_expired_final_attempt_is_terminally_recovered_without_manual_database_edit(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "final-attempt-recovery.db")
    await _seed_operation(sessions, max_attempts=1)

    async with sessions() as session:
        first = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=1),
            lease_seconds=10,
        )
        await session.commit()
        assert first is not None
        assert first.operation.attempt_count == first.operation.max_attempts == 1

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        recovered = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=12),
            lease_seconds=30,
        )
        await session.commit()

        assert recovered is None
        operation = await repository.get_operation(HOUSEHOLD_ID, OPERATION_ID)
        assert operation is not None
        assert operation.status is AgentOperationStatus.FAILED
        assert operation.error_code == "agent_lease_expired_attempts_exhausted"
        assert operation.completed_at == NOW + timedelta(seconds=12)

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_identical_materialization_returns_one_row_and_one_logical_unit(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "materialize-race.db")
    await _seed_run_and_stage(sessions, logical_budget=2, http_budget=4)
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def materialize(operation_id: UUID) -> UUID:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            stored = await OperationScheduler(AgentOperationRepository(session)).materialize(
                _operation_spec(operation_id=operation_id)
            )
            await session.commit()
            return stored.id

    ids = await asyncio.gather(
        materialize(OPERATION_ID),
        materialize(UUID("88888888-8888-8888-8888-888888888888")),
    )

    assert ids[0] == ids[1]
    async with sessions() as session:
        row_count = (
            await session.execute(select(func.count()).select_from(agent_run_operations_table))
        ).scalar_one()
        consumed = (
            await session.execute(
                select(agent_plan_runs_table.c.logical_operations_consumed).where(
                    agent_plan_runs_table.c.id == str(RUN_ID)
                )
            )
        ).scalar_one()
        assert row_count == 1
        assert consumed == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_start_and_polls_share_logical_fingerprint_but_only_root_consumes_budget(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "logical-root.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=5)
    workflow = {"origin": "LED", "destination": "CDG", "departure_date": "2026-09-01"}

    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        start = await scheduler.materialize(
            _operation_spec(
                operation_id=OPERATION_ID,
                kind=AgentOperationKind.EXACT_START,
                immutable_input={**workflow, "phase": "start"},
                logical_input=workflow,
                consumes_logical_unit=True,
            )
        )
        poll_one = await scheduler.materialize(
            _operation_spec(
                operation_id=UUID("88888888-8888-8888-8888-888888888888"),
                kind=AgentOperationKind.EXACT_POLL,
                immutable_input={**workflow, "poll_round": 1},
                logical_input=workflow,
                consumes_logical_unit=False,
            )
        )
        poll_two = await scheduler.materialize(
            _operation_spec(
                operation_id=UUID("99999999-9999-9999-9999-999999999999"),
                kind=AgentOperationKind.EXACT_POLL,
                immutable_input={**workflow, "poll_round": 2},
                logical_input=workflow,
                consumes_logical_unit=False,
            )
        )
        await session.commit()

        assert start.logical_operation_fingerprint == poll_one.logical_operation_fingerprint
        assert poll_one.logical_operation_fingerprint == poll_two.logical_operation_fingerprint
        assert start.consumes_logical_unit
        assert not poll_one.consumes_logical_unit
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        assert run.logical_operation_budget == 1
        assert run.logical_operations_consumed == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_http_attempt_reservation_is_atomic_and_exhaustion_writes_no_attempt(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "attempt-budget.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    await _lease_operation(sessions)
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def reserve() -> AttemptReservationStatus:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            result = await AgentOperationRepository(session).reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-http",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.START,
                provider_rpm=20,
                now=NOW + timedelta(seconds=2),
            )
            await session.commit()
            return result.status

    statuses = await asyncio.gather(reserve(), reserve())

    assert sorted(statuses, key=str) == sorted(
        [AttemptReservationStatus.RESERVED, AttemptReservationStatus.BUDGET_EXHAUSTED],
        key=str,
    )
    async with sessions() as session:
        attempt_count = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        run_row = (
            await session.execute(
                select(
                    agent_plan_runs_table.c.http_attempt_budget,
                    agent_plan_runs_table.c.http_attempts_consumed,
                ).where(agent_plan_runs_table.c.id == str(RUN_ID))
            )
        ).one()
        operation_consumed = (
            await session.execute(
                select(agent_run_operations_table.c.http_attempts_consumed).where(
                    agent_run_operations_table.c.id == str(OPERATION_ID)
                )
            )
        ).scalar_one()
        assert attempt_count == 1
        assert run_row == (1, 1)
        assert operation_consumed == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_committed_reservation_survives_simulated_worker_crash(tmp_path: Path) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-crash.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    await _lease_operation(sessions)

    async with sessions() as session:
        result = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=2),
        )
        assert result.status is AttemptReservationStatus.RESERVED
        await session.commit()

    # No completion write simulates the worker dying immediately after reservation.
    async with sessions() as session:
        second = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
        )
        assert second.status is AttemptReservationStatus.BUDGET_EXHAUSTED
        assert second.retry_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_provider_rpm_counts_start_poll_and_retry_across_runs(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "provider-rpm.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=3)
    second_ids = {
        "plan": UUID("aaaaaaaa-2222-2222-2222-222222222222"),
        "revision": UUID("aaaaaaaa-3333-3333-3333-333333333333"),
        "approval": UUID("aaaaaaaa-4444-4444-4444-444444444444"),
        "run": UUID("aaaaaaaa-5555-5555-5555-555555555555"),
        "stage": UUID("aaaaaaaa-6666-6666-6666-666666666666"),
        "operation": UUID("aaaaaaaa-7777-7777-7777-777777777777"),
    }
    await _seed_operation(
        sessions,
        plan_id=second_ids["plan"],
        revision_id=second_ids["revision"],
        approval_id=second_ids["approval"],
        run_id=second_ids["run"],
        stage_id=second_ids["stage"],
        operation_id=second_ids["operation"],
        logical_budget=1,
        http_budget=3,
        idempotency_key="execute:second",
    )
    await _lease_operation(sessions)
    await _lease_operation(
        sessions,
        run_id=second_ids["run"],
        operation_id=second_ids["operation"],
    )

    reservations = (
        (RUN_ID, OPERATION_ID, AttemptKind.START, NOW),
        (second_ids["run"], second_ids["operation"], AttemptKind.POLL, NOW + timedelta(seconds=1)),
    )
    for run_id, operation_id, kind, when in reservations:
        async with sessions() as session:
            result = await AgentOperationRepository(session).reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=run_id,
                operation_id=operation_id,
                worker_id="worker-http",
                provider_id="aviasales_search",
                attempt_kind=kind,
                provider_rpm=2,
                now=when,
            )
            await session.commit()
            assert result.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        limited = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=2,
            now=NOW + timedelta(seconds=2),
        )
        assert limited.status is AttemptReservationStatus.RATE_LIMITED
        assert limited.retry_at == NOW + timedelta(minutes=1)
        await session.rollback()

    async with sessions() as session:
        later = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=2,
            now=NOW + timedelta(minutes=1, seconds=1),
        )
        await session.commit()
        assert later.status is AttemptReservationStatus.RESERVED

    await engine.dispose()


@pytest.mark.anyio
async def test_provider_rpm_window_excludes_attempt_exactly_sixty_seconds_old(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "provider-rpm-boundary.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=2)
    await _lease_operation(sessions)

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        first = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=1,
            now=NOW,
        )
        await session.commit()
        assert first.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        second = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.POLL,
            provider_rpm=1,
            now=NOW + timedelta(seconds=60),
        )
        await session.commit()
        assert second.status is AttemptReservationStatus.RESERVED
        assert second.retry_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_rate_limit_and_budget_denials_leave_all_counters_unchanged(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "attempt-denial-invariants.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=2)
    await _lease_operation(sessions)
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        first = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=1,
            now=NOW,
        )
        await session.commit()
        assert first.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        limited = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.POLL,
            provider_rpm=1,
            now=NOW + timedelta(seconds=1),
        )
        assert limited.status is AttemptReservationStatus.RATE_LIMITED
        await session.commit()

    async with sessions() as session:
        await session.execute(
            update(agent_plan_runs_table)
            .where(agent_plan_runs_table.c.id == str(RUN_ID))
            .values(http_attempt_budget=1)
        )
        await session.commit()

    async with sessions() as session:
        exhausted = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(minutes=2),
        )
        assert exhausted.status is AttemptReservationStatus.BUDGET_EXHAUSTED
        await session.commit()

    async with sessions() as session:
        attempts = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        run_consumed = (
            await session.execute(
                select(agent_plan_runs_table.c.http_attempts_consumed).where(
                    agent_plan_runs_table.c.id == str(RUN_ID)
                )
            )
        ).scalar_one()
        operation_consumed = (
            await session.execute(
                select(agent_run_operations_table.c.http_attempts_consumed).where(
                    agent_run_operations_table.c.id == str(OPERATION_ID)
                )
            )
        ).scalar_one()
        assert (attempts, run_consumed, operation_consumed) == (1, 1, 1)

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("run_state", ("cancel_requested", "cancelled", "completed", "expired"))
async def test_claim_does_not_start_work_for_inactive_or_expired_run(
    tmp_path: Path,
    run_state: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"claim-{run_state}.db")
    await _seed_operation(sessions)
    async with sessions() as session:
        await _transition_run_state(session, run_state)
        await session.commit()

    claim_at = NOW + timedelta(minutes=11) if run_state == "expired" else NOW + timedelta(seconds=4)
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-denied",
            now=claim_at,
            lease_seconds=30,
        )
        await session.commit()

        assert lease is None
        operation = await repository.get_operation(HOUSEHOLD_ID, OPERATION_ID)
        assert operation is not None
        assert operation.status is AgentOperationStatus.PENDING
        assert operation.attempt_count == 0

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("run_state", ("cancel_requested", "cancelled", "completed", "expired"))
async def test_reservation_is_denied_atomically_for_inactive_or_expired_run(
    tmp_path: Path,
    run_state: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"reserve-{run_state}.db")
    await _seed_operation(sessions, http_budget=2)
    await _lease_operation(sessions, lease_seconds=1_200)
    async with sessions() as session:
        await _transition_run_state(session, run_state)
        await session.commit()

    reserve_at = (
        NOW + timedelta(minutes=11) if run_state == "expired" else NOW + timedelta(seconds=4)
    )
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        with pytest.raises(AgentOperationConflict) as captured:
            await repository.reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-http",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.START,
                provider_rpm=20,
                now=reserve_at,
            )
        assert captured.value.code == "agent_operation_not_reservable"
        await session.commit()

    async with sessions() as session:
        attempts = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        counters = (
            await session.execute(
                select(
                    agent_plan_runs_table.c.http_attempts_consumed,
                    agent_run_operations_table.c.http_attempts_consumed,
                )
                .join(
                    agent_run_operations_table,
                    agent_run_operations_table.c.run_id == agent_plan_runs_table.c.id,
                )
                .where(agent_plan_runs_table.c.id == str(RUN_ID))
                .where(agent_run_operations_table.c.id == str(OPERATION_ID))
            )
        ).one()
        assert attempts == 0
        assert counters == (0, 0)

    await engine.dispose()


@pytest.mark.anyio
async def test_stale_worker_cannot_reserve_after_lease_takeover(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-owner-cas.db")
    await _seed_operation(sessions, http_budget=2)
    await _lease_operation(sessions, worker_id="worker-a", lease_seconds=10)
    async with sessions() as session:
        takeover = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=11),
            lease_seconds=30,
        )
        await session.commit()
        assert takeover is not None

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        with pytest.raises(AgentOperationConflict) as captured:
            await repository.reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.RETRY,
                provider_rpm=20,
                now=NOW + timedelta(seconds=12),
            )
        assert captured.value.code == "agent_operation_not_reservable"
        await session.commit()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        allowed = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-b",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(seconds=12),
        )
        await session.commit()
        assert allowed.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        attempts = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        consumed = (
            await session.execute(
                select(agent_plan_runs_table.c.http_attempts_consumed).where(
                    agent_plan_runs_table.c.id == str(RUN_ID)
                )
            )
        ).scalar_one()
        assert (attempts, consumed) == (1, 1)

    await engine.dispose()


@pytest.mark.anyio
async def test_operation_stage_scope_and_private_state_are_household_scoped(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-household.db")
    await _seed_operation(sessions)
    snapshot_id = UUID("99999999-9999-9999-9999-999999999999")
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        await repository.append_scope_snapshot(
            NewAgentRunScopeSnapshot(
                id=snapshot_id,
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                fingerprint="sha256:" + "a" * 64,
                snapshot={"destinations": ["CDG", "ORY"]},
                created_at=NOW,
            )
        )
        await session.commit()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        assert await repository.get_stage(OTHER_HOUSEHOLD_ID, STAGE_ID) is None
        assert await repository.get_operation(OTHER_HOUSEHOLD_ID, OPERATION_ID) is None
        assert await repository.get_scope_snapshot(OTHER_HOUSEHOLD_ID, snapshot_id) is None
        assert (
            await repository.claim_next_operation(
                household_id=OTHER_HOUSEHOLD_ID,
                run_id=RUN_ID,
                worker_id="worker-other",
                now=NOW,
                lease_seconds=30,
            )
            is None
        )
        public = await repository.get_operation(HOUSEHOLD_ID, OPERATION_ID)
        assert public is not None
        assert not hasattr(public, "private_continuation_json")
        assert not hasattr(public, "private_continuation")
        assert "private_continuation" not in repr(public)

        lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-owner",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert lease is not None
        assert lease.private_continuation == {"search_session": "opaque-1"}

    await engine.dispose()


@pytest.mark.anyio
async def test_stage_progress_and_stage_listing_are_derived_from_operation_rows(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "stage-progress.db")
    await _seed_run_and_stage(sessions, logical_budget=5, http_budget=5)
    ids = {
        "succeeded": UUID("11111111-7777-7777-7777-777777777777"),
        "failed": UUID("22222222-7777-7777-7777-777777777777"),
        "leased": UUID("33333333-7777-7777-7777-777777777777"),
        "skipped": UUID("44444444-7777-7777-7777-777777777777"),
        "pending": UUID("55555555-7777-7777-7777-777777777777"),
    }
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        for index, operation_id in enumerate(ids.values(), start=1):
            await scheduler.materialize(
                _operation_spec(
                    operation_id=operation_id,
                    immutable_input={"origin": "LED", "destination": f"D{index:02d}"},
                    logical_input={"origin": "LED", "destination": f"D{index:02d}"},
                )
            )
        repository = AgentOperationRepository(session)
        succeeded_lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert succeeded_lease is not None
        await repository.mark_operation_succeeded(
            household_id=HOUSEHOLD_ID,
            operation_id=succeeded_lease.operation.id,
            worker_id="worker-a",
            result_type="confirmed_offer",
            result_id=EVIDENCE_RESULT_ID,
            now=NOW + timedelta(seconds=2),
        )
        failed_lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=3),
            lease_seconds=30,
        )
        assert failed_lease is not None
        await repository.mark_operation_failed(
            household_id=HOUSEHOLD_ID,
            operation_id=failed_lease.operation.id,
            worker_id="worker-b",
            error_code="provider_schema",
            now=NOW + timedelta(seconds=4),
        )
        leased = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-c",
            now=NOW + timedelta(seconds=5),
            lease_seconds=30,
        )
        assert leased is not None
        await repository.mark_operation_skipped(
            household_id=HOUSEHOLD_ID,
            operation_id=ids["skipped"],
            error_code="scope_excluded",
            now=NOW + timedelta(seconds=6),
        )
        await session.commit()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        stages = await repository.list_stages(HOUSEHOLD_ID, RUN_ID)
        progress = await repository.get_stage_progress(HOUSEHOLD_ID, STAGE_ID)
        operations = await repository.list_operations(HOUSEHOLD_ID, RUN_ID)

        assert [stage.id for stage in stages] == [STAGE_ID]
        assert progress is not None
        assert progress.total == 5
        assert progress.leased == 1
        assert progress.pending == 1
        assert progress.succeeded == progress.failed == progress.skipped == 1
        assert len(operations) == 5
        assert all(not hasattr(operation, "private_continuation") for operation in operations)

    await engine.dispose()


@pytest.mark.anyio
async def test_claim_order_is_deterministic_by_eligibility_created_at_and_id(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "claim-order.db")
    await _seed_run_and_stage(sessions, logical_budget=3, http_budget=3)
    smaller_id = UUID("11111111-7777-7777-7777-777777777777")
    larger_id = UUID("99999999-7777-7777-7777-777777777777")
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=larger_id,
                    immutable_input={"destination": "ORY"},
                    logical_input={"destination": "ORY"},
                ),
                created_at=NOW,
            )
        )
        await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=smaller_id,
                    immutable_input={"destination": "CDG"},
                    logical_input={"destination": "CDG"},
                ),
                created_at=NOW,
            )
        )
        claimed = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert claimed is not None
        assert claimed.operation.id == smaller_id

    await engine.dispose()


@pytest.mark.anyio
async def test_stale_lease_owner_cannot_retry_succeed_or_fail_a_reclaimed_operation(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "lease-owner-cas.db")
    await _seed_operation(sessions)
    async with sessions() as session:
        first = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW,
            lease_seconds=10,
        )
        await session.commit()
        assert first is not None

    async with sessions() as session:
        second = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=11),
            lease_seconds=30,
        )
        await session.commit()
        assert second is not None

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        actions = (
            lambda: repository.schedule_retry(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                next_retry_at=NOW + timedelta(minutes=1),
                error_code="provider_network",
                now=NOW + timedelta(seconds=12),
            ),
            lambda: repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                result_type="confirmed_offer",
                result_id=UUID("99999999-9999-9999-9999-999999999999"),
                now=NOW + timedelta(seconds=12),
            ),
            lambda: repository.mark_operation_failed(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                error_code="provider_schema",
                now=NOW + timedelta(seconds=12),
            ),
        )
        for action in actions:
            with pytest.raises(AgentOperationConflict) as captured:
                await action()
            assert captured.value.code == "agent_operation_transition_conflict"

        stored = await repository.get_operation(HOUSEHOLD_ID, OPERATION_ID)
        assert stored is not None
        assert stored.status == AgentOperationStatus.LEASED.value
        assert stored.lease_owner == "worker-b"

    await engine.dispose()


@pytest.mark.anyio
async def test_invalid_operation_transitions_naive_times_and_counter_overflow_are_rejected(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-invalid.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    naive = NOW.replace(tzinfo=None)

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        with pytest.raises(ValueError, match="timezone-aware"):
            await repository.claim_next_operation(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                worker_id="worker",
                now=naive,
                lease_seconds=30,
            )
        with pytest.raises(ValueError, match="provider_rpm"):
            await repository.reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.START,
                provider_rpm=0,
                now=NOW,
            )
        with pytest.raises(AgentOperationConflict, match="agent_operation_transition_conflict"):
            await repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="never-leased",
                result_type="confirmed_offer",
                result_id=UUID("99999999-9999-9999-9999-999999999999"),
                now=NOW,
            )

    async with sessions() as session:
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    update(agent_plan_runs_table)
                    .where(agent_plan_runs_table.c.id == str(RUN_ID))
                    .values(logical_operations_consumed=2)
                )
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(
                    update(agent_run_operations_table)
                    .where(agent_run_operations_table.c.id == str(OPERATION_ID))
                    .values(status=AgentOperationStatus.SUCCEEDED.value)
                )

    await engine.dispose()


@pytest.mark.anyio
async def test_sqlite_mutation_rejects_caller_savepoint_and_honors_outer_rollback(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-boundary.db")
    await _seed_run_and_stage(sessions)
    spec = _operation_spec()

    async with sessions() as session:
        caller_savepoint = await session.begin_nested()
        with pytest.raises(AgentOperationConflict) as captured:
            await OperationScheduler(AgentOperationRepository(session)).materialize(spec)
        assert captured.value.code == "agent_sqlite_nested_transaction_unsupported"
        await caller_savepoint.rollback()
        await session.rollback()

    async with sessions() as session:
        caller_transaction = await session.begin()
        await OperationScheduler(AgentOperationRepository(session)).materialize(spec)
        await caller_transaction.rollback()

    async with sessions() as session:
        assert (
            await AgentOperationRepository(session).get_operation(HOUSEHOLD_ID, OPERATION_ID)
            is None
        )

    await engine.dispose()


async def _session_factory(
    tmp_path: Path,
    filename: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_database_engine(f"sqlite+aiosqlite:///{(tmp_path / filename).as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_operation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    plan_id: UUID = PLAN_ID,
    revision_id: UUID = REVISION_ID,
    approval_id: UUID = APPROVAL_ID,
    run_id: UUID = RUN_ID,
    stage_id: UUID = STAGE_ID,
    operation_id: UUID = OPERATION_ID,
    logical_budget: int = 2,
    http_budget: int = 4,
    max_attempts: int = 3,
    idempotency_key: str = "execute:ledger:1",
) -> None:
    await _seed_run_and_stage(
        sessions,
        plan_id=plan_id,
        revision_id=revision_id,
        approval_id=approval_id,
        run_id=run_id,
        stage_id=stage_id,
        logical_budget=logical_budget,
        http_budget=http_budget,
        idempotency_key=idempotency_key,
    )
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(
            _operation_spec(
                operation_id=operation_id,
                run_id=run_id,
                stage_id=stage_id,
                max_attempts=max_attempts,
            )
        )
        await session.commit()


async def _lease_operation(
    sessions: async_sessionmaker[AsyncSession],
    *,
    run_id: UUID = RUN_ID,
    operation_id: UUID = OPERATION_ID,
    worker_id: str = "worker-http",
    now: datetime = NOW,
    lease_seconds: int = 600,
) -> None:
    async with sessions() as session:
        lease = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=run_id,
            worker_id=worker_id,
            now=now,
            lease_seconds=lease_seconds,
        )
        await session.commit()
        assert lease is not None
        assert lease.operation.id == operation_id


async def _transition_run_state(session: AsyncSession, run_state: str) -> None:
    if run_state == "expired":
        return
    repository = AgentRunRepository(session)
    if run_state == "completed":
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="running",
            changed_at=NOW + timedelta(seconds=2),
        )
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="completed",
            changed_at=NOW + timedelta(seconds=3),
        )
        return
    await repository.set_status(
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        status="cancel_requested",
        changed_at=NOW + timedelta(seconds=2),
    )
    if run_state == "cancelled":
        await repository.set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancelled",
            changed_at=NOW + timedelta(seconds=3),
        )


async def _seed_run_and_stage(
    sessions: async_sessionmaker[AsyncSession],
    *,
    plan_id: UUID = PLAN_ID,
    revision_id: UUID = REVISION_ID,
    approval_id: UUID = APPROVAL_ID,
    run_id: UUID = RUN_ID,
    stage_id: UUID = STAGE_ID,
    logical_budget: int = 2,
    http_budget: int = 4,
    idempotency_key: str = "execute:ledger:1",
) -> None:
    async with sessions() as session:
        revision = await AgentPlanRepository(session).create_plan(
            NewAgentPlan(
                id=plan_id,
                household_id=HOUSEHOLD_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
            ),
            NewAgentPlanRevision(
                id=revision_id,
                state="awaiting_approval",
                plan={"route": ["LED", "CDG"]},
                scope_snapshot={"airports": ["LED", "CDG"]},
                capability_snapshot={"provider": "aviasales_search", "version": "v1"},
                cost_model_snapshot={"version": "v1", "requests_per_minute": 20},
                parser_version="parser-v1",
                planner_version="planner-v1",
                estimated_calendar_searches=0,
                estimated_exact_searches=logical_budget,
                estimated_logical_operations=logical_budget,
                estimated_http_attempts=http_budget,
                estimated_deadline_seconds=600,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            ),
        )
        approval = NewAgentPlanApproval(
            id=approval_id,
            household_id=HOUSEHOLD_ID,
            revision_id=revision_id,
            approved_by_user_id=USER_ID,
            approved_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
            snapshot=AgentPlanApprovalSnapshot(
                revision_content_hash=revision.content_hash,
                approved_by_session_id=SESSION_ID,
                approved_budget={
                    "logical_operations": logical_budget,
                    "http_attempts": http_budget,
                    "deadline_seconds": 600,
                },
                approved_strategies=("direct",),
                risk_warning_versions={},
            ),
        )
        await AgentRunRepository(session).approve_and_execute(
            approval=approval,
            run=NewAgentPlanRun(
                id=run_id,
                execute_idempotency_key=idempotency_key,
                created_at=NOW,
                deadline_at=NOW + timedelta(minutes=10),
            ),
        )
        await AgentOperationRepository(session).create_stage(
            NewAgentPlanStage(
                id=stage_id,
                household_id=HOUSEHOLD_ID,
                run_id=run_id,
                kind=AgentPlanStageKind.EXACT_SEARCH,
                status=AgentStageStatus.PENDING,
                created_at=NOW,
            )
        )
        await session.commit()


def _operation_spec(
    *,
    operation_id: UUID = OPERATION_ID,
    run_id: UUID = RUN_ID,
    stage_id: UUID = STAGE_ID,
    kind: AgentOperationKind = AgentOperationKind.EXACT_START,
    immutable_input: dict[str, object] | None = None,
    logical_input: dict[str, object] | None = None,
    consumes_logical_unit: bool = True,
    max_attempts: int = 3,
) -> OperationSpec:
    immutable = immutable_input or {
        "origin": "LED",
        "destination": "CDG",
        "departure_date": "2026-09-01",
    }
    logical = logical_input or {
        "origin": "LED",
        "destination": "CDG",
        "departure_date": "2026-09-01",
    }
    return OperationSpec(
        id=operation_id,
        household_id=HOUSEHOLD_ID,
        run_id=run_id,
        stage_id=stage_id,
        provider_id="aviasales_search",
        kind=kind,
        immutable_input=immutable,
        logical_workflow_input=logical,
        consumes_logical_unit=consumes_logical_unit,
        private_continuation={"search_session": "opaque-1"},
        max_attempts=max_attempts,
        created_at=NOW,
    )


def test_fingerprint_helpers_are_used_by_operation_fixture() -> None:
    spec = _operation_spec()
    assert operation_fingerprint(spec.kind, spec.immutable_input).startswith("sha256:")
    assert logical_workflow_fingerprint("exact_search", spec.logical_workflow_input).startswith(
        "sha256:"
    )
