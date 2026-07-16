from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.domain.agent_evidence import ProtectionStatus
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    _OPERATION_RESULT_MATRIX,
    AgentEvidenceError,
    AgentEvidenceRepository,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentPlanApprovalSnapshot,
    AgentPlanRepository,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    NewAgentAnalysisSnapshot,
    NewAgentConfirmedOfferEvidence,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    NewAgentPlanStage,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import mapper_registry

HOUSEHOLD_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
HOUSEHOLD_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("22222222-2222-2222-2222-222222222222")
SESSION_A = UUID("33333333-3333-3333-3333-333333333333")
SESSION_B = UUID("44444444-4444-4444-4444-444444444444")
RUN_A1 = UUID("50000000-0000-0000-0000-000000000001")
RUN_A2 = UUID("50000000-0000-0000-0000-000000000002")
RUN_B1 = UUID("50000000-0000-0000-0000-000000000003")
STAGE_A1 = UUID("60000000-0000-0000-0000-000000000001")
STAGE_A2 = UUID("60000000-0000-0000-0000-000000000002")
STAGE_B1 = UUID("60000000-0000-0000-0000-000000000003")
EVIDENCE_A1 = UUID("70000000-0000-0000-0000-000000000001")
EVIDENCE_A2 = UUID("70000000-0000-0000-0000-000000000002")
EVIDENCE_B1 = UUID("70000000-0000-0000-0000-000000000003")
SNAPSHOT_ID = UUID("80000000-0000-0000-0000-000000000001")
SERIES_HASH = "sha256:" + "a" * 64
OTHER_SERIES_HASH = "sha256:" + "b" * 64
NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


@pytest.mark.anyio
async def test_exact_confirmed_history_spans_runs_and_is_strictly_isolated(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "history-query.db")
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_A,
        user_id=USER_A,
        session_id=SESSION_A,
        run_id=RUN_A1,
        stage_id=STAGE_A1,
        ordinal=1,
    )
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_A,
        user_id=USER_A,
        session_id=SESSION_A,
        run_id=RUN_A2,
        stage_id=STAGE_A2,
        ordinal=2,
    )
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_B,
        user_id=USER_B,
        session_id=SESSION_B,
        run_id=RUN_B1,
        stage_id=STAGE_B1,
        ordinal=3,
    )

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        first = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_A1,
                household_id=HOUSEHOLD_A,
                run_id=RUN_A1,
                stage_id=STAGE_A1,
                observed_at=NOW - timedelta(days=3),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="1",
            )
        )
        await repository.append_confirmed_evidence(
            _confirmed(
                id_value=UUID("70000000-0000-0000-0000-000000000004"),
                household_id=HOUSEHOLD_A,
                run_id=RUN_A2,
                stage_id=STAGE_A2,
                observed_at=NOW - timedelta(days=4),
                history_series_hash=None,
                fingerprint_seed="2",
            )
        )
        await repository.append_confirmed_evidence(
            _confirmed(
                id_value=UUID("70000000-0000-0000-0000-000000000005"),
                household_id=HOUSEHOLD_A,
                run_id=RUN_A2,
                stage_id=STAGE_A2,
                observed_at=NOW - timedelta(days=2),
                history_series_hash=OTHER_SERIES_HASH,
                fingerprint_seed="3",
            )
        )
        await repository.append_confirmed_evidence(
            _confirmed(
                id_value=UUID("70000000-0000-0000-0000-000000000006"),
                household_id=HOUSEHOLD_A,
                run_id=RUN_A2,
                stage_id=STAGE_A2,
                observed_at=NOW - timedelta(days=2),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="4",
                source="manual_confirmation",
            )
        )
        second = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_A2,
                household_id=HOUSEHOLD_A,
                run_id=RUN_A2,
                stage_id=STAGE_A2,
                observed_at=NOW - timedelta(days=1),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="5",
            )
        )
        other_household = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_B1,
                household_id=HOUSEHOLD_B,
                run_id=RUN_B1,
                stage_id=STAGE_B1,
                observed_at=NOW - timedelta(days=5),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="6",
            )
        )
        await session.commit()

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        history = await repository.list_confirmed_history(HOUSEHOLD_A, SERIES_HASH)
        cutoff = await repository.list_confirmed_history(
            HOUSEHOLD_A,
            SERIES_HASH,
            observed_before=second.observed_at,
        )
        household_b = await repository.list_confirmed_history(HOUSEHOLD_B, SERIES_HASH)
        legacy = await repository.get_confirmed_evidence(
            HOUSEHOLD_A,
            UUID("70000000-0000-0000-0000-000000000004"),
        )

    assert tuple(record.id for record in history) == (first.id, second.id)
    assert tuple(record.id for record in cutoff) == (first.id,)
    assert tuple(record.id for record in household_b) == (other_household.id,)
    assert legacy is not None and legacy.history_series_hash is None
    await engine.dispose()


