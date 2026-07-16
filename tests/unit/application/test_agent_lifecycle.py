from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_lifecycle import (
    HIDDEN_CITY_WARNING_VERSION,
    AgentLifecycleError,
    AgentLifecycleService,
    CancelAgentRun,
    CloneAgentPlan,
    CreateAgentPlan,
    EditAgentPlan,
    ExecuteAgentPlan,
    PlanView,
    RunView,
)
from flight_hunter.application.agent_planning import AgentPlanBuilder
from flight_hunter.application.agent_scope import CoverageMode, ScopeResolver
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportType,
    freeze_airport_catalog,
)
from flight_hunter.persistence.agent_repositories import AgentPlanRepository, AgentRunRepository
from flight_hunter.persistence.models import (
    agent_plan_execution_approvals_table,
    mapper_registry,
)

NOW = datetime(2026, 7, 14, 9, 0, tzinfo=UTC)
HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = UUID("aaaaaaaa-0000-0000-0000-000000000001")
SESSION_ID = UUID("aaaaaaaa-1000-0000-0000-000000000001")


class StaticAirportCatalog:
    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        return freeze_airport_catalog(
            (
                _airport("LED", "RU", "Saint Petersburg"),
                _airport("CDG", "FR", "Paris"),
                _airport("FCO", "IT", "Rome"),
            )
        )


class CountingProviderGateway:
    def __init__(self) -> None:
        self.calls = 0


@dataclass(slots=True)
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


@dataclass(frozen=True, slots=True)
class LifecycleHarness:
    service: AgentLifecycleService
    session: AsyncSession
    provider: CountingProviderGateway
    clock: MutableClock
    engine: AsyncEngine


@pytest.mark.anyio
async def test_complete_create_persists_executable_revision_without_provider_call() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = CountingProviderGateway()
    builder = AgentPlanBuilder(
        clock=lambda: NOW,
        scope_resolver=ScopeResolver(repository=StaticAirportCatalog()),
    )

    async with factory() as session:
        service = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=builder,
            clock=lambda: NOW,
            provider_gateway=provider,
        )
        view = await service.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections={"departure_date": "2026-09-10"},
                coverage=CoverageMode.QUICK,
            )
        )
        stored = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            view.revision_id,
        )

    assert view.state == "awaiting_approval"
    assert view.revision == 1
    assert view.executable is True
    assert view.content_hash.startswith("sha256:")
    assert stored is not None
    assert stored.parser_version == "intent-parser-v2"
    assert stored.planner_version == "agent-plan-builder-v5"
    assert provider.calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("return_date", ("2026-09-09", "2026-09-11"))
async def test_flexible_round_trip_invalid_return_cannot_reach_approval(
    return_date: str,
) -> None:
    async with _lifecycle_harness() as harness:
        view = await harness.service.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections={
                    "departure_date": "2026-09-10",
                    "date_mode": "flexible",
                    "flex_days": 2,
                    "return_date": return_date,
                },
                coverage=CoverageMode.QUICK,
            )
        )

    assert view.state == "draft"
    assert view.executable is False
    assert view.estimate is None
    assert tuple(item["code"] for item in view.clarifications) == (
        "return_before_outbound_window_end",
    )
    assert harness.provider.calls == 0


