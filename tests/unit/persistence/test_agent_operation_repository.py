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
from flight_hunter.domain.agent_evidence import ProtectionStatus
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentEvidenceRepository,
    AgentOperationConflict,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentOperationStatus,
    AgentPlanApprovalSnapshot,
    AgentPlanRepository,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    AttemptKind,
    AttemptReservationStatus,
    CircuitPermitStatus,
    NewAgentConfirmedOfferEvidence,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    NewAgentPlanStage,
    NewAgentRunScopeSnapshot,
    ServerPrivateCircuitPermit,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import (
    agent_plan_runs_table,
    agent_provider_circuit_state_table,
    agent_provider_http_attempts_table,
    agent_run_operations_table,
    agent_run_scope_snapshots_table,
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
async def test_review_start_and_polls_share_logical_fingerprint_but_only_root_consumes_budget(
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
            replace(
                _operation_spec(
                    operation_id=UUID("88888888-8888-8888-8888-888888888888"),
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={**workflow, "poll_round": 1},
                    logical_input=workflow,
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=start.id,
            )
        )
        poll_two = await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=UUID("99999999-9999-9999-9999-999999999999"),
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={**workflow, "poll_round": 2},
                    logical_input=workflow,
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=start.id,
            )
        )
        await session.commit()

        assert start.logical_operation_fingerprint == poll_one.logical_operation_fingerprint
        assert poll_one.logical_operation_fingerprint == poll_two.logical_operation_fingerprint
        assert start.consumes_logical_unit
        assert not poll_one.consumes_logical_unit
        assert poll_one.logical_root_operation_id == start.id
        assert poll_two.logical_root_operation_id == start.id
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        assert run.logical_operation_budget == 1
        assert run.logical_operations_consumed == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_http_reservation_is_idempotent_and_writes_one_attempt(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "attempt-budget.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    await _lease_operation(sessions)
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW + timedelta(seconds=1),
    )
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
                circuit_permit=permit,
            )
            await session.commit()
            return result.status

    statuses = await asyncio.gather(reserve(), reserve())

    assert statuses == [AttemptReservationStatus.RESERVED, AttemptReservationStatus.RESERVED]
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
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW + timedelta(seconds=1),
    )

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
            circuit_permit=permit,
        )
        assert result.status is AttemptReservationStatus.RESERVED
        await session.commit()

    # No completion write simulates the worker dying before it can observe the reservation result.
    async with sessions() as session:
        second = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
            circuit_permit=permit,
        )
        assert second.status is AttemptReservationStatus.RESERVED
        assert second.reused
        assert second.reservation_id == result.reservation_id
        assert second.retry_at is None

    await engine.dispose()


