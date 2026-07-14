from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.domain.agent_evidence import DiscoverySource, ProtectionStatus
from flight_hunter.domain.offers import Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentEvidenceError,
    AgentEvidenceRepository,
    AgentOperationRepository,
    AgentPlanApprovalSnapshot,
    AgentPlanRepository,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    NewAgentComposedRouteCandidate,
    NewAgentConfirmedOfferEvidence,
    NewAgentDiscoverySignal,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    NewAgentPlanStage,
    NewAgentRankingSnapshot,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import (
    agent_composed_route_candidates_table,
    agent_confirmed_offer_evidence_table,
    agent_discovery_signals_table,
    agent_ranking_snapshots_table,
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
DISCOVERY_ID = UUID("77777777-7777-7777-7777-777777777777")
EVIDENCE_ID = UUID("88888888-8888-8888-8888-888888888888")
CANDIDATE_ID = UUID("99999999-9999-9999-9999-999999999999")
RANKING_ID = UUID("aaaaaaaa-9999-9999-9999-999999999999")
SESSION_ID = UUID("12121212-1212-1212-1212-121212121212")
NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_confirmed_evidence_and_candidate_retries_deduplicate_without_update(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-dedupe.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        discovery = await repository.append_discovery_signal(_discovery())
        discovery_duplicate = await repository.append_discovery_signal(
            replace(
                _discovery(id_value=UUID("bbbbbbbb-7777-7777-7777-777777777777")),
                amount_minor=1,
            )
        )
        original = await repository.append_confirmed_evidence(_confirmed())
        duplicate = await repository.append_confirmed_evidence(
            replace(
                _confirmed(id_value=UUID("bbbbbbbb-8888-8888-8888-888888888888")),
                amount_minor=1,
                itinerary_evidence={"segments": [{"origin": "LED", "destination": "ORY"}]},
            )
        )
        candidate = await repository.append_composed_candidate(_candidate())
        candidate_duplicate = await repository.append_composed_candidate(
            replace(
                _candidate(id_value=UUID("bbbbbbbb-9999-9999-9999-999999999999")),
                amount_minor=2,
            )
        )
        await session.commit()

        assert discovery_duplicate.id == discovery.id == DISCOVERY_ID
        assert discovery_duplicate.amount_minor == 18_000
        assert duplicate.id == original.id == EVIDENCE_ID
        assert duplicate.amount_minor == 20_000
        assert duplicate.itinerary_evidence == {
            "segments": ({"destination": "CDG", "origin": "LED"},)
        }
        assert candidate_duplicate.id == candidate.id == CANDIDATE_ID
        assert candidate_duplicate.amount_minor == 20_000

    async with sessions() as session:
        discovery_count = (
            await session.execute(select(func.count()).select_from(agent_discovery_signals_table))
        ).scalar_one()
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
        candidate_count = (
            await session.execute(
                select(func.count()).select_from(agent_composed_route_candidates_table)
            )
        ).scalar_one()
        assert (discovery_count, evidence_count, candidate_count) == (1, 1, 1)

    await engine.dispose()


@pytest.mark.anyio
async def test_concurrent_confirmed_evidence_retries_store_one_fingerprint(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-concurrent-dedupe.db")
    await _seed_run_and_stage(sessions)
    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def append(evidence_id: UUID) -> UUID:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            stored = await AgentEvidenceRepository(session).append_confirmed_evidence(
                _confirmed(id_value=evidence_id)
            )
            await session.commit()
            return stored.id

    ids = await asyncio.gather(
        append(EVIDENCE_ID),
        append(UUID("bbbbbbbb-8888-8888-8888-888888888888")),
    )

    assert ids[0] == ids[1]
    async with sessions() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
        assert count == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_discovery_signal_is_a_distinct_type_and_cannot_enter_ranking(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "discovery-ranking.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        discovery = await repository.append_discovery_signal(_discovery())
        confirmed = await repository.append_confirmed_evidence(_confirmed())

        assert type(discovery) is not type(confirmed)
        with pytest.raises(AgentEvidenceError) as captured:
            await repository.create_ranking_snapshot(
                _ranking(confirmed_evidence_ids=(DISCOVERY_ID,))
            )
        assert captured.value.code == "agent_ranking_discovery_signal_forbidden"
        assert (
            await session.execute(select(func.count()).select_from(agent_ranking_snapshots_table))
        ).scalar_one() == 0

    await engine.dispose()


@pytest.mark.anyio
async def test_ranking_creates_append_only_snapshots_without_rewriting_evidence(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "ranking-append.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        evidence = await repository.append_confirmed_evidence(_confirmed())
        first = await repository.create_ranking_snapshot(_ranking())
        second = await repository.create_ranking_snapshot(
            _ranking(
                id_value=UUID("bbbbbbbb-9999-9999-9999-999999999998"),
                fingerprint="sha256:" + "d" * 64,
                ranking={"ordered": [str(EVIDENCE_ID)], "version": "rank-v2"},
            )
        )
        stored = await repository.get_confirmed_evidence(HOUSEHOLD_ID, EVIDENCE_ID)
        await session.commit()

        assert first.id != second.id
        assert stored == evidence

    async with sessions() as session:
        assert (
            await session.execute(select(func.count()).select_from(agent_ranking_snapshots_table))
        ).scalar_one() == 2

    await engine.dispose()


@pytest.mark.anyio
async def test_ranking_retry_with_same_fingerprint_returns_original_immutable_snapshot(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "ranking-idempotency.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        await repository.append_confirmed_evidence(_confirmed())
        original = await repository.create_ranking_snapshot(_ranking())
        duplicate = await repository.create_ranking_snapshot(
            _ranking(
                id_value=UUID("cccccccc-9999-9999-9999-999999999999"),
                ranking={"ordered": [], "version": "mutated-retry"},
            )
        )
        await session.commit()

        assert duplicate.id == original.id == RANKING_ID
        assert duplicate.ranking == {
            "ordered": (str(EVIDENCE_ID),),
            "version": "rank-v1",
        }

    async with sessions() as session:
        count = (
            await session.execute(select(func.count()).select_from(agent_ranking_snapshots_table))
        ).scalar_one()
        assert count == 1

    await engine.dispose()


@pytest.mark.anyio
async def test_candidate_and_ranking_references_require_same_household_and_run(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-ownership.db")
    await _seed_run_and_stage(sessions)
    other_ids = {
        "plan": UUID("bbbbbbbb-2222-2222-2222-222222222222"),
        "revision": UUID("bbbbbbbb-3333-3333-3333-333333333333"),
        "approval": UUID("bbbbbbbb-4444-4444-4444-444444444444"),
        "run": UUID("bbbbbbbb-5555-5555-5555-555555555555"),
        "stage": UUID("bbbbbbbb-6666-6666-6666-666666666666"),
    }
    await _seed_run_and_stage(
        sessions,
        plan_id=other_ids["plan"],
        revision_id=other_ids["revision"],
        approval_id=other_ids["approval"],
        run_id=other_ids["run"],
        stage_id=other_ids["stage"],
        idempotency_key="execute:evidence:other",
    )

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        await repository.append_confirmed_evidence(_confirmed())
        with pytest.raises(AgentEvidenceError, match="agent_evidence_reference_not_found"):
            await repository.append_composed_candidate(
                replace(
                    _candidate(),
                    run_id=other_ids["run"],
                    stage_id=other_ids["stage"],
                )
            )
        with pytest.raises(AgentEvidenceError, match="agent_evidence_reference_not_found"):
            await repository.create_ranking_snapshot(replace(_ranking(), run_id=other_ids["run"]))

    await engine.dispose()


@pytest.mark.anyio
async def test_household_a_cannot_read_household_b_evidence_or_results(tmp_path: Path) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-household.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        await repository.append_discovery_signal(_discovery())
        await repository.append_confirmed_evidence(_confirmed())
        await repository.append_composed_candidate(_candidate())
        await repository.create_ranking_snapshot(_ranking())
        await session.commit()

    async with sessions() as session:
        repository = AgentEvidenceRepository(session)
        assert await repository.get_discovery_signal(OTHER_HOUSEHOLD_ID, DISCOVERY_ID) is None
        assert await repository.get_confirmed_evidence(OTHER_HOUSEHOLD_ID, EVIDENCE_ID) is None
        assert await repository.get_composed_candidate(OTHER_HOUSEHOLD_ID, CANDIDATE_ID) is None
        assert await repository.get_ranking_snapshot(OTHER_HOUSEHOLD_ID, RANKING_ID) is None

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"segments": [{"x-signature": "secret"}]},
        {"segments": [{"marker": "mobile.secret"}]},
        {"provider_payload": {"anything": "raw"}},
        {"segments": [{"booking_url": "https://signed.example/secret"}]},
        {"segments": [{"href": "https://signed.example/opaque"}]},
        {"segments": [{"href": "  HtTpS://signed.example/mixed-case"}]},
        {"segments": [{"passenger_email": "person@example.test"}]},
    ],
)
async def test_nested_secrets_provider_payloads_urls_and_pii_are_rejected(
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-sanitizer.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        with pytest.raises(ValueError, match="unsafe field"):
            await AgentEvidenceRepository(session).append_confirmed_evidence(
                replace(_confirmed(), itinerary_evidence=payload)
            )

    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mutation",
    [
        {"observed_at": NOW.replace(tzinfo=None)},
        {"amount_minor": -1},
        {"amount_minor": 1, "currency": None},
        {"amount_minor": None, "currency": "RUB"},
        {"currency": "rubles"},
        {"passengers": 0},
        {"passenger_basis": "unknown_basis"},
        {"protection_status": "protected"},
    ],
)
async def test_invalid_evidence_money_passengers_status_and_time_are_rejected(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    engine, sessions = await _session_factory(tmp_path, "invalid-evidence.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        with pytest.raises((TypeError, ValueError)):
            await AgentEvidenceRepository(session).append_confirmed_evidence(
                replace(_confirmed(), **mutation)
            )

    await engine.dispose()


@pytest.mark.anyio
async def test_evidence_retry_rollback_remains_caller_owned(tmp_path: Path) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-rollback.db")
    await _seed_run_and_stage(sessions)

    async with sessions() as session:
        await AgentEvidenceRepository(session).append_confirmed_evidence(_confirmed())
        await session.rollback()

    async with sessions() as session:
        assert (
            await AgentEvidenceRepository(session).get_confirmed_evidence(HOUSEHOLD_ID, EVIDENCE_ID)
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


async def _seed_run_and_stage(
    sessions: async_sessionmaker[AsyncSession],
    *,
    plan_id: UUID = PLAN_ID,
    revision_id: UUID = REVISION_ID,
    approval_id: UUID = APPROVAL_ID,
    run_id: UUID = RUN_ID,
    stage_id: UUID = STAGE_ID,
    idempotency_key: str = "execute:evidence:1",
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
                cost_model_snapshot={"version": "v1"},
                parser_version="parser-v1",
                planner_version="planner-v1",
                estimated_calendar_searches=0,
                estimated_exact_searches=2,
                estimated_logical_operations=2,
                estimated_http_attempts=8,
                estimated_deadline_seconds=600,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            ),
        )
        await AgentRunRepository(session).approve_and_execute(
            approval=NewAgentPlanApproval(
                id=approval_id,
                household_id=HOUSEHOLD_ID,
                revision_id=revision_id,
                approved_by_user_id=USER_ID,
                approved_at=NOW,
                expires_at=NOW + timedelta(minutes=30),
                snapshot=AgentPlanApprovalSnapshot(
                    revision_content_hash=revision.content_hash,
                    approved_by_session_id=SESSION_ID,
                    approved_budget={"logical_operations": 2, "http_attempts": 8},
                    approved_strategies=("direct",),
                    risk_warning_versions={},
                ),
            ),
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


def _discovery(*, id_value: UUID = DISCOVERY_ID) -> NewAgentDiscoverySignal:
    return NewAgentDiscoverySignal(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        stage_id=STAGE_ID,
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 1),
        return_date=None,
        amount_minor=18_000,
        currency="RUB",
        passengers=1,
        passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
        source_kind=DiscoverySource.CALENDAR,
        freshness=Freshness.API_CACHED,
        observed_at=NOW,
        signal_evidence={"calendar_bucket": "2026-09"},
        fingerprint="sha256:" + "a" * 64,
        created_at=NOW,
    )


def _confirmed(*, id_value: UUID = EVIDENCE_ID) -> NewAgentConfirmedOfferEvidence:
    return NewAgentConfirmedOfferEvidence(
        id=id_value,
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
        fingerprint="sha256:" + "b" * 64,
        created_at=NOW,
    )


def _candidate(*, id_value: UUID = CANDIDATE_ID) -> NewAgentComposedRouteCandidate:
    return NewAgentComposedRouteCandidate(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        stage_id=STAGE_ID,
        component_evidence_ids=(EVIDENCE_ID,),
        observed_at=NOW,
        passengers=1,
        passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
        amount_minor=20_000,
        currency="RUB",
        itinerary_evidence={"components": [str(EVIDENCE_ID)]},
        protection_status=ProtectionStatus.UNKNOWN,
        baggage_status=None,
        transfer_status=None,
        visa_status=None,
        fingerprint="sha256:" + "c" * 64,
        created_at=NOW,
    )


def _ranking(
    *,
    id_value: UUID = RANKING_ID,
    confirmed_evidence_ids: tuple[UUID, ...] = (EVIDENCE_ID,),
    candidate_ids: tuple[UUID, ...] = (),
    fingerprint: str = "sha256:" + "e" * 64,
    ranking: dict[str, object] | None = None,
) -> NewAgentRankingSnapshot:
    return NewAgentRankingSnapshot(
        id=id_value,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        confirmed_evidence_ids=confirmed_evidence_ids,
        composed_candidate_ids=candidate_ids,
        ranking=ranking or {"ordered": [str(EVIDENCE_ID)], "version": "rank-v1"},
        fingerprint=fingerprint,
        created_at=NOW,
    )
