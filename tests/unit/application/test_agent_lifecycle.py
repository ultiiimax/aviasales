from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_lifecycle import (
    HIDDEN_CITY_WARNING_VERSION,
    AgentLifecycleError,
    AgentLifecycleService,
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
from flight_hunter.persistence.models import mapper_registry

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

    assert view.state == "awaiting_approval"
    assert view.revision == 1
    assert view.executable is True
    assert view.content_hash.startswith("sha256:")
    assert provider.calls == 0
    await engine.dispose()


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
async def test_execute_persists_exact_budget_strategy_session_and_warning_snapshot() -> None:
    async with _lifecycle_harness() as harness:
        hidden = await _create(harness.service, strategies=("hidden_city",))
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
        "calendar_searches": 0,
        "exact_searches": 1,
        "logical_operations": 1,
        "http_attempts": 27,
        "deadline_seconds": 600,
    }
    assert approval.snapshot.approved_strategies == ("hidden_city",)
    assert approval.snapshot.risk_warning_versions == {"hidden_city": HIDDEN_CITY_WARNING_VERSION}


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