@pytest.mark.anyio
async def test_history_series_hash_is_validated_before_insert(tmp_path: Path) -> None:
    engine, sessions = await _session_factory(tmp_path, "history-hash.db")
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_A,
        user_id=USER_A,
        session_id=SESSION_A,
        run_id=RUN_A1,
        stage_id=STAGE_A1,
        ordinal=1,
    )

    async with sessions() as session:
        with pytest.raises(ValueError, match="history_series_hash"):
            await AgentEvidenceRepository(session).append_confirmed_evidence(
                _confirmed(
                    id_value=EVIDENCE_A1,
                    household_id=HOUSEHOLD_A,
                    run_id=RUN_A1,
                    stage_id=STAGE_A1,
                    observed_at=NOW,
                    history_series_hash="not-a-hash",
                    fingerprint_seed="1",
                )
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_analysis_snapshot_is_immutable_idempotent_and_household_scoped(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "analysis-snapshot.db")
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_A,
        user_id=USER_A,
        session_id=SESSION_A,
        run_id=RUN_A1,
        stage_id=STAGE_A1,
        ordinal=1,
    )
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_A,
        user_id=USER_A,
        session_id=SESSION_A,
        run_id=RUN_A2,
        stage_id=STAGE_A2,
        ordinal=2,
    )
    await _seed_run(
        sessions,
        household_id=HOUSEHOLD_B,
        user_id=USER_B,
        session_id=SESSION_B,
        run_id=RUN_B1,
        stage_id=STAGE_B1,
        ordinal=3,
    )

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        first = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_A1,
                household_id=HOUSEHOLD_A,
                run_id=RUN_A1,
                stage_id=STAGE_A1,
                observed_at=NOW - timedelta(days=2),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="1",
            )
        )
        previous_run = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_A2,
                household_id=HOUSEHOLD_A,
                run_id=RUN_A2,
                stage_id=STAGE_A2,
                observed_at=NOW - timedelta(days=1),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="2",
            )
        )
        other_household = await repository.append_confirmed_evidence(
            _confirmed(
                id_value=EVIDENCE_B1,
                household_id=HOUSEHOLD_B,
                run_id=RUN_B1,
                stage_id=STAGE_B1,
                observed_at=NOW - timedelta(days=1),
                history_series_hash=SERIES_HASH,
                fingerprint_seed="3",
            )
        )
        snapshot = await repository.create_analysis_snapshot(
            NewAgentAnalysisSnapshot(
                id=SNAPSHOT_ID,
                household_id=HOUSEHOLD_A,
                run_id=RUN_A1,
                source_evidence_ids=(first.id, previous_run.id),
                analysis={
                    "version": "fare-analysis-v1",
                    "buy_timing": {"status": "insufficient_data", "sample_count": 2},
                },
                created_at=NOW,
            )
        )
        duplicate = await repository.create_analysis_snapshot(
            NewAgentAnalysisSnapshot(
                id=UUID("80000000-0000-0000-0000-000000000002"),
                household_id=HOUSEHOLD_A,
                run_id=RUN_A1,
                source_evidence_ids=(first.id, previous_run.id),
                analysis={
                    "buy_timing": {"sample_count": 2, "status": "insufficient_data"},
                    "version": "fare-analysis-v1",
                },
                created_at=NOW + timedelta(seconds=1),
            )
        )
        await session.commit()

        assert duplicate.id == snapshot.id
        assert duplicate.fingerprint == snapshot.fingerprint
        assert duplicate.source_evidence_ids == (first.id, previous_run.id)
        assert duplicate.analysis["version"] == "fare-analysis-v1"

        with pytest.raises(AgentEvidenceError) as conflict:
            await repository.create_analysis_snapshot(
                NewAgentAnalysisSnapshot(
                    id=UUID("80000000-0000-0000-0000-000000000003"),
                    household_id=HOUSEHOLD_A,
                    run_id=RUN_A1,
                    source_evidence_ids=(first.id, previous_run.id),
                    analysis={"version": "fare-analysis-v2"},
                    created_at=NOW + timedelta(seconds=2),
                )
            )
        assert conflict.value.code == "agent_analysis_snapshot_conflict"

        with pytest.raises(AgentEvidenceError) as ownership:
            await repository.create_analysis_snapshot(
                NewAgentAnalysisSnapshot(
                    id=UUID("80000000-0000-0000-0000-000000000004"),
                    household_id=HOUSEHOLD_A,
                    run_id=RUN_A2,
                    source_evidence_ids=(other_household.id,),
                    analysis={"version": "fare-analysis-v1"},
                    created_at=NOW + timedelta(seconds=2),
                )
            )
        assert ownership.value.code == "agent_analysis_evidence_not_found"

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        stored = await repository.get_analysis_snapshot_for_run(HOUSEHOLD_A, RUN_A1)
        hidden = await repository.get_analysis_snapshot_for_run(HOUSEHOLD_B, RUN_A1)

    assert stored is not None and stored.id == SNAPSHOT_ID
    assert hidden is None
    await engine.dispose()