@pytest.mark.anyio
async def test_provider_rpm_counts_distinct_claim_attempts_across_runs(
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
    await _lease_operation(sessions, lease_seconds=10)
    await _lease_operation(
        sessions,
        run_id=second_ids["run"],
        operation_id=second_ids["operation"],
        lease_seconds=10,
    )
    first_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW,
    )
    second_permit = await _issue_permit(
        sessions,
        run_id=second_ids["run"],
        operation_id=second_ids["operation"],
        worker_id="worker-http",
        now=NOW,
    )

    reservations = (
        (RUN_ID, OPERATION_ID, AttemptKind.START, NOW, first_permit),
        (
            second_ids["run"],
            second_ids["operation"],
            AttemptKind.START,
            NOW + timedelta(seconds=1),
            second_permit,
        ),
    )
    for run_id, operation_id, kind, when, permit in reservations:
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
                circuit_permit=permit,
            )
            await session.commit()
            assert result.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        reclaimed = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-retry",
            now=NOW + timedelta(seconds=11),
            lease_seconds=120,
        )
        await session.commit()
        assert reclaimed is not None and reclaimed.operation.attempt_count == 2
    retry_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-retry",
        now=NOW + timedelta(seconds=11),
    )

    async with sessions() as session:
        limited = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-retry",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=2,
            now=NOW + timedelta(seconds=12),
            circuit_permit=retry_permit,
        )
        assert limited.status is AttemptReservationStatus.RATE_LIMITED
        assert limited.retry_at == NOW + timedelta(minutes=1)
        await session.rollback()

    async with sessions() as session:
        later = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-retry",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=2,
            now=NOW + timedelta(minutes=1, seconds=1),
            circuit_permit=retry_permit,
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
    await _lease_operation(sessions, lease_seconds=10)
    first_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW,
    )

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
            circuit_permit=first_permit,
        )
        await session.commit()
        assert first.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        reclaimed = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-retry",
            now=NOW + timedelta(seconds=60),
            lease_seconds=60,
        )
        await session.commit()
        assert reclaimed is not None and reclaimed.operation.attempt_count == 2
    retry_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-retry",
        now=NOW + timedelta(seconds=60),
    )

    async with sessions() as session:
        second = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-retry",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=1,
            now=NOW + timedelta(seconds=60),
            circuit_permit=retry_permit,
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
    await _lease_operation(sessions, lease_seconds=10)
    first_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW,
    )
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
            circuit_permit=first_permit,
        )
        await session.commit()
        assert first.status is AttemptReservationStatus.RESERVED

    async with sessions() as session:
        reclaimed = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-retry",
            now=NOW + timedelta(seconds=11),
            lease_seconds=300,
        )
        await session.commit()
        assert reclaimed is not None and reclaimed.operation.attempt_count == 2
    retry_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-retry",
        now=NOW + timedelta(seconds=11),
    )

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        limited = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-retry",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=1,
            now=NOW + timedelta(seconds=11),
            circuit_permit=retry_permit,
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
            worker_id="worker-retry",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(minutes=2),
            circuit_permit=retry_permit,
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
async def test_review_claim_reconciles_inactive_or_expired_run_without_starting_work(
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
        assert operation.status is AgentOperationStatus.SKIPPED
        assert operation.attempt_count == 0
        expected_error = {
            "cancel_requested": "agent_run_cancelled",
            "cancelled": "agent_run_cancelled",
            "completed": "agent_run_terminal",
            "expired": "agent_run_deadline_exceeded",
        }[run_state]
        assert operation.error_code == expected_error
        assert operation.completed_at == claim_at

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
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW + timedelta(seconds=1),
    )
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
                circuit_permit=permit,
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
    stale_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-a",
        now=NOW + timedelta(seconds=1),
    )
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
                circuit_permit=stale_permit,
            )
        assert captured.value.code == "agent_operation_not_reservable"
        await session.commit()

    current_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=12),
    )
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
            circuit_permit=current_permit,
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
async def test_review_operation_stage_scope_and_private_state_are_household_scoped(
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
        assert "opaque-1" not in repr(lease)
        assert "private_continuation=" not in repr(lease)

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
            spec = _operation_spec(
                operation_id=operation_id,
                immutable_input={"origin": "LED", "destination": f"D{index:02d}"},
                logical_input={"origin": "LED", "destination": f"D{index:02d}"},
            )
            if operation_id == ids["succeeded"]:
                spec = replace(
                    spec,
                    provider_id=None,
                    kind=AgentOperationKind.SCOPE_FREEZE,
                    consumes_logical_unit=False,
                    private_continuation=None,
                )
            await scheduler.materialize(spec)
        repository = AgentOperationRepository(session)
        succeeded_lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert succeeded_lease is not None
        scope = await repository.append_scope_snapshot(
            NewAgentRunScopeSnapshot(
                id=EVIDENCE_RESULT_ID,
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                fingerprint="sha256:" + "f" * 64,
                snapshot={"destinations": ["CDG"]},
                created_at=NOW + timedelta(seconds=1),
            )
        )
        await repository.mark_operation_succeeded(
            household_id=HOUSEHOLD_ID,
            operation_id=succeeded_lease.operation.id,
            worker_id="worker-a",
            result_type=AgentOperationResultType.SCOPE_SNAPSHOT,
            result_id=scope.id,
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
    await _lease_operation(sessions, worker_id="worker")
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker",
        now=NOW,
    )
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
                circuit_permit=permit,
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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind",
    (
        AgentOperationKind.SCOPE_FREEZE,
        AgentOperationKind.COMPARISON,
        AgentOperationKind.COMPOSITION,
        AgentOperationKind.RANKING,
        AgentOperationKind.ANALYSIS,
    ),
)
async def test_review_provider_neutral_operations_are_independent_and_consume_no_logical_unit(
    tmp_path: Path,
    kind: AgentOperationKind,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"independent-{kind.value}.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)
    operation_id = UUID(int=OPERATION_ID.int + tuple(AgentOperationKind).index(kind))

    async with sessions() as session:
        stored = await OperationScheduler(AgentOperationRepository(session)).materialize(
            replace(
                _operation_spec(
                    operation_id=operation_id,
                    kind=kind,
                    immutable_input={"value": 1},
                    logical_input={"value": 1},
                    consumes_logical_unit=False,
                ),
                provider_id=None,
                private_continuation=None,
                logical_root_operation_id=None,
            )
        )
        await session.commit()

        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        assert run.logical_operations_consumed == 0
        assert stored.logical_root_operation_id is None
        assert not stored.consumes_logical_unit

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("consumes", (False, True))
async def test_review_suggest_discovery_is_rejected_until_it_has_an_approved_budget_category(
    tmp_path: Path,
    consumes: bool,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"suggest-budget-{consumes}.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)

    async with sessions() as session:
        with pytest.raises(AgentOperationConflict) as captured:
            await OperationScheduler(AgentOperationRepository(session)).materialize(
                replace(
                    _operation_spec(
                        kind=AgentOperationKind.SUGGEST_DISCOVERY,
                        consumes_logical_unit=consumes,
                    ),
                    logical_root_operation_id=None,
                )
            )
        assert captured.value.code == "agent_operation_kind_not_budgeted"

        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        assert run.logical_operations_consumed == 0

    await engine.dispose()


@pytest.mark.anyio
async def test_review_exact_poll_requires_a_same_scope_exact_start_root(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "logical-root-validation.db")
    await _seed_run_and_stage(sessions, logical_budget=2, http_budget=2)
    scheduler_session = sessions()
    async with scheduler_session as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        root = await scheduler.materialize(_operation_spec())

        missing_root_poll = replace(
            _operation_spec(
                operation_id=UUID("88888888-8888-8888-8888-888888888888"),
                kind=AgentOperationKind.EXACT_POLL,
                immutable_input={"origin": "LED", "destination": "CDG", "poll_round": 1},
                consumes_logical_unit=False,
            ),
            logical_root_operation_id=None,
        )
        with pytest.raises(AgentOperationConflict) as missing:
            await scheduler.materialize(missing_root_poll)
        assert missing.value.code == "agent_logical_operation_root_missing"

        forged = replace(
            missing_root_poll,
            id=UUID("99999999-9999-9999-9999-999999999999"),
            immutable_input={"origin": "LED", "destination": "CDG", "poll_round": 2},
            logical_root_operation_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        )
        with pytest.raises(AgentOperationConflict) as unknown:
            await scheduler.materialize(forged)
        assert unknown.value.code == "agent_logical_operation_root_not_found"

        wrong_provider = replace(
            forged,
            id=UUID("aaaaaaaa-8888-8888-8888-888888888888"),
            provider_id="different_provider",
            immutable_input={"origin": "LED", "destination": "CDG", "poll_round": 3},
            logical_root_operation_id=root.id,
        )
        with pytest.raises(AgentOperationConflict) as mismatch:
            await scheduler.materialize(wrong_provider)
        assert mismatch.value.code == "agent_logical_operation_root_mismatch"

        invalid_child = replace(
            _operation_spec(
                operation_id=UUID("bbbbbbbb-8888-8888-8888-888888888888"),
                kind=AgentOperationKind.EXACT_START,
                immutable_input={"origin": "LED", "destination": "ORY"},
                logical_input={"origin": "LED", "destination": "ORY"},
                consumes_logical_unit=False,
            ),
            logical_root_operation_id=root.id,
        )
        with pytest.raises(AgentOperationConflict) as incompatible:
            await scheduler.materialize(invalid_child)
        assert incompatible.value.code == "agent_logical_operation_shape_invalid"

        await session.rollback()

    await engine.dispose()


@pytest.mark.anyio
async def test_review_cancelled_owner_can_cas_skip_its_live_lease_before_io(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "cancel-owner-skip.db")
    await _seed_operation(sessions)
    await _lease_operation(sessions, worker_id="worker-a", lease_seconds=30)
    async with sessions() as session:
        await _transition_run_state(session, "cancel_requested")
        await session.commit()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        skipped = await repository.mark_claimed_operation_skipped(
            household_id=HOUSEHOLD_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-a",
            error_code="agent_run_cancelled",
            now=NOW + timedelta(seconds=3),
        )
        await session.commit()
        assert skipped.status is AgentOperationStatus.SKIPPED
        assert skipped.error_code == "agent_run_cancelled"

    async with sessions() as session:
        with pytest.raises(AgentOperationConflict) as stale:
            await AgentOperationRepository(session).mark_claimed_operation_skipped(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                error_code="agent_run_cancelled",
                now=NOW + timedelta(seconds=4),
            )
        assert stale.value.code == "agent_operation_transition_conflict"

    await engine.dispose()


@pytest.mark.anyio
async def test_review_inactive_run_reconciles_expired_lease_and_rejects_stale_owner(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "cancel-expired-lease.db")
    await _seed_operation(sessions)
    await _lease_operation(sessions, worker_id="worker-a", lease_seconds=5)
    async with sessions() as session:
        await _transition_run_state(session, "cancel_requested")
        await session.commit()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        assert (
            await repository.claim_next_operation(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                worker_id="worker-b",
                now=NOW + timedelta(seconds=6),
                lease_seconds=30,
            )
            is None
        )
        stored = await repository.get_operation(HOUSEHOLD_ID, OPERATION_ID)
        assert stored is not None
        assert stored.status is AgentOperationStatus.SKIPPED
        assert stored.error_code == "agent_run_cancelled"
        with pytest.raises(AgentOperationConflict) as stale:
            await repository.mark_claimed_operation_skipped(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                error_code="agent_run_cancelled",
                now=NOW + timedelta(seconds=6),
            )
        assert stale.value.code == "agent_operation_transition_conflict"

    await engine.dispose()


@pytest.mark.anyio
async def test_review_run_has_exactly_one_immutable_scope_snapshot(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "single-scope.db")
    await _seed_run_and_stage(sessions)
    first_id = UUID("11111111-9999-9999-9999-999999999999")
    same_id = UUID("22222222-9999-9999-9999-999999999999")
    different_id = UUID("33333333-9999-9999-9999-999999999999")
    first = NewAgentRunScopeSnapshot(
        id=first_id,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        fingerprint="sha256:" + "a" * 64,
        snapshot={"airports": ["LED"], "destinations": ["CDG"]},
        created_at=NOW,
    )

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        stored = await repository.append_scope_snapshot(first)
        repeated = await repository.append_scope_snapshot(replace(first, id=same_id))
        assert repeated.id == stored.id == first_id
        with pytest.raises(AgentOperationConflict) as conflict:
            await repository.append_scope_snapshot(
                replace(
                    first,
                    id=different_id,
                    fingerprint="sha256:" + "b" * 64,
                    snapshot={"airports": ["LED"], "destinations": ["ORY"]},
                )
            )
        assert conflict.value.code == "agent_run_scope_conflict"
        await session.commit()

    async with sessions() as session:
        assert (
            await session.execute(select(func.count()).select_from(agent_run_scope_snapshots_table))
        ).scalar_one() == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_review_scope_allowlist_and_concurrent_different_snapshots_have_one_winner(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "scope-policy-race.db")
    await _seed_run_and_stage(sessions)
    unsafe = NewAgentRunScopeSnapshot(
        id=UUID("11111111-9999-9999-9999-999999999999"),
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        fingerprint="sha256:" + "a" * 64,
        snapshot={"airports": ["LED"], "unexpected_safe_key": "value"},
        created_at=NOW,
    )
    async with sessions() as session:
        with pytest.raises(ValueError, match="not allowed"):
            await AgentOperationRepository(session).append_scope_snapshot(unsafe)

    candidates = (
        replace(
            unsafe,
            snapshot={"airports": ["LED"], "destinations": ["CDG"]},
        ),
        replace(
            unsafe,
            id=UUID("22222222-9999-9999-9999-999999999999"),
            fingerprint="sha256:" + "b" * 64,
            snapshot={"airports": ["LED"], "destinations": ["ORY"]},
        ),
    )
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def append(candidate: NewAgentRunScopeSnapshot) -> str:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            try:
                stored = await AgentOperationRepository(session).append_scope_snapshot(candidate)
                await session.commit()
                return f"stored:{stored.fingerprint}"
            except AgentOperationConflict as error:
                await session.rollback()
                return f"conflict:{error.code}"

    outcomes = await asyncio.gather(*(append(candidate) for candidate in candidates))
    assert sum(outcome.startswith("stored:") for outcome in outcomes) == 1
    assert outcomes.count("conflict:agent_run_scope_conflict") == 1
    async with sessions() as session:
        assert (
            await session.execute(select(func.count()).select_from(agent_run_scope_snapshots_table))
        ).scalar_one() == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_review_exact_start_and_nonfinal_poll_use_owned_operation_handoff(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "typed-operation-handoff.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=3)
    poll_one_id = UUID("88888888-7777-7777-7777-777777777777")
    poll_two_id = UUID("99999999-7777-7777-7777-777777777777")
    workflow = {"origin": "LED", "destination": "CDG", "departure_date": "2026-09-01"}

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        scheduler = OperationScheduler(repository)
        root = await scheduler.materialize(
            _operation_spec(immutable_input={**workflow, "phase": "start"}, logical_input=workflow)
        )
        poll_one = await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=poll_one_id,
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={**workflow, "poll_round": 1},
                    logical_input=workflow,
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=root.id,
            )
        )
        poll_two = await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=poll_two_id,
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={**workflow, "poll_round": 2},
                    logical_input=workflow,
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=root.id,
            )
        )
        root_lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-root",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert root_lease is not None and root_lease.operation.id == root.id
        with pytest.raises(AgentOperationConflict) as fake_offer:
            await repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=root.id,
                worker_id="worker-root",
                result_type=AgentOperationResultType.CONFIRMED_OFFER,
                result_id=EVIDENCE_RESULT_ID,
                now=NOW + timedelta(seconds=2),
            )
        assert fake_offer.value.code == "agent_operation_result_incompatible"

        completed_root = await repository.mark_operation_succeeded(
            household_id=HOUSEHOLD_ID,
            operation_id=root.id,
            worker_id="worker-root",
            result_type=AgentOperationResultType.OPERATION,
            result_id=poll_one.id,
            now=NOW + timedelta(seconds=2),
        )
        assert completed_root.result_id == poll_one.id

        first_poll_lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-poll",
            now=NOW + timedelta(seconds=3),
            lease_seconds=30,
        )
        assert first_poll_lease is not None and first_poll_lease.operation.id == poll_one.id
        completed_poll = await repository.mark_operation_succeeded(
            household_id=HOUSEHOLD_ID,
            operation_id=poll_one.id,
            worker_id="worker-poll",
            result_type=AgentOperationResultType.OPERATION,
            result_id=poll_two.id,
            now=NOW + timedelta(seconds=4),
        )
        assert completed_poll.result_id == poll_two.id
        await session.commit()

    await engine.dispose()