@pytest.mark.anyio
async def test_edit_and_clone_keep_old_revisions_immutable_and_refresh_terminal_sources() -> None:
    async with _lifecycle_harness() as harness:
        first = await _create(harness.service)
        edited = await harness.service.edit_plan(
            EditAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=1,
                selections={"departure_date": "2026-09-11"},
            )
        )
        superseded_clone = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=1,
                idempotency_key="clone-superseded",
            )
        )
        superseded_retry = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=1,
                idempotency_key="clone-superseded",
            )
        )

        consumed = await _create(harness.service)
        await _execute(harness.service, consumed, "execute-consumed")
        consumed_clone = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=consumed.plan_id,
                source_revision_id=consumed.revision_id,
                expected_revision=1,
                idempotency_key="clone-consumed",
            )
        )

        expiring = await _create(harness.service)
        harness.clock.advance(timedelta(days=1, seconds=1))
        expired_clone = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=expiring.plan_id,
                source_revision_id=expiring.revision_id,
                expected_revision=1,
                idempotency_key="clone-expired",
            )
        )

        repository = AgentPlanRepository(harness.session)
        original = await repository.get_revision(HOUSEHOLD_ID, first.revision_id)
        edited_record = await repository.get_revision(HOUSEHOLD_ID, edited.revision_id)
        expired_source = await repository.get_revision(HOUSEHOLD_ID, expiring.revision_id)

    assert original is not None and original.state == "superseded"
    assert edited_record is not None and edited_record.state == "superseded"
    assert edited.revision == 2
    assert superseded_clone.revision == 3
    assert superseded_retry.revision_id == superseded_clone.revision_id
    assert consumed_clone.revision == 2
    assert expired_clone.revision == 2
    assert expired_source is not None and expired_source.state == "expired"
    assert harness.provider.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("text", "selections", "expected_radius"),
    (
        ("LED → CDG", {"nearby_radius_km": 80}, 80),
        (
            "LED → CDG nearby airports",
            {"origin": "LED", "destination": "CDG"},
            150,
        ),
    ),
)
async def test_edit_without_new_text_and_clone_preserve_nearby_radius(
    text: str,
    selections: dict[str, object],
    expected_radius: int,
) -> None:
    async with _lifecycle_harness() as harness:
        first = await harness.service.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text=text,
                selections={"departure_date": "2026-09-10", **selections},
                coverage=CoverageMode.QUICK,
            )
        )
        edited = await harness.service.edit_plan(
            EditAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                selections={"departure_date": "2026-09-11"},
            )
        )
        cloned = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                idempotency_key=f"clone-nearby-{expected_radius}",
            )
        )

    assert edited.summary.scope[0].nearby_radius_km == expected_radius
    assert cloned.summary.scope[0].nearby_radius_km == expected_radius


@pytest.mark.anyio
async def test_edit_with_new_route_text_does_not_carry_previous_nearby_radius() -> None:
    async with _lifecycle_harness() as harness:
        first = await harness.service.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections={"departure_date": "2026-09-10", "nearby_radius_km": 80},
                coverage=CoverageMode.QUICK,
            )
        )
        edited = await harness.service.edit_plan(
            EditAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                text="LED → CDG",
                selections={"departure_date": "2026-09-11"},
            )
        )

    assert edited.summary.scope[0].nearby_radius_km == 0


@pytest.mark.anyio
async def test_explicit_zero_disables_nearby_preset_across_edit_and_clone() -> None:
    async with _lifecycle_harness() as harness:
        first = await harness.service.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                preset_id="nearby_airports",
                selections={"departure_date": "2026-09-10", "nearby_radius_km": 0},
                coverage=CoverageMode.QUICK,
            )
        )
        edited = await harness.service.edit_plan(
            EditAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                selections={"departure_date": "2026-09-11"},
            )
        )
        cloned = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                idempotency_key="clone-nearby-disabled",
            )
        )

    assert first.summary.scope[0].nearby_radius_km == 0
    assert edited.summary.scope[0].nearby_radius_km == 0
    assert cloned.summary.scope[0].nearby_radius_km == 0