def test_analysis_operation_has_a_distinct_result_type() -> None:
    assert _OPERATION_RESULT_MATRIX[AgentOperationKind.ANALYSIS] == frozenset(
        {AgentOperationResultType.ANALYSIS_SNAPSHOT}
    )
    assert (
        AgentOperationResultType.RANKING_SNAPSHOT
        not in _OPERATION_RESULT_MATRIX[AgentOperationKind.ANALYSIS]
    )


async def _session_factory(
    tmp_path: Path,
    filename: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_database_engine(f"sqlite+aiosqlite:///{(tmp_path / filename).as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_run(
    sessions: async_sessionmaker[AsyncSession],
    *,
    household_id: UUID,
    user_id: UUID,
    session_id: UUID,
    run_id: UUID,
    stage_id: UUID,
    ordinal: int,
) -> None:
    plan_id = UUID(f"10000000-0000-0000-0000-{ordinal:012d}")
    revision_id = UUID(f"20000000-0000-0000-0000-{ordinal:012d}")
    approval_id = UUID(f"30000000-0000-0000-0000-{ordinal:012d}")
    async with sessions() as session:
        revision = await AgentPlanRepository(session).create_plan(
            NewAgentPlan(
                id=plan_id,
                household_id=household_id,
                created_by_user_id=user_id,
                created_at=NOW,
            ),
            NewAgentPlanRevision(
                id=revision_id,
                state="awaiting_approval",
                plan={"route": ["LED", "CDG"]},
                scope_snapshot={"airports": ["LED", "CDG"]},
                capability_snapshot={"provider": "aviasales_search", "version": "v1"},
                cost_model_snapshot={"version": "v1"},
                parser_version="parser-v1",
                planner_version="planner-v1",
                estimated_calendar_searches=0,
                estimated_exact_searches=1,
                estimated_logical_operations=1,
                estimated_http_attempts=4,
                estimated_deadline_seconds=600,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            ),
        )
        await AgentRunRepository(session).approve_and_execute(
            approval=NewAgentPlanApproval(
                id=approval_id,
                household_id=household_id,
                revision_id=revision_id,
                approved_by_user_id=user_id,
                approved_at=NOW,
                expires_at=NOW + timedelta(minutes=30),
                snapshot=AgentPlanApprovalSnapshot(
                    revision_content_hash=revision.content_hash,
                    approved_by_session_id=session_id,
                    approved_budget={"logical_operations": 1, "http_attempts": 4},
                    approved_strategies=("direct",),
                    risk_warning_versions={},
                ),
            ),
            run=NewAgentPlanRun(
                id=run_id,
                execute_idempotency_key=f"execute:history:{ordinal}",
                created_at=NOW,
                deadline_at=NOW + timedelta(minutes=10),
            ),
        )
        await AgentOperationRepository(session).create_stage(
            NewAgentPlanStage(
                id=stage_id,
                household_id=household_id,
                run_id=run_id,
                kind=AgentPlanStageKind.EXACT_SEARCH,
                status=AgentStageStatus.PENDING,
                created_at=NOW,
            )
        )
        await session.commit()


def _confirmed(
    *,
    id_value: UUID,
    household_id: UUID,
    run_id: UUID,
    stage_id: UUID,
    observed_at: datetime,
    history_series_hash: str | None,
    fingerprint_seed: str,
    source: str = "exact_search",
) -> NewAgentConfirmedOfferEvidence:
    segment_ref = f"segment-{id_value.hex[:12]}"
    return NewAgentConfirmedOfferEvidence(
        id=id_value,
        household_id=household_id,
        run_id=run_id,
        stage_id=stage_id,
        provider_id="aviasales_search",
        source=source,
        observed_at=observed_at,
        freshness=Freshness.LIVE_OBSERVED,
        passengers=1,
        passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
        amount_minor=20_000,
        currency="RUB",
        itinerary_evidence={
            "leg_ordinal": 0,
            "search_role": "base",
            "origin": "LED",
            "destination": "CDG",
            "departure_date": "2026-09-01",
            "return_date": None,
            "passenger_mix": {"adults": 1, "children": 0, "infants": 0},
            "price_basis": PriceBasis.PROVIDER_SINGLE_ADULT_TICKET.value,
            "segments": [
                {
                    "segment_ref": segment_ref,
                    "origin": "LED",
                    "destination": "CDG",
                    "depart_at": "2026-09-01 08:00",
                    "arrive_at": "2026-09-01 10:00",
                    "depart_at_utc": "2026-09-01T08:00:00+00:00",
                    "arrive_at_utc": "2026-09-01T10:00:00+00:00",
                    "carrier": "FV",
                    "flight_number": "FV100",
                }
            ],
            "seller": "Fixture seller",
            "ticket_structure": "provider_ticket",
            "stops": 0,
        },
        protection_status=ProtectionStatus.UNKNOWN,
        baggage_status=None,
        transfer_status=None,
        visa_status=None,
        history_series_hash=history_series_hash,
        fingerprint="sha256:" + fingerprint_seed * 64,
        created_at=NOW,
    )