@pytest.mark.anyio
async def test_review_final_exact_poll_requires_existing_same_run_and_stage_confirmed_evidence(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "typed-confirmed-result.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=2)
    poll_id = UUID("88888888-7777-7777-7777-777777777777")
    workflow = {"origin": "LED", "destination": "CDG", "departure_date": "2026-09-01"}

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        scheduler = OperationScheduler(repository)
        root = await scheduler.materialize(_operation_spec(logical_input=workflow))
        poll = await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=poll_id,
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={**workflow, "poll_round": 1},
                    logical_input=workflow,
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=root.id,
            )
        )
        await repository.mark_operation_skipped(
            household_id=HOUSEHOLD_ID,
            operation_id=root.id,
            error_code="test_root_already_started",
            now=NOW + timedelta(seconds=1),
        )
        lease = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-poll",
            now=NOW + timedelta(seconds=2),
            lease_seconds=30,
        )
        assert lease is not None and lease.operation.id == poll.id

        with pytest.raises(AgentOperationConflict) as missing:
            await repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=poll.id,
                worker_id="worker-poll",
                result_type=AgentOperationResultType.CONFIRMED_OFFER,
                result_id=EVIDENCE_RESULT_ID,
                now=NOW + timedelta(seconds=3),
            )
        assert missing.value.code == "agent_operation_result_not_found"

        evidence = await AgentEvidenceRepository(session).append_confirmed_evidence(
            _confirmed_result()
        )
        completed = await repository.mark_operation_succeeded(
            household_id=HOUSEHOLD_ID,
            operation_id=poll.id,
            worker_id="worker-poll",
            result_type=AgentOperationResultType.CONFIRMED_OFFER,
            result_id=evidence.id,
            now=NOW + timedelta(seconds=3),
        )
        assert completed.result_id == evidence.id
        await session.commit()

    await engine.dispose()