@pytest.mark.anyio
async def test_execute_persists_exact_budget_strategy_session_and_warning_snapshot() -> None:
    async with _lifecycle_harness() as harness:
        hidden = await _create(harness.service, strategies=("hidden_city",))
        stored_revision = await AgentPlanRepository(harness.session).get_revision(
            HOUSEHOLD_ID,
            hidden.revision_id,
        )
        assert stored_revision is not None
        stored_plan = json.loads(stored_revision.plan_json)
        stored_scope = json.loads(stored_revision.scope_snapshot_json)
        hidden_rule = stored_plan["hidden_city"]
        assert hidden_rule["version"] == "hidden-city-search-v1"
        assert hidden_rule["plan_leg_index"] == 0
        assert hidden_rule["desired_airports"] == ["CDG"]
        discovery = hidden_rule["discovery"]
        assert discovery["origin_airports"] == ["LED"]
        assert discovery["date_start"] == "2026-09-10"
        assert discovery["date_end"] == "2026-09-10"
        assert discovery["discovery_source_ids"] == ["aviasales_hot_offers"]
        assert discovery["max_destination_seeds"] == 4
        assert discovery["exact_verification_limit"] == 2
        assert discovery["eligible_destination_countries"] == [
            {"code": "FCO", "country_code": "IT"},
        ]
        assert (
            discovery["catalog_checksum"] == (stored_scope["legs"][0]["origin"]["catalog_checksum"])
        )
        assert hidden.summary.hidden_city_warning_version == HIDDEN_CITY_WARNING_VERSION
        assert {warning.code for warning in hidden.summary.hidden_city_warnings} == {
            "checked_baggage_continues",
            "later_segments_may_be_cancelled",
            "carrier_contract_risk",
        }
        await harness.session.rollback()
        run = await _execute(
            harness.service,
            hidden,
            "execute-hidden",
            hidden_city_warning_version=HIDDEN_CITY_WARNING_VERSION,
        )
        run_repository = AgentRunRepository(harness.session)
        stored_run = await run_repository.get_run(HOUSEHOLD_ID, run.run_id)
        assert stored_run is not None
        approval = await run_repository.get_approval(HOUSEHOLD_ID, stored_run.approval_id)

    assert approval is not None
    assert approval.snapshot.approved_by_session_id == SESSION_ID
    assert approval.snapshot.revision_content_hash == hidden.content_hash
    assert approval.snapshot.approved_budget == {
        "calendar_searches": 4,
        "exact_searches": 3,
        "logical_operations": 7,
        "http_attempts": 93,
        "deadline_seconds": 600,
    }
    assert approval.snapshot.approved_strategies == ("hidden_city",)
    assert approval.snapshot.risk_warning_versions == {"hidden_city": HIDDEN_CITY_WARNING_VERSION}


@pytest.mark.anyio
async def test_hidden_city_acknowledgement_is_bound_to_the_exact_successor_revision() -> None:
    async with _lifecycle_harness() as harness:
        original = await _create(harness.service, strategies=("hidden_city",))
        successor = await harness.service.edit_plan(
            EditAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=original.plan_id,
                source_revision_id=original.revision_id,
                expected_revision=original.revision,
                selections={"requested_strategies": ["hidden_city"]},
            )
        )

        with pytest.raises(AgentLifecycleError) as stale:
            await _execute(
                harness.service,
                original,
                "hidden-old-revision",
                hidden_city_warning_version=HIDDEN_CITY_WARNING_VERSION,
            )
        accepted = await _execute(
            harness.service,
            successor,
            "hidden-successor-run",
            hidden_city_warning_version=HIDDEN_CITY_WARNING_VERSION,
        )

    assert stale.value.code == "agent_plan_stale"
    assert accepted.revision_id == successor.revision_id


@pytest.mark.anyio
async def test_execute_surfaces_typed_sqlite_nested_transaction_boundary() -> None:
    async with _lifecycle_harness() as harness:
        plan = await _create(harness.service)
        async with harness.session.begin_nested():
            with pytest.raises(AgentLifecycleError) as exc_info:
                await _execute(harness.service, plan, "nested-execute")
        runs = await AgentRunRepository(harness.session).list_runs(
            HOUSEHOLD_ID,
            plan.plan_id,
        )

    assert exc_info.value.code == "agent_sqlite_nested_transaction_unsupported"
    assert runs == ()


@pytest.mark.anyio
async def test_failed_execute_rolls_back_orphan_approval_and_reuses_session() -> None:
    async with _lifecycle_harness() as harness:
        source = await _create(harness.service)
        active = await _execute(harness.service, source, "active-run")
        cloned = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=source.plan_id,
                source_revision_id=source.revision_id,
                expected_revision=source.revision,
                idempotency_key="clone-for-conflict",
            )
        )

        with pytest.raises(AgentLifecycleError) as exc_info:
            await _execute(harness.service, cloned, "blocked-by-active-run")

        recovered = await _create(harness.service)
        approval_count = await harness.session.scalar(
            select(func.count()).select_from(agent_plan_execution_approvals_table)
        )
        stored_clone = await AgentPlanRepository(harness.session).get_revision(
            HOUSEHOLD_ID,
            cloned.revision_id,
        )

    assert exc_info.value.code == "agent_run_already_active"
    assert approval_count == 1
    assert stored_clone is not None and stored_clone.state == "awaiting_approval"
    assert recovered.state == "awaiting_approval"
    assert active.status == "queued"


@pytest.mark.anyio
async def test_execute_unknown_fault_after_approval_insert_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _lifecycle_harness() as harness:
        plan = await _create(harness.service)

        async def fail_execute(
            _repository: AgentRunRepository,
            **_kwargs: object,
        ) -> object:
            raise RuntimeError("execute fault")

        monkeypatch.setattr(AgentRunRepository, "execute", fail_execute)
        with pytest.raises(RuntimeError, match="execute fault"):
            await _execute(harness.service, plan, "fault-after-approval")
        recovered = await _create(harness.service)
        approval_count = await harness.session.scalar(
            select(func.count()).select_from(agent_plan_execution_approvals_table)
        )
        revision = await AgentPlanRepository(harness.session).get_revision(
            HOUSEHOLD_ID,
            plan.revision_id,
        )

    assert approval_count == 0
    assert revision is not None and revision.state == "awaiting_approval"
    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
async def test_edit_clone_and_cancel_unknown_faults_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _lifecycle_harness() as harness:
        editable = await _create(harness.service)
        original_successor = AgentPlanRepository.create_successor

        async def fail_after_successor(
            repository: AgentPlanRepository,
            **kwargs: object,
        ) -> object:
            await original_successor(repository, **kwargs)  # type: ignore[arg-type]
            raise RuntimeError("edit fault")

        monkeypatch.setattr(AgentPlanRepository, "create_successor", fail_after_successor)
        with pytest.raises(RuntimeError, match="edit fault"):
            await harness.service.edit_plan(
                EditAgentPlan(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    plan_id=editable.plan_id,
                    source_revision_id=editable.revision_id,
                    expected_revision=editable.revision,
                    selections={"departure_date": "2026-09-11"},
                )
            )
        revisions = await AgentPlanRepository(harness.session).list_revisions(
            HOUSEHOLD_ID,
            editable.plan_id,
        )
        assert [(item.revision_number, item.state) for item in revisions] == [
            (1, "awaiting_approval")
        ]
        await harness.session.rollback()
        monkeypatch.setattr(AgentPlanRepository, "create_successor", original_successor)

        terminal = await _create(harness.service)
        run = await _execute(harness.service, terminal, "terminal-run")
        await _terminalize_run(harness.session, run)
        original_clone = AgentPlanRepository.create_clone

        async def fail_after_clone(
            repository: AgentPlanRepository,
            **kwargs: object,
        ) -> object:
            await original_clone(repository, **kwargs)  # type: ignore[arg-type]
            raise RuntimeError("clone fault")

        monkeypatch.setattr(AgentPlanRepository, "create_clone", fail_after_clone)
        with pytest.raises(RuntimeError, match="clone fault"):
            await harness.service.clone_revision(
                CloneAgentPlan(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    plan_id=terminal.plan_id,
                    source_revision_id=terminal.revision_id,
                    expected_revision=terminal.revision,
                    idempotency_key="faulty-clone",
                )
            )
        revisions = await AgentPlanRepository(harness.session).list_revisions(
            HOUSEHOLD_ID,
            terminal.plan_id,
        )
        assert len(revisions) == 1
        await harness.session.rollback()
        monkeypatch.setattr(AgentPlanRepository, "create_clone", original_clone)

        cancellable = await _create(harness.service)
        queued = await _execute(harness.service, cancellable, "cancel-fault-run")
        original_status = AgentRunRepository.set_status

        async def fail_after_status(
            repository: AgentRunRepository,
            **kwargs: object,
        ) -> object:
            await original_status(repository, **kwargs)  # type: ignore[arg-type]
            raise RuntimeError("cancel fault")

        monkeypatch.setattr(AgentRunRepository, "set_status", fail_after_status)
        with pytest.raises(RuntimeError, match="cancel fault"):
            await harness.service.cancel_run(
                CancelAgentRun(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    plan_id=cancellable.plan_id,
                    run_id=queued.run_id,
                )
            )
        stored_run = await AgentRunRepository(harness.session).get_run(
            HOUSEHOLD_ID,
            queued.run_id,
        )

    assert stored_run is not None and stored_run.status == "queued"