@pytest.mark.anyio
async def test_review_result_reference_rejects_self_cross_run_and_incompatible_kind(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "typed-result-negative.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=2)
    await _lease_operation(sessions, worker_id="worker-result")

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        with pytest.raises(AgentOperationConflict) as self_ref:
            await repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-result",
                result_type=AgentOperationResultType.OPERATION,
                result_id=OPERATION_ID,
                now=NOW + timedelta(seconds=1),
            )
        assert self_ref.value.code == "agent_operation_result_invalid"

        with pytest.raises(AgentOperationConflict) as incompatible:
            await repository.mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-result",
                result_type=AgentOperationResultType.SCOPE_SNAPSHOT,
                result_id=UUID("11111111-9999-9999-9999-999999999999"),
                now=NOW + timedelta(seconds=1),
            )
        assert incompatible.value.code == "agent_operation_result_incompatible"

    cross_source_id = UUID("cccccccc-7777-7777-7777-777777777777")
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(
            replace(
                _operation_spec(
                    operation_id=cross_source_id,
                    kind=AgentOperationKind.EXACT_POLL,
                    immutable_input={
                        "origin": "LED",
                        "destination": "CDG",
                        "departure_date": "2026-09-01",
                        "poll_round": 1,
                    },
                    consumes_logical_unit=False,
                ),
                logical_root_operation_id=OPERATION_ID,
            )
        )
        lease = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-result-cross",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        await session.commit()
        assert lease is not None and lease.operation.id == cross_source_id

    second_ids = {
        "plan": UUID("aaaaaaaa-2222-2222-2222-222222222222"),
        "revision": UUID("aaaaaaaa-3333-3333-3333-333333333333"),
        "approval": UUID("aaaaaaaa-4444-4444-4444-444444444444"),
        "run": UUID("aaaaaaaa-5555-5555-5555-555555555555"),
        "stage": UUID("aaaaaaaa-6666-6666-6666-666666666666"),
    }
    await _seed_run_and_stage(
        sessions,
        plan_id=second_ids["plan"],
        revision_id=second_ids["revision"],
        approval_id=second_ids["approval"],
        run_id=second_ids["run"],
        stage_id=second_ids["stage"],
        logical_budget=1,
        http_budget=1,
        idempotency_key="execute:cross-result",
    )
    async with sessions() as session:
        cross_run = await AgentEvidenceRepository(session).append_confirmed_evidence(
            replace(
                _confirmed_result(),
                id=UUID("bbbbbbbb-eeee-eeee-eeee-eeeeeeeeeeee"),
                run_id=second_ids["run"],
                stage_id=second_ids["stage"],
                fingerprint="sha256:" + "c" * 64,
            )
        )
        with pytest.raises(AgentOperationConflict) as hidden:
            await AgentOperationRepository(session).mark_operation_succeeded(
                household_id=HOUSEHOLD_ID,
                operation_id=cross_source_id,
                worker_id="worker-result-cross",
                result_type=AgentOperationResultType.CONFIRMED_OFFER,
                result_id=cross_run.id,
                now=NOW + timedelta(seconds=1),
            )
        assert hidden.value.code == "agent_operation_result_not_found"

    await engine.dispose()