@pytest.mark.anyio
async def test_repeated_unchanged_clone_generations_are_unique_and_idempotent() -> None:
    async with _lifecycle_harness() as harness:
        first = await _create(harness.service)
        first_run = await _execute(harness.service, first, "generation-run-1")
        await _terminalize_run(harness.session, first_run)
        harness.clock.advance(timedelta(minutes=1))
        second = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=first.revision_id,
                expected_revision=first.revision,
                idempotency_key="generation-clone-1",
            )
        )
        second_run = await _execute(harness.service, second, "generation-run-2")
        await _terminalize_run(harness.session, second_run)
        harness.clock.advance(timedelta(minutes=1))
        third = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=second.revision_id,
                expected_revision=second.revision,
                idempotency_key="generation-clone-2",
            )
        )
        retry = await harness.service.clone_revision(
            CloneAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                plan_id=first.plan_id,
                source_revision_id=second.revision_id,
                expected_revision=second.revision,
                idempotency_key="generation-clone-2",
            )
        )
        records = await AgentPlanRepository(harness.session).list_revisions(
            HOUSEHOLD_ID,
            first.plan_id,
        )

    approval_evidence = [json.loads(item.plan_json)["approval"] for item in records]
    assert [item.revision_number for item in records] == [1, 2, 3]
    assert [item["generation"] for item in approval_evidence] == [1, 2, 3]
    assert len({item.content_hash for item in records}) == 3
    assert first.expires_at < second.expires_at < third.expires_at
    assert retry.revision_id == third.revision_id


@pytest.mark.anyio
async def test_execute_rechecks_idempotency_after_revision_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _lifecycle_harness() as harness:
        plan = await _create(harness.service)
        original = await _execute(harness.service, plan, "locked-idempotency")
        real_lookup = AgentRunRepository.get_by_execute_idempotency
        calls = 0

        async def miss_then_find(
            repository: AgentRunRepository,
            household_id: UUID,
            idempotency_key: str,
        ):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return await real_lookup(repository, household_id, idempotency_key)

        monkeypatch.setattr(
            AgentRunRepository,
            "get_by_execute_idempotency",
            miss_then_find,
        )
        retried = await _execute(harness.service, plan, "locked-idempotency")

    assert calls == 2
    assert retried.run_id == original.run_id


@pytest.mark.anyio
async def test_two_session_execute_race_converges_on_one_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "agent-execute-race.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = CountingProviderGateway()

    def service(session: AsyncSession) -> AgentLifecycleService:
        return AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=lambda: NOW,
                scope_resolver=ScopeResolver(repository=StaticAirportCatalog()),
            ),
            clock=lambda: NOW,
            provider_gateway=provider,
        )

    async with factory() as setup_session:
        plan = await _create(service(setup_session))

    real_lookup = AgentRunRepository.get_by_execute_idempotency
    gate = asyncio.Event()
    lock = asyncio.Lock()
    synchronized_repositories: set[int] = set()

    async def synchronize_initial_lookup(
        repository: AgentRunRepository,
        household_id: UUID,
        idempotency_key: str,
    ):
        identity = id(repository)
        if identity not in synchronized_repositories:
            async with lock:
                synchronized_repositories.add(identity)
                if len(synchronized_repositories) == 2:
                    gate.set()
            await gate.wait()
        return await real_lookup(repository, household_id, idempotency_key)

    monkeypatch.setattr(
        AgentRunRepository,
        "get_by_execute_idempotency",
        synchronize_initial_lookup,
    )
    async with factory() as first_session, factory() as second_session:
        first, second = await asyncio.gather(
            _execute(service(first_session), plan, "two-session-key"),
            _execute(service(second_session), plan, "two-session-key"),
        )

    async with factory() as check_session:
        runs = await AgentRunRepository(check_session).list_runs(HOUSEHOLD_ID, plan.plan_id)

    assert first.run_id == second.run_id
    assert len(runs) == 1
    assert provider.calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_direct_invalid_parser_input_is_stable_and_rolls_back() -> None:
    async with _lifecycle_harness() as harness:
        with pytest.raises(AgentLifecycleError) as exc_info:
            await harness.service.create_plan(
                CreateAgentPlan(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    text="LED → CDG",
                    selections={"adults": "two"},
                )
            )
        valid = await _create(harness.service)

    assert exc_info.value.code == "agent_plan_invalid_input"
    assert valid.state == "awaiting_approval"


@pytest.mark.anyio
async def test_internal_builder_value_error_rolls_back_and_propagates() -> None:
    class FailingBuilder:
        async def build(self, *_args: object, **_kwargs: object) -> object:
            raise ValueError("internal builder probe")

    async with _lifecycle_harness() as harness:
        broken_service = AgentLifecycleService(
            session=harness.session,
            parser=IntentParser(),
            builder=FailingBuilder(),  # type: ignore[arg-type]
            clock=harness.clock,
            provider_gateway=harness.provider,
        )
        with pytest.raises(ValueError, match="internal builder probe"):
            await _create(broken_service)
        assert harness.session.in_transaction() is False
        recovered = await _create(harness.service)

    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