@pytest.mark.anyio
async def test_review_http_reservation_is_idempotent_per_claim_attempt_and_returns_identity(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-idempotent.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    await _lease_operation(sessions, worker_id="worker-http")
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW + timedelta(seconds=1),
    )

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        first = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=2),
            circuit_permit=permit,
        )
        repeated = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=1,
            now=NOW + timedelta(seconds=3),
            circuit_permit=permit,
        )
        await session.commit()

        assert first.status is repeated.status is AttemptReservationStatus.RESERVED
        assert first.reservation_id is not None
        assert repeated.reservation_id == first.reservation_id
        assert not first.reused
        assert repeated.reused

    async with sessions() as session:
        attempts = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().all()
        )
        run_consumed = (
            await session.execute(
                select(agent_plan_runs_table.c.http_attempts_consumed).where(
                    agent_plan_runs_table.c.id == str(RUN_ID)
                )
            )
        ).scalar_one()
        assert len(attempts) == 1
        assert attempts[0]["operation_attempt_number"] == 1
        assert run_consumed == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_review_reservation_kind_is_derived_from_operation_and_claim_attempt(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-kind.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=3)
    await _lease_operation(sessions, worker_id="worker-a", lease_seconds=10)
    first_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-a",
        now=NOW + timedelta(seconds=1),
    )

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        with pytest.raises(AgentOperationConflict) as invalid_kind:
            await repository.reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.POLL,
                provider_rpm=20,
                now=NOW + timedelta(seconds=2),
                circuit_permit=first_permit,
            )
        assert invalid_kind.value.code == "agent_attempt_kind_invalid"
        first = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-a",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=2),
            circuit_permit=first_permit,
        )
        await session.commit()
        assert first.reservation_id is not None

    async with sessions() as session:
        reclaimed = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=11),
            lease_seconds=30,
        )
        await session.commit()
        assert reclaimed is not None
        assert reclaimed.operation.attempt_count == 2

    retry_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=12),
    )
    async with sessions() as session:
        retry = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-b",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(seconds=13),
            circuit_permit=retry_permit,
        )
        await session.commit()
        assert retry.reservation_id is not None
        assert retry.reservation_id != first.reservation_id

    async with sessions() as session:
        attempts = (
            await session.execute(
                select(
                    agent_provider_http_attempts_table.c.operation_attempt_number,
                    agent_provider_http_attempts_table.c.attempt_kind,
                ).order_by(agent_provider_http_attempts_table.c.operation_attempt_number)
            )
        ).all()
        assert attempts == [(1, "start"), (2, "retry")]

    await engine.dispose()


@pytest.mark.anyio
async def test_review_reservation_and_permit_consumption_honor_caller_rollback(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-rollback.db")
    await _seed_operation(sessions, logical_budget=1, http_budget=1)
    await _lease_operation(sessions, worker_id="worker-http")
    permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-http",
        now=NOW + timedelta(seconds=1),
    )

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
            circuit_permit=permit,
        )
        assert result.status is AttemptReservationStatus.RESERVED
        await session.rollback()

    async with sessions() as session:
        repository = AgentOperationRepository(session)
        retried = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-http",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
            circuit_permit=permit,
        )
        await session.commit()
        assert retried.status is AttemptReservationStatus.RESERVED
        assert not retried.reused

    await engine.dispose()


@pytest.mark.anyio
async def test_review_closed_permit_is_rechecked_when_another_attempt_opens_circuit(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-closed-open-race.db")
    await _seed_run_and_stage(sessions, logical_budget=2, http_budget=2)
    other_id = UUID("88888888-7777-7777-7777-777777777777")
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(_operation_spec())
        await scheduler.materialize(
            _operation_spec(
                operation_id=other_id,
                immutable_input={"origin": "LED", "destination": "ORY"},
                logical_input={"origin": "LED", "destination": "ORY"},
            )
        )
        repository = AgentOperationRepository(session)
        first = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        second = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        await session.commit()
        assert first is not None and second is not None

    permit_a = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-a",
        now=NOW + timedelta(seconds=2),
    )
    permit_b = await _issue_permit(
        sessions,
        operation_id=other_id,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=2),
    )
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        reservation_b = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=other_id,
            worker_id="worker-b",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
            circuit_permit=permit_b,
        )
        assert reservation_b.reservation_id is not None
        opened = await repository.record_circuit_failure(
            circuit_permit=permit_b,
            reservation_id=reservation_b.reservation_id,
            transient=True,
            failure_threshold=1,
            cooldown_seconds=5,
            now=NOW + timedelta(seconds=4),
        )
        assert opened.state.value == "open"
        with pytest.raises(AgentOperationConflict) as stale:
            await repository.reserve_http_attempt(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=OPERATION_ID,
                worker_id="worker-a",
                provider_id="aviasales_search",
                attempt_kind=AttemptKind.START,
                provider_rpm=20,
                now=NOW + timedelta(seconds=4),
                circuit_permit=permit_a,
            )
        assert stale.value.code == "agent_circuit_permit_stale"
        await session.commit()

    await engine.dispose()