async def test_internal_overlay_value_error_is_not_classified_as_user_input() -> None:
    def failing_overlay(*_args: object, **_kwargs: object) -> object:
        raise ValueError("internal overlay probe")

    async with _lifecycle_harness() as harness:
        broken_service = AgentLifecycleService(
            session=harness.session,
            parser=IntentParser(overlay_provider=failing_overlay),
            builder=AgentPlanBuilder(
                clock=harness.clock,
                scope_resolver=ScopeResolver(repository=StaticAirportCatalog()),
            ),
            clock=harness.clock,
            provider_gateway=harness.provider,
        )
        with pytest.raises(ValueError, match="internal overlay probe"):
            await _create(broken_service)
        assert harness.session.in_transaction() is False
        recovered = await _create(harness.service)

    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
async def test_internal_repository_type_error_rolls_back_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = AgentPlanRepository.create_plan

    async def fail_create_plan(
        _repository: AgentPlanRepository,
        *_args: object,
        **_kwargs: object,
    ) -> object:
        raise TypeError("internal repository probe")

    async with _lifecycle_harness() as harness:
        monkeypatch.setattr(AgentPlanRepository, "create_plan", fail_create_plan)
        with pytest.raises(TypeError, match="internal repository probe"):
            await _create(harness.service)
        assert harness.session.in_transaction() is False
        monkeypatch.setattr(AgentPlanRepository, "create_plan", original)
        recovered = await _create(harness.service)

    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation",
    ("get_plan", "list_runs", "get_run", "get_latest_run", "get_run_results"),
)
async def test_read_methods_end_transaction_and_allow_same_session_mutation(
    operation: str,
) -> None:
    async with _lifecycle_harness() as harness:
        plan = await _create(harness.service)
        run = await _execute(harness.service, plan, f"read-boundary-{operation}")

        if operation == "get_plan":
            await harness.service.get_plan(HOUSEHOLD_ID, plan.plan_id)
        elif operation == "list_runs":
            await harness.service.list_runs(HOUSEHOLD_ID, plan.plan_id)
        elif operation == "get_run":
            await harness.service.get_run(HOUSEHOLD_ID, plan.plan_id, run.run_id)
        elif operation == "get_latest_run":
            await harness.service.get_latest_run(HOUSEHOLD_ID, plan.plan_id)
        else:
            await harness.service.get_run_results(HOUSEHOLD_ID, plan.plan_id, run.run_id)

        assert harness.session.in_transaction() is False
        recovered = await _create(harness.service)

    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
async def test_read_exception_rolls_back_and_reuses_same_session() -> None:
    async with _lifecycle_harness() as harness:
        plan = await _create(harness.service)
        with pytest.raises(AgentLifecycleError) as exc_info:
            await harness.service.get_latest_run(HOUSEHOLD_ID, plan.plan_id)
        assert harness.session.in_transaction() is False
        recovered = await _create(harness.service)

    assert exc_info.value.code == "agent_run_not_found"
    assert recovered.state == "awaiting_approval"


@pytest.mark.anyio
async def test_list_runs_query_count_is_constant_and_limit_is_bounded() -> None:
    async with _lifecycle_harness() as harness:
        first = await _create(harness.service)
        first_run = await _execute(harness.service, first, "bulk-run-1")
        await _terminalize_run(harness.session, first_run)

        async def counted_list() -> tuple[int, tuple[RunView, ...]]:
            queries = 0

            def count_query(*_args: object) -> None:
                nonlocal queries
                queries += 1

            event.listen(harness.engine.sync_engine, "before_cursor_execute", count_query)
            try:
                views = await harness.service.list_runs(
                    HOUSEHOLD_ID,
                    first.plan_id,
                    limit=100,
                )
            finally:
                event.remove(harness.engine.sync_engine, "before_cursor_execute", count_query)
            return queries, views

        one_query_count, one = await counted_list()
        source = first
        for index in (2, 3):
            cloned = await harness.service.clone_revision(
                CloneAgentPlan(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    plan_id=first.plan_id,
                    source_revision_id=source.revision_id,
                    expected_revision=source.revision,
                    idempotency_key=f"bulk-clone-{index}",
                )
            )
            run = await _execute(harness.service, cloned, f"bulk-run-{index}")
            await _terminalize_run(harness.session, run)
            source = cloned
        many_query_count, many = await counted_list()

        with pytest.raises(ValueError, match="between 1 and 100"):
            await harness.service.list_runs(HOUSEHOLD_ID, first.plan_id, limit=101)

    assert len(one) == 1
    assert len(many) == 3
    assert many_query_count == one_query_count