@pytest.mark.anyio
async def test_review_half_open_permit_is_one_shot_and_late_owner_cannot_close_takeover(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-takeover.db")
    await _seed_run_and_stage(sessions, logical_budget=2, http_budget=3)
    probe_id = UUID("88888888-7777-7777-7777-777777777777")
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(_operation_spec())
        await scheduler.materialize(
            _operation_spec(
                operation_id=probe_id,
                immutable_input={"origin": "LED", "destination": "ORY"},
                logical_input={"origin": "LED", "destination": "ORY"},
            )
        )
        opener = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-open",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        await session.commit()
        assert opener is not None and opener.operation.id == OPERATION_ID

    opening_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-open",
        now=NOW + timedelta(seconds=2),
    )
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        opening_reservation = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-open",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
            circuit_permit=opening_permit,
        )
        assert opening_reservation.reservation_id is not None
        await repository.record_circuit_failure(
            circuit_permit=opening_permit,
            reservation_id=opening_reservation.reservation_id,
            transient=True,
            failure_threshold=1,
            cooldown_seconds=5,
            now=NOW + timedelta(seconds=4),
        )
        await repository.mark_operation_failed(
            household_id=HOUSEHOLD_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-open",
            error_code="provider_network",
            now=NOW + timedelta(seconds=4),
        )
        await session.commit()

    async with sessions() as session:
        claimed_a = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-a",
            now=NOW + timedelta(seconds=10),
            lease_seconds=10,
        )
        await session.commit()
        assert claimed_a is not None and claimed_a.operation.id == probe_id

    permit_a = await _issue_permit(
        sessions,
        operation_id=probe_id,
        worker_id="worker-a",
        now=NOW + timedelta(seconds=10),
        probe_lease_seconds=5,
        expected_status=CircuitPermitStatus.HALF_OPEN_PROBE,
    )
    async with sessions() as session:
        with pytest.raises(AgentOperationConflict) as duplicate:
            await AgentOperationRepository(session).acquire_circuit_permit(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=probe_id,
                provider_id="aviasales_search",
                worker_id="worker-a",
                now=NOW + timedelta(seconds=11),
                probe_lease_seconds=5,
            )
        assert duplicate.value.code == "agent_circuit_permit_already_issued"

    async with sessions() as session:
        reservation_a = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=probe_id,
            worker_id="worker-a",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=11),
            circuit_permit=permit_a,
        )
        await session.commit()
        assert reservation_a.reservation_id is not None

    async with sessions() as session:
        claimed_b = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-b",
            now=NOW + timedelta(seconds=21),
            lease_seconds=30,
        )
        await session.commit()
        assert claimed_b is not None and claimed_b.operation.attempt_count == 2

    permit_b = await _issue_permit(
        sessions,
        operation_id=probe_id,
        worker_id="worker-b",
        now=NOW + timedelta(seconds=22),
        expected_status=CircuitPermitStatus.HALF_OPEN_PROBE,
    )
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        reservation_b = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=probe_id,
            worker_id="worker-b",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.RETRY,
            provider_rpm=20,
            now=NOW + timedelta(seconds=23),
            circuit_permit=permit_b,
        )
        assert reservation_b.reservation_id is not None
        with pytest.raises(AgentOperationConflict) as late_a:
            await repository.record_circuit_success(
                circuit_permit=permit_a,
                reservation_id=reservation_a.reservation_id,
                now=NOW + timedelta(seconds=24),
            )
        assert late_a.value.code == "agent_circuit_permit_stale"
        closed = await repository.record_circuit_success(
            circuit_permit=permit_b,
            reservation_id=reservation_b.reservation_id,
            now=NOW + timedelta(seconds=24),
        )
        assert closed.state.value == "closed"
        assert closed.consecutive_transient_failures == 0
        await session.commit()

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("http_budget", "provider_rpm", "expected_status"),
    (
        (1, 20, AttemptReservationStatus.BUDGET_EXHAUSTED),
        (2, 1, AttemptReservationStatus.RATE_LIMITED),
    ),
)
async def test_review_rate_or_budget_denial_does_not_consume_half_open_probe(
    tmp_path: Path,
    http_budget: int,
    provider_rpm: int,
    expected_status: AttemptReservationStatus,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"circuit-denial-{expected_status.value}.db",
    )
    await _seed_run_and_stage(sessions, logical_budget=2, http_budget=http_budget)
    probe_id = UUID("88888888-7777-7777-7777-777777777777")
    async with sessions() as session:
        scheduler = OperationScheduler(AgentOperationRepository(session))
        await scheduler.materialize(_operation_spec())
        await scheduler.materialize(
            _operation_spec(
                operation_id=probe_id,
                immutable_input={"origin": "LED", "destination": "ORY"},
                logical_input={"origin": "LED", "destination": "ORY"},
            )
        )
        opener = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-open",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        await session.commit()
        assert opener is not None
    opening_permit = await _issue_permit(
        sessions,
        operation_id=OPERATION_ID,
        worker_id="worker-open",
        now=NOW + timedelta(seconds=2),
    )
    async with sessions() as session:
        repository = AgentOperationRepository(session)
        opening = await repository.reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-open",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=20,
            now=NOW + timedelta(seconds=3),
            circuit_permit=opening_permit,
        )
        assert opening.reservation_id is not None
        await repository.record_circuit_failure(
            circuit_permit=opening_permit,
            reservation_id=opening.reservation_id,
            transient=True,
            failure_threshold=1,
            cooldown_seconds=5,
            now=NOW + timedelta(seconds=4),
        )
        await repository.mark_operation_failed(
            household_id=HOUSEHOLD_ID,
            operation_id=OPERATION_ID,
            worker_id="worker-open",
            error_code="provider_network",
            now=NOW + timedelta(seconds=4),
        )
        probe = await repository.claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-probe",
            now=NOW + timedelta(seconds=10),
            lease_seconds=30,
        )
        await session.commit()
        assert probe is not None and probe.operation.id == probe_id
    probe_permit = await _issue_permit(
        sessions,
        operation_id=probe_id,
        worker_id="worker-probe",
        now=NOW + timedelta(seconds=10),
        expected_status=CircuitPermitStatus.HALF_OPEN_PROBE,
    )
    async with sessions() as session:
        denied = await AgentOperationRepository(session).reserve_http_attempt(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            operation_id=probe_id,
            worker_id="worker-probe",
            provider_id="aviasales_search",
            attempt_kind=AttemptKind.START,
            provider_rpm=provider_rpm,
            now=NOW + timedelta(seconds=11),
            circuit_permit=probe_permit,
        )
        assert denied.status is expected_status
        row = (
            await session.execute(
                select(
                    agent_run_operations_table.c.circuit_permit_consumed_at,
                    agent_run_operations_table.c.circuit_permit_generation,
                ).where(agent_run_operations_table.c.id == str(probe_id))
            )
        ).one()
        state = (
            (
                await session.execute(
                    select(agent_provider_circuit_state_table).where(
                        agent_provider_circuit_state_table.c.provider_id == "aviasales_search"
                    )
                )
            )
            .mappings()
            .one()
        )
        assert row.circuit_permit_consumed_at is None
        assert row.circuit_permit_generation == state["generation"]

    await engine.dispose()


@pytest.mark.anyio
async def test_review_provider_neutral_operation_cannot_acquire_an_http_permit(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "neutral-no-http.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)
    async with sessions() as session:
        operation = await OperationScheduler(AgentOperationRepository(session)).materialize(
            replace(
                _operation_spec(
                    kind=AgentOperationKind.RANKING,
                    immutable_input={"ordered": [str(EVIDENCE_RESULT_ID)], "version": "rank-v1"},
                    logical_input={"value": 1},
                    consumes_logical_unit=False,
                ),
                provider_id=None,
                private_continuation=None,
                logical_root_operation_id=None,
            )
        )
        lease = await AgentOperationRepository(session).claim_next_operation(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            worker_id="worker-neutral",
            now=NOW + timedelta(seconds=1),
            lease_seconds=30,
        )
        assert lease is not None and lease.operation.id == operation.id
        with pytest.raises(AgentOperationConflict) as denied:
            await AgentOperationRepository(session).acquire_circuit_permit(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                operation_id=operation.id,
                provider_id="aviasales_search",
                worker_id="worker-neutral",
                now=NOW + timedelta(seconds=2),
                probe_lease_seconds=30,
            )
        assert denied.value.code == "agent_operation_not_networked"

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "unsafe_value",
    (
        "http://signed.example/value",
        "  HtTpS://signed.example/value",
        "mailto:person@example.test",
        "data:text/plain,secret",
        "javascript:alert(1)",
        "//signed.example/value",
        "  //signed.example/value",
    ),
)
async def test_review_operation_context_rejects_all_uri_forms(
    tmp_path: Path,
    unsafe_value: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-uri.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)
    async with sessions() as session:
        with pytest.raises(ValueError, match="unsafe field"):
            await OperationScheduler(AgentOperationRepository(session)).materialize(
                _operation_spec(immutable_input={"value": unsafe_value})
            )
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    (
        {"apiKey": "secret"},
        {"api-key": "secret"},
        {"credentials": [{"value": "secret"}]},
        {"accessKey": "secret"},
        {"email": "person@example.test"},
        {"phone": "+7 999 111-22-33"},
        {"traveler": {"contact": "person@example.test"}},
        {"unexpected_safe_key": "value"},
    ),
)
async def test_review_operation_context_uses_explicit_allowlist_and_rejects_aliases(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-allowlist.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)
    async with sessions() as session:
        with pytest.raises(ValueError, match=r"unsafe|not allowed"):
            await OperationScheduler(AgentOperationRepository(session)).materialize(
                _operation_spec(immutable_input={"value": 1, **payload})
            )
    await engine.dispose()


@pytest.mark.anyio
async def test_review_operation_context_accepts_current_typed_route_and_private_fields(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "operation-safe-context.db")
    await _seed_run_and_stage(sessions, logical_budget=1, http_budget=1)
    async with sessions() as session:
        stored = await OperationScheduler(AgentOperationRepository(session)).materialize(
            replace(
                _operation_spec(
                    immutable_input={
                        "value": 1,
                        "origin": "LED",
                        "destination": "CDG",
                        "route": ["LED", "CDG"],
                        "departure_date": "2026-09-01",
                        "return_date": None,
                        "passengers": {"adults": 1, "children": 0, "infants": 0},
                    },
                    logical_input={
                        "origin": "LED",
                        "destination": "CDG",
                        "departure_date": "2026-09-01",
                    },
                ),
                private_continuation={
                    "search_session": "opaque-session",
                    "search_id": "opaque-id",
                    "cursor": 17,
                },
            )
        )
        await session.commit()
        assert stored.immutable_input["route"] == ("LED", "CDG")

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


async def _issue_permit(
    sessions: async_sessionmaker[AsyncSession],
    *,
    operation_id: UUID,
    worker_id: str,
    now: datetime,
    run_id: UUID = RUN_ID,
    probe_lease_seconds: int = 30,
    expected_status: CircuitPermitStatus = CircuitPermitStatus.ALLOWED,
) -> ServerPrivateCircuitPermit:
    async with sessions() as session:
        result = await AgentOperationRepository(session).acquire_circuit_permit(
            household_id=HOUSEHOLD_ID,
            run_id=run_id,
            operation_id=operation_id,
            provider_id="aviasales_search",
            worker_id=worker_id,
            now=now,
            probe_lease_seconds=probe_lease_seconds,
        )
        await session.commit()
        assert result.status is expected_status
        assert result.permit is not None
        return result.permit


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


def _confirmed_result() -> NewAgentConfirmedOfferEvidence:
    return NewAgentConfirmedOfferEvidence(
        id=EVIDENCE_RESULT_ID,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        stage_id=STAGE_ID,
        provider_id="aviasales_search",
        source="exact_search",
        observed_at=NOW,
        freshness=Freshness.LIVE_OBSERVED,
        passengers=1,
        passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
        amount_minor=20_000,
        currency="RUB",
        itinerary_evidence={"segments": [{"origin": "LED", "destination": "CDG"}]},
        protection_status=ProtectionStatus.UNKNOWN,
        baggage_status=None,
        transfer_status=None,
        visa_status=None,
        fingerprint="sha256:" + "e" * 64,
        created_at=NOW,
    )


def test_fingerprint_helpers_are_used_by_operation_fixture() -> None:
    spec = _operation_spec()
    assert operation_fingerprint(spec.kind, spec.immutable_input).startswith("sha256:")
    assert logical_workflow_fingerprint("exact_search", spec.logical_workflow_input).startswith(
        "sha256:"
    )