@pytest.mark.anyio
async def test_lifecycle_observability_is_structured_and_omits_private_inputs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_key = "PRIVATE-IDEMPOTENCY-CANARY"
    async with _lifecycle_harness() as harness:
        with caplog.at_level("INFO", logger="flight_hunter.observability"):
            plan = await _create(harness.service)
            run = await _execute(harness.service, plan, private_key)
            await harness.service.cancel_run(
                CancelAgentRun(
                    household_id=HOUSEHOLD_ID,
                    user_id=USER_ID,
                    plan_id=plan.plan_id,
                    run_id=run.run_id,
                )
            )

    rendered = "\n".join(caplog.messages)
    assert '"event":"agent_plan_created"' in rendered
    assert '"event":"agent_run_approved"' in rendered
    assert '"event":"agent_run_cancel_requested"' in rendered
    assert '"estimated_http_attempts":' in rendered
    assert '"http_attempt_budget":' in rendered
    assert '"parser_version":"intent-parser-v2"' in rendered
    assert '"planner_version":"agent-plan-builder-v5"' in rendered
    assert private_key not in rendered
    for forbidden in ("content_hash", "idempotency", "booking", "continuation", "prompt"):
        assert forbidden not in rendered.lower()


@asynccontextmanager
async def _lifecycle_harness() -> AsyncIterator[LifecycleHarness]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = CountingProviderGateway()
    clock = MutableClock()
    builder = AgentPlanBuilder(
        clock=clock,
        scope_resolver=ScopeResolver(repository=StaticAirportCatalog()),
    )
    async with factory() as session:
        yield LifecycleHarness(
            service=AgentLifecycleService(
                session=session,
                parser=IntentParser(),
                builder=builder,
                clock=clock,
                provider_gateway=provider,
            ),
            session=session,
            provider=provider,
            clock=clock,
            engine=engine,
        )
    await engine.dispose()


async def _create(
    service: AgentLifecycleService,
    *,
    strategies: tuple[str, ...] = (),
) -> PlanView:
    return await service.create_plan(
        CreateAgentPlan(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            text="LED → CDG",
            selections={
                "departure_date": "2026-09-10",
                "requested_strategies": list(strategies),
            },
            coverage=CoverageMode.QUICK,
        )
    )


async def _execute(
    service: AgentLifecycleService,
    plan: PlanView,
    key: str,
    *,
    hidden_city_warning_version: str | None = None,
) -> RunView:
    return await service.execute_plan(
        ExecuteAgentPlan(
            household_id=HOUSEHOLD_ID,
            user_id=USER_ID,
            approved_by_session_id=SESSION_ID,
            plan_id=plan.plan_id,
            revision_id=plan.revision_id,
            expected_revision=plan.revision,
            content_hash=plan.content_hash,
            idempotency_key=key,
            hidden_city_warning_version=hidden_city_warning_version,
        )
    )


async def _terminalize_run(session: AsyncSession, run: RunView) -> None:
    repository = AgentRunRepository(session)
    changed_at = run.created_at + timedelta(seconds=1)
    await repository.set_status(
        household_id=HOUSEHOLD_ID,
        run_id=run.run_id,
        status="cancel_requested",
        changed_at=changed_at,
    )
    await repository.set_status(
        household_id=HOUSEHOLD_ID,
        run_id=run.run_id,
        status="cancelled",
        changed_at=changed_at,
    )
    await session.commit()


def _airport(code: str, country: str, municipality: str) -> Airport:
    return Airport(
        iata_code=code,
        name=f"{municipality} Airport",
        municipality=municipality,
        country_code=country,
        latitude=48.0,
        longitude=2.0,
        airport_type=AirportType.LARGE_AIRPORT,
        active=True,
        scheduled_service=True,
        commercial_provenance="task5.test_catalog",
    )
