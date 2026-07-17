from __future__ import annotations

import hashlib
import importlib
import json
import traceback
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Literal
from uuid import UUID, uuid4, uuid5

import pytest
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.application.agent_hidden_city import HIDDEN_CITY_WARNING_VERSION
from flight_hunter.application.agent_intent import IntentParser
from flight_hunter.application.agent_lifecycle import (
    AgentLifecycleService,
    CreateAgentPlan,
    ExecuteAgentPlan,
    _coverage_operation_outcomes,
    _snapshot_anywhere_discovery_phase,
)
from flight_hunter.application.agent_operations import CoveragePair
from flight_hunter.application.agent_planning import AgentPlanBuilder
from flight_hunter.application.agent_reporting import (
    CandidateKind,
    RankingView,
    ranking_snapshot_from_payload,
)
from flight_hunter.application.agent_scope import CoverageMode, ScopeResolver
from flight_hunter.application.booking_actions import (
    verify_agent_booking_action_token,
)
from flight_hunter.domain.agent_evidence import (
    ConfirmedOfferEvidence,
    DiscoverySignal,
    DiscoverySource,
    ProtectionStatus,
)
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary, Freshness, PriceBasis
from flight_hunter.geo.airports import (
    Airport,
    AirportCatalogSnapshot,
    AirportType,
    freeze_airport_catalog,
)
from flight_hunter.persistence.agent_repositories import (
    AgentConfirmedOfferEvidenceRecord,
    AgentEvidenceRepository,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentOperationStatus,
    AgentPlanApprovalSnapshot,
    AgentPlanRepository,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    NewAgentAnalysisSnapshot,
    NewAgentConfirmedOfferEvidence,
    NewAgentDiscoverySignal,
    NewAgentPlan,
    NewAgentPlanApproval,
    NewAgentPlanRevision,
    NewAgentPlanRun,
    recompute_agent_plan_revision_content_hash,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import (
    agent_analysis_snapshots_table,
    agent_confirmed_offer_evidence_table,
    agent_discovery_signals_table,
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
    agent_provider_circuit_state_table,
    agent_provider_http_attempts_table,
    agent_ranking_snapshots_table,
    agent_run_operations_table,
    agent_run_scope_snapshots_table,
    agent_search_plan_revisions_table,
    mapper_registry,
)
from flight_hunter.providers.aviasales_search.client import (
    AviasalesSearchAuthFailed,
    AviasalesSearchBlocked,
    AviasalesSearchHttpStatusError,
    AviasalesSearchRateLimited,
    AviasalesSearchSchemaError,
    AviasalesSearchTransportError,
    SearchStartParams,
)
from flight_hunter.providers.aviasales_search.gateway import (
    AnywhereDiscoveryParams,
    AviasalesSearchPolicyDenied,
    CalendarSearchParams,
    ExactPollOutcome,
    ExactSearchContinuation,
    PrivateBookingActionDescriptor,
)

HOUSEHOLD_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_HOUSEHOLD_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("11111111-1111-1111-1111-111111111111")
SESSION_ID = UUID("12121212-1212-1212-1212-121212121212")
PLAN_ID = UUID("22222222-2222-2222-2222-222222222222")
REVISION_ID = UUID("33333333-3333-3333-3333-333333333333")
APPROVAL_ID = UUID("44444444-4444-4444-4444-444444444444")
RUN_ID = UUID("55555555-5555-5555-5555-555555555555")
NOW = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


class SimulatedProcessCrash(BaseException):
    pass


class _ProductionShapeAirportCatalog:
    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        return freeze_airport_catalog(
            (
                Airport(
                    iata_code="LED",
                    name="Pulkovo",
                    municipality="Saint Petersburg",
                    country_code="RU",
                    latitude=59.8003,
                    longitude=30.2625,
                    airport_type=AirportType.LARGE_AIRPORT,
                    active=True,
                    scheduled_service=True,
                    commercial_provenance="task9.test_catalog",
                ),
                Airport(
                    iata_code="CDG",
                    name="Charles de Gaulle",
                    municipality="Paris",
                    country_code="FR",
                    latitude=49.0097,
                    longitude=2.5479,
                    airport_type=AirportType.LARGE_AIRPORT,
                    active=True,
                    scheduled_service=True,
                    commercial_provenance="task9.test_catalog",
                ),
                Airport(
                    iata_code="FCO",
                    name="Fiumicino",
                    municipality="Rome",
                    country_code="IT",
                    latitude=41.8003,
                    longitude=12.2389,
                    airport_type=AirportType.LARGE_AIRPORT,
                    active=True,
                    scheduled_service=True,
                    commercial_provenance="task12.test_catalog",
                ),
            )
        )


@dataclass(slots=True)
class _MutableApprovalAirportCatalog:
    airports: tuple[Airport, ...]
    reads: int = 0
    forbid_reads: bool = False

    async def catalog_snapshot(self) -> AirportCatalogSnapshot:
        if self.forbid_reads:
            raise AssertionError("approved execution must not re-read the mutable airport catalog")
        self.reads += 1
        return freeze_airport_catalog(self.airports)


@dataclass(slots=True)
class MutableClock:
    value: datetime = NOW

    def __call__(self) -> datetime:
        return self.value


@dataclass(slots=True)
class StartCall:
    params: SearchStartParams
    evidence_namespace: UUID
    request_fingerprint: str


@dataclass(slots=True)
class CalendarCall:
    params: CalendarSearchParams
    evidence_namespace: UUID
    request_fingerprint: str


@dataclass(slots=True)
class AnywhereCall:
    params: AnywhereDiscoveryParams
    evidence_namespace: UUID
    request_fingerprint: str


@dataclass(slots=True)
class ResumableFakeGateway:
    """Fixture gateway with real start + resumable poll semantics."""

    clock: MutableClock
    start_behaviors: list[BaseException | None] = field(default_factory=list)
    poll_behaviors: list[BaseException | Literal["evidence"] | int] = field(
        default_factory=lambda: ["evidence"]
    )
    calendar_behaviors: list[BaseException | None] = field(default_factory=list)
    calendar_results: list[tuple[DiscoverySignal, ...]] = field(default_factory=list)
    anywhere_results: list[tuple[DiscoverySignal, ...]] = field(default_factory=list)
    exact_amounts: dict[date, int] = field(default_factory=dict)
    start_calls: list[StartCall] = field(default_factory=list)
    poll_calls: list[ExactSearchContinuation] = field(default_factory=list)
    calendar_calls: list[CalendarCall] = field(default_factory=list)
    anywhere_calls: list[AnywhereCall] = field(default_factory=list)
    booking_descriptor_batches: list[int] = field(default_factory=list)
    advance_on_start_seconds: int = 0
    advance_on_poll_seconds: int = 0
    connecting_evidence: bool = False
    private_booking_descriptor: bool = False
    private_booking_results_url: str | None = None
    preserve_calendar_ids: bool = False
    evidence_observed_at: datetime | None = None
    connection_airport: str = "AMS"

    @property
    def provider_calls(self) -> int:
        return (
            len(self.start_calls)
            + len(self.poll_calls)
            + len(self.calendar_calls)
            + len(self.anywhere_calls)
        )

    async def start_exact(
        self,
        params: SearchStartParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> ExactSearchContinuation:
        self.start_calls.append(StartCall(params, evidence_namespace, request_fingerprint))
        if self.advance_on_start_seconds:
            self.clock.value += timedelta(seconds=self.advance_on_start_seconds)
        behavior = self.start_behaviors.pop(0) if self.start_behaviors else None
        if behavior is not None:
            raise behavior
        return ExactSearchContinuation(
            search_id=f"search-{len(self.start_calls)}",
            results_url="results.aviasales.ru",
            last_update_timestamp=0,
            request_id=f"request-{len(self.start_calls)}",
            evidence_namespace=evidence_namespace,
            expected_origin=params.origin.code,
            expected_destination=params.destination.code,
            expected_departure_date=date.fromisoformat(params.departure_date),
            expected_return_date=(
                date.fromisoformat(params.return_date) if params.return_date is not None else None
            ),
            expected_currency=params.currency,
            passengers=params.passengers,
        )

    async def poll_exact_once(
        self,
        continuation: ExactSearchContinuation,
        *,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> ExactPollOutcome:
        assert request_fingerprint
        self.poll_calls.append(continuation)
        if self.advance_on_poll_seconds:
            self.clock.value += timedelta(seconds=self.advance_on_poll_seconds)
        behavior = self.poll_behaviors.pop(0) if self.poll_behaviors else "evidence"
        if isinstance(behavior, BaseException):
            raise behavior
        if isinstance(behavior, int):
            return ExactPollOutcome(evidence=(), next_cursor=behavior, complete=False)
        evidence = self.evidence_for(continuation)
        descriptors = (
            (
                PrivateBookingActionDescriptor(
                    evidence_id=evidence.id,
                    provider_id="aviasales_search",
                    value={
                        "provider_id": "aviasales_search",
                        "search_id": continuation.search_id,
                        "proposal_id": "PRIVATE-proposal-id",
                        "results_url": (
                            self.private_booking_results_url or continuation.results_url
                        ),
                    },
                ),
            )
            if self.private_booking_descriptor
            else ()
        )
        self.booking_descriptor_batches.append(len(descriptors))
        return ExactPollOutcome(
            evidence=(evidence,),
            next_cursor=continuation.last_update_timestamp + 1,
            complete=False,
            booking_descriptors=descriptors,
        )

    async def calendar(
        self,
        params: CalendarSearchParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> tuple[DiscoverySignal, ...]:
        self.calendar_calls.append(CalendarCall(params, evidence_namespace, request_fingerprint))
        behavior = self.calendar_behaviors.pop(0) if self.calendar_behaviors else None
        if behavior is not None:
            raise behavior
        if self.calendar_results:
            return tuple(
                (
                    signal
                    if self.preserve_calendar_ids
                    else replace(
                        signal,
                        id=_calendar_signal_id(evidence_namespace, signal),
                    )
                )
                for signal in self.calendar_results[0]
                if params.depart_from <= signal.departure_date <= params.depart_to
            )
        return ()

    async def discover_anywhere(
        self,
        params: AnywhereDiscoveryParams,
        *,
        evidence_namespace: UUID,
        request_fingerprint: str,
        **_kwargs: object,
    ) -> tuple[DiscoverySignal, ...]:
        self.anywhere_calls.append(AnywhereCall(params, evidence_namespace, request_fingerprint))
        if not self.anywhere_results:
            return ()
        result_index = min(len(self.anywhere_calls) - 1, len(self.anywhere_results) - 1)
        return tuple(
            replace(signal, id=_anywhere_signal_id(evidence_namespace, signal))
            for signal in self.anywhere_results[result_index]
        )

    def evidence_for(self, continuation: ExactSearchContinuation) -> ConfirmedOfferEvidence:
        amount = self.exact_amounts.get(continuation.expected_departure_date, 20_000)
        connection_airport = self.connection_airport
        if (
            self.connecting_evidence
            and continuation.expected_origin != connection_airport
            and continuation.expected_destination != connection_airport
        ):
            segments = (
                FlightSegmentSummary(
                    airline_code="FV",
                    airline_name="Fixture Air",
                    flight_number="FV100",
                    origin=continuation.expected_origin,
                    destination=connection_airport,
                    depart_at=f"{continuation.expected_departure_date.isoformat()} 08:00",
                    arrive_at=f"{continuation.expected_departure_date.isoformat()} 10:00",
                    depart_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        8,
                        tzinfo=UTC,
                    ),
                    arrive_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        10,
                        tzinfo=UTC,
                    ),
                ),
                FlightSegmentSummary(
                    airline_code="FV",
                    airline_name="Fixture Air",
                    flight_number="FV101",
                    origin=connection_airport,
                    destination=continuation.expected_destination,
                    depart_at=f"{continuation.expected_departure_date.isoformat()} 11:00",
                    arrive_at=f"{continuation.expected_departure_date.isoformat()} 13:00",
                    depart_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        11,
                        tzinfo=UTC,
                    ),
                    arrive_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        13,
                        tzinfo=UTC,
                    ),
                ),
            )
        else:
            depart_hour = (
                8
                if continuation.expected_destination == connection_airport
                else 13
                if continuation.expected_origin == connection_airport
                else 10
            )
            arrive_hour = depart_hour + 2
            segments = (
                FlightSegmentSummary(
                    airline_code="FV",
                    airline_name="Fixture Air",
                    flight_number="FV100",
                    origin=continuation.expected_origin,
                    destination=continuation.expected_destination,
                    depart_at=(
                        f"{continuation.expected_departure_date.isoformat()} {depart_hour:02d}:00"
                    ),
                    arrive_at=(
                        f"{continuation.expected_departure_date.isoformat()} {arrive_hour:02d}:00"
                    ),
                    depart_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        depart_hour,
                        tzinfo=UTC,
                    ),
                    arrive_at_utc=datetime(
                        continuation.expected_departure_date.year,
                        continuation.expected_departure_date.month,
                        continuation.expected_departure_date.day,
                        arrive_hour,
                        tzinfo=UTC,
                    ),
                ),
            )
        if continuation.expected_return_date is not None:
            if self.connecting_evidence:
                segments += (
                    FlightSegmentSummary(
                        airline_code="FV",
                        airline_name="Fixture Air",
                        flight_number="FV102",
                        origin=continuation.expected_destination,
                        destination=connection_airport,
                        depart_at=f"{continuation.expected_return_date.isoformat()} 08:00",
                        arrive_at=f"{continuation.expected_return_date.isoformat()} 10:00",
                        depart_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            8,
                            tzinfo=UTC,
                        ),
                        arrive_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            10,
                            tzinfo=UTC,
                        ),
                    ),
                    FlightSegmentSummary(
                        airline_code="FV",
                        airline_name="Fixture Air",
                        flight_number="FV103",
                        origin=connection_airport,
                        destination=continuation.expected_origin,
                        depart_at=f"{continuation.expected_return_date.isoformat()} 11:00",
                        arrive_at=f"{continuation.expected_return_date.isoformat()} 13:00",
                        depart_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            11,
                            tzinfo=UTC,
                        ),
                        arrive_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            13,
                            tzinfo=UTC,
                        ),
                    ),
                )
            else:
                segments += (
                    FlightSegmentSummary(
                        airline_code="FV",
                        airline_name="Fixture Air",
                        flight_number="FV101",
                        origin=continuation.expected_destination,
                        destination=continuation.expected_origin,
                        depart_at=f"{continuation.expected_return_date.isoformat()} 10:00",
                        arrive_at=f"{continuation.expected_return_date.isoformat()} 12:00",
                        depart_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            10,
                            tzinfo=UTC,
                        ),
                        arrive_at_utc=datetime(
                            continuation.expected_return_date.year,
                            continuation.expected_return_date.month,
                            continuation.expected_return_date.day,
                            12,
                            tzinfo=UTC,
                        ),
                    ),
                )
        provider_offer_id = (
            "aviasales_search:"
            + uuid5(
                continuation.evidence_namespace,
                continuation.expected_departure_date.isoformat(),
            ).hex
        )
        return ConfirmedOfferEvidence(
            id=uuid5(
                continuation.evidence_namespace,
                f"exact|{provider_offer_id}|{continuation.passengers}",
            ),
            provider_id="aviasales_search",
            provider_offer_id=provider_offer_id,
            origin=continuation.expected_origin,
            destination=continuation.expected_destination,
            departure_date=continuation.expected_departure_date,
            return_date=continuation.expected_return_date,
            total_amount=Money(amount, continuation.expected_currency),
            passengers=continuation.passengers,
            observed_at=self.evidence_observed_at or self.clock(),
            segment_ids=tuple(
                uuid5(continuation.evidence_namespace, f"segment:{index}").hex
                for index, _segment in enumerate(segments)
            ),
            segments=segments,
            protection_status=ProtectionStatus.UNKNOWN,
            seller_name="Fixture seller",
            baggage_summary=None,
        )


@pytest.mark.parametrize(
    "field_name",
    ("operation_lease_seconds", "circuit_cooldown_seconds", "poll_interval_seconds"),
)
def test_execution_policy_accepts_bounded_temporal_maximum(
    execution_module: ModuleType,
    field_name: str,
) -> None:
    values = {
        "provider_rpm": 20,
        "operation_lease_seconds": 60,
        "circuit_failure_threshold": 5,
        "circuit_cooldown_seconds": 120,
        "circuit_probe_lease_seconds": 30,
        "poll_interval_seconds": 2,
    }
    values[field_name] = 3600

    policy = execution_module.AgentExecutionPolicy(**values)

    assert getattr(policy, field_name) == 3600


@pytest.mark.parametrize(
    ("field_name", "value"),
    tuple(
        (field_name, value)
        for field_name in (
            "operation_lease_seconds",
            "circuit_cooldown_seconds",
            "poll_interval_seconds",
        )
        for value in (3601, 10**30)
    ),
)
def test_execution_policy_rejects_unbounded_temporal_values(
    execution_module: ModuleType,
    field_name: str,
    value: int,
) -> None:
    values = {
        "provider_rpm": 20,
        "operation_lease_seconds": 60,
        "circuit_failure_threshold": 5,
        "circuit_cooldown_seconds": 120,
        "circuit_probe_lease_seconds": 30,
        "poll_interval_seconds": 2,
    }
    values[field_name] = value

    with pytest.raises(ValueError, match="cannot exceed 3600 seconds"):
        execution_module.AgentExecutionPolicy(**values)


@pytest.mark.anyio
async def test_run_next_pages_past_future_waiting_runs_to_reach_later_runnable_work(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "candidate-pagination.db")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    candidates = tuple(
        SimpleNamespace(household_id=HOUSEHOLD_ID, id=UUID(int=index + 1)) for index in range(5)
    )

    class PagedRuns:
        async def list_execution_candidates(self, *, limit: int, after=None):
            start = 0
            if after is not None:
                start = (
                    next(
                        index
                        for index, candidate in enumerate(candidates)
                        if candidate.id == after.id
                    )
                    + 1
                )
            return candidates[start : start + limit]

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            candidate_page_size=2,
        )
        service._runs = PagedRuns()
        visited: list[UUID] = []

        async def fake_run_step(*, household_id: UUID, run_id: UUID):
            assert household_id == HOUSEHOLD_ID
            visited.append(run_id)
            if run_id == candidates[-1].id:
                return execution_module.AgentExecutionStep(True, "succeeded", "running")
            return execution_module.AgentExecutionStep(False, None, "running")

        service.run_step = fake_run_step
        result = await service.run_next()

    assert result.operation_claimed is True
    assert visited == [candidate.id for candidate in candidates]
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_two_workers_tolerate_stale_queued_transition_with_one_provider_call(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "queued-race.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as first_session, sessions() as second_session:
        stale = await AgentRunRepository(second_session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert stale is not None and stale.status == "queued"
        first = _service(
            execution_module,
            first_session,
            gateway,
            clock,
            poll_interval_seconds=2,
        )
        await first.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await first_session.commit()
        await second_session.rollback()

        delegate = AgentRunRepository(second_session)

        class StaleFirstRead:
            first_read = True

            async def get_run(self, household_id: UUID, run_id: UUID):
                if self.first_read:
                    self.first_read = False
                    return stale
                return await delegate.get_run(household_id, run_id)

            def __getattr__(self, name: str):
                return getattr(delegate, name)

        second = _service(
            execution_module,
            second_session,
            gateway,
            clock,
            poll_interval_seconds=2,
        )
        second._runs = StaleFirstRead()
        result = await second.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await second_session.commit()
        operations = await AgentOperationRepository(second_session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert result.operation_claimed is False
    assert gateway.provider_calls == 1
    assert sum(operation.attempt_count for operation in operations) == 1
    await engine.dispose()


@pytest.fixture
def execution_module() -> ModuleType:
    return importlib.import_module("flight_hunter.application.agent_execution")


def test_anywhere_country_codes_reject_unicode_lookalikes(
    execution_module: ModuleType,
) -> None:
    country_code = execution_module._country_code

    with pytest.raises(ValueError, match="ISO alpha-2"):
        country_code("ФР", "allowed_country_codes")


def test_anywhere_snapshot_rejects_unbounded_discovery_horizon(
    execution_module: ModuleType,
) -> None:
    value = {
        "origin_airports": ["LED"],
        "date_start": "2026-01-01",
        "date_end": "2027-01-01",
        "allowed_country_codes": [],
        "excluded_country_codes": [],
        "discovery_source_ids": ["aviasales_hot_offers"],
        "max_destination_seeds": 40,
        "exact_verification_limit": 20,
        "catalog_checksum": "sha256:" + "a" * 64,
        "taxonomy_version": "v1",
        "eligible_destination_countries": {"CDG": "FR"},
    }
    first_plan_leg = {
        "origin": {"kind": "airport", "value": "LED"},
        "destination": {"kind": "anywhere", "value": None},
    }

    with pytest.raises(ValueError, match="bounded immutable rule"):
        execution_module._anywhere_rule_from_snapshot(  # type: ignore[attr-defined]
            value,
            first_plan_leg=first_plan_leg,
            origin_codes=("LED",),
            date_start=date(2026, 1, 1),
            date_end=date(2027, 1, 1),
            coverage="quick",
        )


@pytest.mark.anyio
async def test_exact_run_transitions_queued_running_completed_through_start_and_poll(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "exact-complete.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        queued = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert queued is not None and queued.status == "queued"
        service = _service(execution_module, session, gateway, clock)
        first_step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (started_stage,) = await AgentOperationRepository(session).list_stages(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        terminal = await _run_until_terminal(service, session)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert first_step.operation_status == "succeeded"
    assert started_stage.status is AgentStageStatus.RUNNING
    assert terminal.started_at is not None
    assert terminal.logical_operations_consumed == 1
    assert terminal.http_attempts_consumed == 2
    assert [call.params.departure_date for call in gateway.start_calls] == ["2026-09-10"]
    assert len(gateway.poll_calls) == 1
    assert gateway.start_calls[0].evidence_namespace == operations[0].id
    assert [operation.kind for operation in operations] == [
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
        AgentOperationKind.RANKING,
        AgentOperationKind.ANALYSIS,
    ]
    assert all(operation.status is AgentOperationStatus.SUCCEEDED for operation in operations)
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("not_modified", (False, True))
async def test_exact_run_repolls_after_provider_unchanged_response(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    not_modified: bool,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"exact-unchanged-{not_modified}.db",
    )
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    original_poll = ResumableFakeGateway.poll_exact_once

    async def poll_with_initial_not_modified(
        fake_gateway: ResumableFakeGateway,
        continuation: ExactSearchContinuation,
        *,
        request_fingerprint: str,
        **kwargs: object,
    ) -> ExactPollOutcome:
        if not fake_gateway.poll_calls:
            fake_gateway.poll_calls.append(continuation)
            return ExactPollOutcome(
                evidence=(),
                next_cursor=continuation.last_update_timestamp,
                complete=False,
                not_modified=not_modified,
            )
        return await original_poll(
            fake_gateway,
            continuation,
            request_fingerprint=request_fingerprint,
            **kwargs,
        )

    monkeypatch.setattr(ResumableFakeGateway, "poll_exact_once", poll_with_initial_not_modified)
    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert terminal.http_attempts_consumed == 3
    assert len(gateway.poll_calls) == 2
    assert [operation.kind for operation in operations[:3]] == [
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
        AgentOperationKind.EXACT_POLL,
    ]
    assert all(operation.status is AgentOperationStatus.SUCCEEDED for operation in operations)
    await engine.dispose()


@pytest.mark.anyio
async def test_exact_run_accepts_live_evidence_when_provider_cursor_stays_zero(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "exact-zero-cursor-evidence.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async def poll_with_zero_cursor(
        fake_gateway: ResumableFakeGateway,
        continuation: ExactSearchContinuation,
        **_kwargs: object,
    ) -> ExactPollOutcome:
        fake_gateway.poll_calls.append(continuation)
        return ExactPollOutcome(
            evidence=(fake_gateway.evidence_for(continuation),),
            next_cursor=continuation.last_update_timestamp,
            complete=False,
        )

    monkeypatch.setattr(ResumableFakeGateway, "poll_exact_once", poll_with_zero_cursor)
    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
    assert terminal.status == "completed"
    assert evidence_count == 1
    assert len(gateway.poll_calls) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_exact_run_accepts_provider_tagged_airport_change(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "exact-provider-airport-change.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=("through_ticket",),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)

    async def poll_with_airport_change(
        fake_gateway: ResumableFakeGateway,
        continuation: ExactSearchContinuation,
        **_kwargs: object,
    ) -> ExactPollOutcome:
        fake_gateway.poll_calls.append(continuation)
        base = fake_gateway.evidence_for(continuation)
        segments = (replace(base.segments[0], destination="SAW"), *base.segments[1:])
        evidence = replace(
            base,
            segments=segments,
            provider_airport_changes=(("SAW", fake_gateway.connection_airport),),
        )
        return ExactPollOutcome(
            evidence=(evidence,),
            next_cursor=continuation.last_update_timestamp + 1,
            complete=False,
        )

    monkeypatch.setattr(ResumableFakeGateway, "poll_exact_once", poll_with_airport_change)
    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
    assert terminal.status == "completed"
    assert evidence_count == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_flexible_calendar_shortlists_by_amount_recency_and_stable_tie_break(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "flexible.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
        adults=2,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    gateway.calendar_results.append(
        (
            _signal(UUID("10000000-0000-0000-0000-000000000003"), date(2026, 9, 12), 30_000),
            _signal(
                UUID("10000000-0000-0000-0000-000000000002"),
                date(2026, 9, 11),
                10_000,
                observed_at=NOW + timedelta(seconds=2),
            ),
            _signal(
                UUID("10000000-0000-0000-0000-000000000001"),
                date(2026, 9, 10),
                10_000,
                observed_at=NOW + timedelta(seconds=1),
            ),
        )
    )
    clock.value = NOW + timedelta(seconds=3)
    gateway.exact_amounts = {
        date(2026, 9, 10): 19_000,
        date(2026, 9, 11): 18_000,
    }

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        terminal = await _run_until_terminal(service, session, limit=20)
        signal_count = (
            await session.execute(select(func.count()).select_from(agent_discovery_signals_table))
        ).scalar_one()
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
        ranking = (await session.execute(select(agent_ranking_snapshots_table))).mappings().one()
        stored_signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        stored_evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        await session.rollback()
        run_view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "partial"
    assert terminal.error_code == "agent_run_partial"
    assert run_view.coverage_report is not None
    assert (
        run_view.coverage_report.planned,
        run_view.coverage_report.attempted,
        run_view.coverage_report.succeeded,
        run_view.coverage_report.failed,
        run_view.coverage_report.skipped,
    ) == (5, 5, 3, 2, 0)
    assert run_view.coverage_report.reason_counts == {"agent_no_discovery_results": 2}
    assert signal_count == 3
    assert {signal.freshness for signal in stored_signals} == {Freshness.LIVE}
    assert evidence_count == 3
    assert len(gateway.calendar_calls) == 5
    assert [call.params.depart_from for call in gateway.calendar_calls] == [
        date(2026, 9, day) for day in range(8, 13)
    ]
    assert all(call.params.depart_from == call.params.depart_to for call in gateway.calendar_calls)
    assert gateway.calendar_calls[0].params.adults == 1
    assert gateway.calendar_calls[0].params.children == 0
    assert gateway.calendar_calls[0].params.infants == 0
    assert {signal.passengers for signal in stored_signals} == {1}
    assert {signal.passenger_basis for signal in stored_signals} == {
        PriceBasis.PROVIDER_SINGLE_ADULT_TICKET
    }
    assert {call.params.departure_date for call in gateway.start_calls} == {
        "2026-09-10",
        "2026-09-11",
        "2026-09-12",
    }
    assert len(gateway.start_calls) == 3
    assert {call.params.passengers for call in gateway.start_calls} == {2}
    assert {evidence.passengers for evidence in stored_evidence} == {2}
    assert {evidence.passenger_basis for evidence in stored_evidence} == {
        PriceBasis.TOTAL_FOR_PASSENGERS
    }
    ranked_ids = set(json.loads(ranking["confirmed_evidence_ids_json"]))
    signal_ids = {str(signal.id) for signal in stored_signals}
    assert ranked_ids
    assert ranked_ids.isdisjoint(signal_ids)
    assert json.loads(ranking["composed_candidate_ids_json"]) == []
    await engine.dispose()


@pytest.mark.anyio
async def test_calendar_duplicate_date_pairs_materialize_one_deterministic_exact_workflow(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "calendar-date-dedupe.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock(NOW + timedelta(seconds=3))
    gateway = ResumableFakeGateway(clock)
    gateway.calendar_results.append(
        (
            _signal(uuid4(), date(2026, 9, 10), 9_000, observed_at=NOW),
            _signal(
                uuid4(),
                date(2026, 9, 10),
                10_000,
                observed_at=NOW + timedelta(seconds=1),
            ),
            _signal(uuid4(), date(2026, 9, 11), 15_000, observed_at=NOW),
        )
    )

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        await session.rollback()
        run_view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "partial"
    assert terminal.error_code == "agent_run_partial"
    assert run_view.coverage_report is not None
    assert (
        run_view.coverage_report.planned,
        run_view.coverage_report.attempted,
        run_view.coverage_report.succeeded,
        run_view.coverage_report.failed,
        run_view.coverage_report.skipped,
    ) == (5, 5, 2, 3, 0)
    assert run_view.coverage_report.reason_counts == {"agent_no_discovery_results": 3}
    assert len(signals) == 2
    assert [call.params.departure_date for call in gateway.start_calls] == [
        "2026-09-10",
        "2026-09-11",
    ]
    assert len(gateway.poll_calls) == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_calendar_retry_reuses_operation_namespace_and_deduplicates_repeated_signal(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "calendar-namespace-retry.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock()
    repeated = _signal(uuid4(), date(2026, 9, 8), 9_000)
    gateway = ResumableFakeGateway(
        clock,
        calendar_behaviors=[AviasalesSearchTransportError()],
        calendar_results=[(repeated, repeated)],
    )

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        first = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        calendar = next(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.CALENDAR_SEARCH
            and operation.immutable_input["departure_date"] == "2026-09-08"
        )
        assert calendar.next_retry_at is not None
        clock.value = calendar.next_retry_at
        remaining_steps = [
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID) for _ in range(5)
        ]
        await session.commit()
        signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert first.operation_status == "retry_wait"
    assert remaining_steps[-1].operation_status == "succeeded"
    assert gateway.provider_calls == 6
    assert len(signals) == 1
    assert signals[0].id == _calendar_signal_id(calendar.id, repeated)
    exact_starts = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    assert len(exact_starts) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_calendar_signal_from_another_operation_namespace_is_provider_schema(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "calendar-wrong-namespace.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock()
    source = _signal(uuid4(), date(2026, 9, 8), 9_000)
    wrong_namespace = uuid4()
    gateway = ResumableFakeGateway(
        clock,
        calendar_results=[(replace(source, id=_calendar_signal_id(wrong_namespace, source)),)],
        preserve_calendar_ids=True,
    )

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=16,
        )
        signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "failed"
    assert terminal.error_code == "provider_schema"
    assert signals == ()
    assert evidence == ()
    assert all(operation.kind is not AgentOperationKind.EXACT_START for operation in operations)
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("date_mode", "expected_end"),
    (
        ("range", date(2026, 9, 12)),
        ("rolling_90_days", date(2026, 12, 8)),
    ),
)
async def test_calendar_uses_validated_range_and_rolling_snapshot_bounds(
    tmp_path: Path,
    execution_module: ModuleType,
    date_mode: Literal["range", "rolling_90_days"],
    expected_end: date,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"calendar-{date_mode}.db")
    surface = (expected_end - date(2026, 9, 10)).days + 1
    await _seed_run(
        sessions,
        date_mode=date_mode,
        calendar_searches=surface,
        exact_searches=surface,
        logical_budget=surface * 2,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert len(gateway.calendar_calls) == 1
    assert gateway.calendar_calls[0].params.depart_from == date(2026, 9, 10)
    assert gateway.calendar_calls[0].params.depart_to == date(2026, 9, 10)
    calendar_dates = sorted(
        operation.immutable_input["departure_date"]
        for operation in operations
        if operation.kind is AgentOperationKind.CALENDAR_SEARCH
    )
    assert len(calendar_dates) == surface
    assert calendar_dates[0] == "2026-09-10"
    assert calendar_dates[-1] == expected_end.isoformat()
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("trip_shape", ("open_jaw", "multi_city"))
async def test_unknown_native_multi_leg_capability_materializes_ordered_per_leg_exact_searches(
    tmp_path: Path,
    execution_module: ModuleType,
    trip_shape: Literal["open_jaw", "multi_city"],
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"per-leg-{trip_shape}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        trip_shape=trip_shape,
        exact_searches=2,
        logical_budget=2,
        adults=1,
        children=1,
        infants=1,
        requested_strategies=("through_ticket",),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)

    exact_starts = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    assert step.operation_claimed is True
    assert len(exact_starts) == 2
    assert [
        (
            operation.immutable_input["origin"],
            operation.immutable_input["destination"],
            operation.immutable_input["departure_date"],
            operation.immutable_input["return_date"],
            operation.immutable_input["passengers"],
        )
        for operation in exact_starts
    ] == [
        ("LED", "CDG", "2026-09-10", None, 3),
        ("CDG", "LED", "2026-09-20", None, 3),
    ]
    assert len(gateway.start_calls) == 1
    assert gateway.start_calls[0].params.return_date is None
    await engine.dispose()


@pytest.mark.anyio
async def test_multi_city_ranks_only_the_full_composed_route_not_individual_legs(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "multi-city-composed-ranking.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        trip_shape="multi_city",
        exact_searches=2,
        logical_budget=2,
        poll_rounds=1,
        analysis_modes=("buy_timing",),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=16,
        )
        evidence_repository = AgentEvidenceRepository(session)
        composed = await evidence_repository.list_composed_candidates(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        ranking_operation = next(
            operation for operation in operations if operation.kind is AgentOperationKind.RANKING
        )
        assert ranking_operation.result_id is not None
        ranking_record = await evidence_repository.get_ranking_snapshot(
            HOUSEHOLD_ID,
            ranking_operation.result_id,
        )
        analysis_record = await evidence_repository.get_analysis_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        await session.rollback()
        results = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
        ).get_run_results(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "completed"
    assert len(composed) == 1
    assert len(composed[0].component_evidence_ids) == 2
    assert ranking_record is not None
    ranking = ranking_snapshot_from_payload(ranking_record.ranking)
    assert ranking.confirmed_evidence_ids == ()
    assert ranking.composed_candidate_ids == (composed[0].id,)
    assert all(
        candidate.reference.kind is CandidateKind.COMPOSED_ROUTE
        for view in ranking.views
        for candidate in view.candidates
    )
    assert results.state == "ready"
    assert results.report is not None
    assert results.report.ranking == ranking
    assert analysis_record is not None
    assert analysis_record.analysis["scope_status"] == "unsupported_trip_structure"
    assert analysis_record.analysis["scope_reason"] == "full_itinerary_history_unavailable"
    assert "buy_timing" not in analysis_record.analysis
    assert "stored-evidence:" not in repr(results.report)
    await engine.dispose()


@pytest.mark.anyio
async def test_confirmed_result_uses_opaque_household_scoped_booking_descriptor(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "opaque-booking-descriptor.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        poll_rounds=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        private_booking_descriptor=True,
    )
    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=12,
        )
        await session.rollback()
        results = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
            booking_action_secret="test-agent-booking-secret",
        ).get_run_results(HOUSEHOLD_ID, PLAN_ID, RUN_ID)
        descriptors = await AgentEvidenceRepository(session).list_booking_action_descriptors(
            HOUSEHOLD_ID,
            RUN_ID,
            active_at=clock(),
        )

    assert terminal.status == "completed"
    assert results.state == "ready"
    assert results.report is not None
    assert gateway.booking_descriptor_batches == [1]
    assert len(descriptors) == 1
    (fact,) = results.report.candidates
    assert fact.booking_action.available is True
    assert fact.booking_action.token is not None
    payload = verify_agent_booking_action_token(
        fact.booking_action.token,
        secret_key="test-agent-booking-secret",
        now=clock(),
    )
    assert payload.descriptor_id == descriptors[0].id
    rendered = repr((results, descriptors))
    assert "PRIVATE-proposal-id" not in rendered
    assert "results.aviasales.ru" not in rendered
    await engine.dispose()


@pytest.mark.anyio
async def test_invalid_private_booking_descriptor_is_classified_without_losing_evidence(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "invalid-booking-descriptor.db")
    await _seed_run(sessions, date_mode="exact", poll_rounds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        private_booking_descriptor=True,
        private_booking_results_url="https://private-invalid.example.test/path",
    )

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=12,
        )
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        descriptors = await AgentEvidenceRepository(session).list_booking_action_descriptors(
            HOUSEHOLD_ID,
            RUN_ID,
            active_at=clock(),
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    poll = next(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
    )
    assert terminal.status == "partial"
    assert terminal.error_code == "agent_run_partial"
    assert len(evidence) == 1
    assert descriptors == ()
    assert poll.status is AgentOperationStatus.FAILED
    assert poll.error_code == "agent_booking_descriptor_invalid"
    await engine.dispose()


@pytest.mark.anyio
async def test_corrupt_confirmed_evidence_fails_ranking_operation_without_stale_lease(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "corrupt-ranking-input.db")
    await _seed_run(sessions, date_mode="exact", poll_rounds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await session.execute(
            update(agent_confirmed_offer_evidence_table)
            .where(agent_confirmed_offer_evidence_table.c.run_id == str(RUN_ID))
            .values(itinerary_evidence_json="{}")
        )
        await session.commit()

        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    ranking = next(
        operation for operation in operations if operation.kind is AgentOperationKind.RANKING
    )
    assert step.operation_status == "failed"
    assert step.run_status == "failed"
    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_confirmed_evidence_invalid"
    assert ranking.status is AgentOperationStatus.FAILED
    assert ranking.lease_owner is None
    assert ranking.lease_expires_at is None
    await engine.dispose()


@pytest.mark.anyio
async def test_no_lease_restart_maps_corrupt_workflow_advance_to_failed_run(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "no-lease-corrupt-restart.db")
    await _seed_run(sessions, date_mode="exact", poll_rounds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.run_id == str(RUN_ID))
            .where(agent_run_operations_table.c.operation_kind == "ranking")
            .values(
                status="failed",
                error_code="agent_confirmed_evidence_invalid",
                completed_at=NOW,
                updated_at=NOW,
            )
        )
        await session.execute(
            update(agent_confirmed_offer_evidence_table)
            .where(agent_confirmed_offer_evidence_table.c.run_id == str(RUN_ID))
            .values(itinerary_evidence_json="{}")
        )
        await session.commit()

        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert step.operation_claimed is False
    assert step.run_status == "failed"
    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_confirmed_evidence_invalid"
    assert gateway.provider_calls == 2
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("return_tamper", ("intent", "scope"))
async def test_round_trip_requires_reciprocal_intent_and_frozen_return_leg(
    tmp_path: Path,
    execution_module: ModuleType,
    return_tamper: Literal["intent", "scope"],
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"round-trip-{return_tamper}.db")
    await _seed_run(
        sessions,
        date_mode="range",
        trip_shape="round_trip",
        return_tamper=return_tamper,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_plan_snapshot_invalid"
    assert terminal.http_attempts_consumed == 0
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_reciprocal_round_trip_binds_the_approved_return_date(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "round-trip-valid.db")
    await _seed_run(sessions, date_mode="exact", trip_shape="round_trip")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()

    assert len(gateway.start_calls) == 1
    assert gateway.start_calls[0].params.origin.code == "LED"
    assert gateway.start_calls[0].params.destination.code == "CDG"
    assert gateway.start_calls[0].params.return_date == "2026-09-20"
    await engine.dispose()


@pytest.mark.anyio
async def test_invalid_or_not_yet_discovered_scope_fails_before_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "invalid-return-scope.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=1,
        logical_budget=1,
        trip_shape="round_trip",
        scope_variant="return_extra",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        circuit_rows = (
            await session.execute(
                select(func.count()).select_from(agent_provider_circuit_state_table)
            )
        ).scalar_one()

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_plan_snapshot_invalid"
    assert terminal.http_attempts_consumed == 0
    assert operations == ()
    assert circuit_rows == reservations == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scope_variant", "destinations"),
    (
        ("city", {"CDG", "ORY"}),
        ("region", {"AMS", "CDG", "FRA", "LHR"}),
        ("nearby", {"CDG", "ORY"}),
    ),
)
async def test_task10_finite_scope_modes_execute_every_frozen_pair(
    tmp_path: Path,
    execution_module: ModuleType,
    scope_variant: Literal["city", "region", "nearby"],
    destinations: set[str],
) -> None:
    exact_searches = len(destinations)
    engine, sessions = await _session_factory(tmp_path, f"finite-{scope_variant}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=exact_searches,
        logical_budget=exact_searches,
        scope_variant=scope_variant,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=20,
        )

    assert terminal.status == "completed"
    assert {call.params.destination.code for call in gateway.start_calls} == destinations
    assert len(gateway.poll_calls) == exact_searches
    await engine.dispose()


@pytest.mark.anyio
async def test_task10_full_country_scope_executes_every_frozen_airport_pair(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "full-country-coverage.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=4,
        logical_budget=4,
        scope_variant="country",
        coverage="full",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=16,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert {
        (call.params.origin.code, call.params.destination.code) for call in gateway.start_calls
    } == {
        ("LED", "CDG"),
        ("LED", "LYS"),
        ("LED", "NCE"),
        ("LED", "ORY"),
    }
    assert len(gateway.poll_calls) == 4
    assert sum(operation.kind is AgentOperationKind.EXACT_START for operation in operations) == 4
    await engine.dispose()


@pytest.mark.anyio
async def test_task10_full_country_failure_is_partial_with_per_pair_reason(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "full-country-partial.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=4,
        logical_budget=4,
        scope_variant="country",
        coverage="full",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchSchemaError()],
    )

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=18,
        )
        await session.rollback()
        view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "partial"
    assert view.coverage_report is not None
    report = view.coverage_report
    assert report.coverage == "full"
    assert report.completion == "partial"
    assert (report.planned, report.attempted, report.succeeded, report.failed, report.skipped) == (
        4,
        4,
        3,
        1,
        0,
    )
    assert report.reason_counts == {"provider_schema": 1}
    assert (
        sum(pair.status == "failed" and pair.reason == "provider_schema" for pair in report.pairs)
        == 1
    )
    await engine.dispose()


@pytest.mark.anyio
async def test_task10_terminal_run_is_partial_when_frozen_pair_was_never_materialized(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "full-country-missing-root.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=4,
        logical_budget=4,
        scope_variant="country",
        coverage="full",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        workflow = await service._workflow(run)
        stage = await service._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=clock.value,
        )
        first = workflow.route_pairs[0]
        await service._materialize_exact_start(
            run,
            stage.id,
            workflow,
            origin=first.origin,
            destination=first.destination,
            departure_date=workflow.departure_date,
            return_date=workflow.return_date,
            ordinal=0,
            now=clock.value,
        )
        await session.commit()

        terminal = await _run_until_terminal(service, session, limit=8)

    assert terminal.status == "partial"
    assert terminal.error_code == "agent_run_partial"
    assert len(gateway.start_calls) == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_task10_anywhere_freezes_first_discovery_snapshot_and_ignores_later_seeds(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-snapshot.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    cdg = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    ory = replace(
        _signal(uuid4(), date(2026, 9, 10), 10_000),
        destination="ORY",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    nce = replace(
        _signal(uuid4(), date(2026, 9, 10), 5_000),
        destination="NCE",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(cdg, ory)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        for _ in range(4):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
        snapshot = await AgentOperationRepository(session).get_scope_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert snapshot is not None
        first_snapshot = dict(snapshot.snapshot)
        gateway.anywhere_results[:] = [(nce,)]
        terminal = await _run_until_terminal(service, session, limit=16)
        repeated = await AgentOperationRepository(session).get_scope_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert first_snapshot["destinations"] == ("ORY", "CDG")
    assert len(first_snapshot["source_signal_ids"]) == 2
    assert repeated is not None and dict(repeated.snapshot) == first_snapshot
    assert len(gateway.anywhere_calls) == 1
    assert {call.params.destination.code for call in gateway.start_calls} == {"CDG", "ORY"}
    assert "NCE" not in {call.params.destination.code for call in gateway.start_calls}
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_exact_start_uses_explicit_frozen_source_signal_id(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-source-binding.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    cdg = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(cdg,)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        starts = ()
        for _ in range(6):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            starts = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.EXACT_START
            )
            if starts:
                break
        snapshot = await AgentOperationRepository(session).get_scope_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert snapshot is not None
    assert len(starts) == 1
    assert (
        starts[0].immutable_input["source_signal_id"] == snapshot.snapshot["source_signal_ids"][0]
    )
    assert "value" not in starts[0].immutable_input
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("tamper", ("missing", "malformed", "foreign"))
async def test_anywhere_exact_source_tamper_fails_before_additional_permit_or_io(
    tmp_path: Path,
    execution_module: ModuleType,
    tamper: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"anywhere-source-{tamper}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        start = None
        for _ in range(6):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            start = next(
                (
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.EXACT_START
                ),
                None,
            )
            if start is not None:
                break
        assert start is not None
        before_calls = gateway.provider_calls
        before_http = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        tampered = dict(start.immutable_input)
        if tamper == "missing":
            tampered.pop("source_signal_id")
        elif tamper == "malformed":
            tampered["source_signal_id"] = "not-a-uuid"
        else:
            tampered["source_signal_id"] = str(uuid4())
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(start.id))
            .values(immutable_input_json=json.dumps(tampered, separators=(",", ":")))
        )
        await session.commit()

        terminal = await _run_until_terminal(service, session, limit=8)
        after_http = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert gateway.provider_calls == before_calls == 1
    assert after_http == before_http == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_poll_revalidates_tampered_root_source_before_new_io(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-poll-root-source.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        root = None
        poll = None
        for _ in range(10):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            root = next(
                (
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.EXACT_START
                    and operation.status is AgentOperationStatus.SUCCEEDED
                ),
                None,
            )
            poll = next(
                (
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.EXACT_POLL
                    and operation.status is AgentOperationStatus.PENDING
                ),
                None,
            )
            if root is not None and poll is not None:
                break
        assert root is not None and poll is not None
        tampered = dict(root.immutable_input)
        tampered["source_signal_id"] = str(uuid4())
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(root.id))
            .values(immutable_input_json=json.dumps(tampered, separators=(",", ":")))
        )
        await session.commit()
        calls_before = gateway.provider_calls
        reservations_before = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

        terminal = await _run_until_terminal(service, session, limit=6)
        reservations_after = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert gateway.provider_calls == calls_before == 2
    assert reservations_after == reservations_before == 2
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("tamper", ("duplicate", "swapped"))
async def test_anywhere_exact_source_set_tamper_is_rejected_atomically_before_io(
    tmp_path: Path,
    execution_module: ModuleType,
    tamper: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"anywhere-source-set-{tamper}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    cdg = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    ory = replace(
        _signal(uuid4(), date(2026, 9, 10), 10_000),
        destination="ORY",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(cdg, ory)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        starts: tuple[object, ...] = ()
        for _ in range(6):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            starts = tuple(
                operation
                for operation in operations
                if operation.kind is AgentOperationKind.EXACT_START
            )
            if len(starts) == 2:
                break
        assert len(starts) == 2
        first, second = starts
        first_input = dict(first.immutable_input)  # type: ignore[attr-defined]
        second_input = dict(second.immutable_input)  # type: ignore[attr-defined]
        first_source = first_input["source_signal_id"]
        second_source = second_input["source_signal_id"]
        if tamper == "duplicate":
            second_input["source_signal_id"] = first_source
        else:
            first_input["source_signal_id"] = second_source
            second_input["source_signal_id"] = first_source
        for operation, payload in ((first, first_input), (second, second_input)):
            await session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(operation.id))  # type: ignore[attr-defined]
                .values(immutable_input_json=json.dumps(payload, separators=(",", ":")))
            )
        await session.commit()
        before_calls = gateway.provider_calls
        before_http = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

        terminal = await _run_until_terminal(service, session, limit=8)
        after_http = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert gateway.provider_calls == before_calls == 1
    assert after_http == before_http == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_discovery_skips_nonmatching_rows_and_caps_before_persistence(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-provider-cap.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=2,
        logical_budget=4,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=2,
    )
    clock = MutableClock()
    eligible = (
        replace(
            _signal(uuid4(), date(2026, 9, 10), 20_000),
            source_kind=DiscoverySource.HOT_OFFER,
        ),
        replace(
            _signal(uuid4(), date(2026, 9, 10), 15_000),
            source_kind=DiscoverySource.HOT_OFFER,
        ),
        replace(
            _signal(uuid4(), date(2026, 9, 10), 10_000),
            destination="ORY",
            source_kind=DiscoverySource.HOT_OFFER,
        ),
        replace(
            _signal(uuid4(), date(2026, 9, 10), 5_000),
            destination="NCE",
            source_kind=DiscoverySource.HOT_OFFER,
        ),
    )
    outside_window = replace(
        _signal(uuid4(), date(2026, 9, 11), 1_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    ineligible_catalog = replace(
        _signal(uuid4(), date(2026, 9, 10), 500),
        destination="FRA",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(
        clock,
        anywhere_results=[(*eligible, outside_window, ineligible_catalog)],
    )

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        stored = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == AgentOperationStatus.SUCCEEDED.value
    assert {(signal.destination, signal.amount_minor) for signal in stored} == {
        ("NCE", 5_000),
        ("ORY", 10_000),
    }
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_discovery_runs_every_origin_and_freezes_cheapest_duplicate(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-origin-breadth.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=1,
        logical_budget=3,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=1,
        anywhere_origin_airports=("LED", "SVO"),
    )
    clock = MutableClock()
    led_signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    svo_signal = replace(
        led_signal,
        id=uuid4(),
        origin="SVO",
        observed_amount=Money(12_000, "RUB"),
        observed_at=NOW + timedelta(minutes=6),
    )
    gateway = ResumableFakeGateway(
        clock,
        anywhere_results=[(led_signal,), (svo_signal,)],
    )

    async with sessions() as session:
        first_step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        assert first_step.operation_status == AgentOperationStatus.SUCCEEDED.value
        clock.value += timedelta(minutes=6)
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=16,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        snapshot = await AgentOperationRepository(session).get_scope_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    suggest = tuple(
        operation
        for operation in operations
        if operation.kind is AgentOperationKind.SUGGEST_DISCOVERY
    )
    assert terminal.status == "completed"
    assert [call.params.origin.code for call in gateway.anywhere_calls] == ["LED", "SVO"]
    assert [call.params.max_results for call in gateway.anywhere_calls] == [1, 1]
    assert [operation.immutable_input["origin"] for operation in suggest] == ["LED", "SVO"]
    anywhere_rule = {
        "origin_airports": ["LED", "SVO"],
        "discovery_source_ids": ["aviasales_hot_offers"],
        "max_destination_seeds": 2,
        "exact_verification_limit": 1,
        "catalog_checksum": "sha256:" + "a" * 64,
        "taxonomy_version": "v1",
    }
    terminal_phase, missing_reasons = _snapshot_anywhere_discovery_phase(
        anywhere_rule,
        suggest[:1],
        terminal=True,
    )
    pending_phase, pending_reasons = _snapshot_anywhere_discovery_phase(
        anywhere_rule,
        suggest[:1],
        terminal=False,
    )
    assert terminal_phase.status == "partial"
    assert missing_reasons == {"agent_discovery_binding_not_materialized": 1}
    assert pending_phase.status == "pending"
    assert pending_reasons == {}
    assert len(signals) == 2
    assert len(signals) <= 2
    assert {(signal.origin, signal.destination) for signal in signals} == {
        ("LED", "CDG"),
        ("SVO", "CDG"),
    }
    assert snapshot is not None
    selected_id = UUID(str(snapshot.snapshot["source_signal_ids"][0]))
    selected = next(signal for signal in signals if signal.id == selected_id)
    assert selected.origin == "SVO"
    assert selected.amount_minor == 12_000
    led_record = next(signal for signal in signals if signal.origin == "LED")
    svo_record = next(signal for signal in signals if signal.origin == "SVO")
    stable_led = replace(
        led_record,
        id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        amount_minor=12_000,
        observed_at=NOW,
    )
    stable_svo = replace(
        svo_record,
        id=UUID("00000000-0000-0000-0000-000000000001"),
        observed_at=NOW,
    )
    assert execution_module._stored_discovery_order(  # type: ignore[attr-defined]
        stable_led
    ) < execution_module._stored_discovery_order(stable_svo)  # type: ignore[attr-defined]
    exact_starts = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    assert len(exact_starts) == 1
    assert exact_starts[0].immutable_input["origin"] == "SVO"
    await engine.dispose()


@pytest.mark.anyio
async def test_sequential_anywhere_discovery_keeps_scope_stage_running_with_next_pending(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-next-stage-state.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=2,
        logical_budget=4,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=2,
        anywhere_origin_airports=("LED", "SVO"),
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        repository = AgentOperationRepository(session)
        operations = await repository.list_operations(HOUSEHOLD_ID, RUN_ID)
        stages = await repository.list_stages(HOUSEHOLD_ID, RUN_ID)

    suggest = tuple(
        operation
        for operation in operations
        if operation.kind is AgentOperationKind.SUGGEST_DISCOVERY
    )
    assert step.operation_status == AgentOperationStatus.SUCCEEDED.value
    assert tuple(operation.status for operation in suggest) == (
        AgentOperationStatus.SUCCEEDED,
        AgentOperationStatus.PENDING,
    )
    assert len(stages) == 1
    assert stages[0].status is AgentStageStatus.RUNNING
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_scope_freeze_materialization_keeps_scope_stage_running(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-freeze-stage-state.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=1,
        exact_searches=1,
        logical_budget=2,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=1,
        anywhere_exact_verification_limit=1,
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        repository = AgentOperationRepository(session)
        operations = await repository.list_operations(HOUSEHOLD_ID, RUN_ID)
        stages = await repository.list_stages(HOUSEHOLD_ID, RUN_ID)

    freeze = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.SCOPE_FREEZE
    )
    assert step.operation_status == AgentOperationStatus.SUCCEEDED.value
    assert len(freeze) == 1 and freeze[0].status is AgentOperationStatus.PENDING
    assert len(stages) == 1 and stages[0].status is AgentStageStatus.RUNNING
    await engine.dispose()


@pytest.mark.anyio
async def test_post_snapshot_coverage_stays_partial_when_one_discovery_origin_failed(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-partial-discovery-coverage.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=1,
        logical_budget=3,
        scope_variant="anywhere",
        coverage="full",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=1,
        anywhere_origin_airports=("LED", "SVO"),
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        execution_service = _service(execution_module, session, gateway, clock)
        terminal = await _run_until_terminal(
            execution_service,
            session,
            limit=20,
        )
        await session.rollback()
        view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "partial"
    assert view.coverage_report is not None
    report = view.coverage_report
    assert report.completion == "partial"
    assert (report.planned, report.succeeded, report.failed) == (1, 1, 0)
    assert report.discovery_phase is not None
    assert report.discovery_phase.status == "partial"
    assert report.discovery_phase.terminal_reason == "provider_schema"
    assert report.reason_counts == {"provider_schema": 1}
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_structural_corruption_rejects_the_whole_provider_batch(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-provider-corrupt.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=2,
        logical_budget=4,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=2,
    )
    clock = MutableClock()
    valid = replace(
        _signal(uuid4(), date(2026, 9, 10), 10_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    corrupt = replace(valid, provider_id="foreign_provider", destination="ORY")
    gateway = ResumableFakeGateway(clock, anywhere_results=[(valid, corrupt)])

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        stored = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == AgentOperationStatus.FAILED.value
    assert stored == ()
    assert operations[0].error_code == "provider_schema"
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_existing_evidence_reduces_run_wide_persistence_cap(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-existing-cap.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=2,
        exact_searches=2,
        logical_budget=4,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=2,
        anywhere_exact_verification_limit=2,
    )
    clock = MutableClock()
    existing = replace(
        _signal(uuid4(), date(2026, 9, 10), 9_000),
        destination="ORY",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    cdg = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    nce = replace(
        _signal(uuid4(), date(2026, 9, 10), 5_000),
        destination="NCE",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(cdg, nce)])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        await service._ensure_initial_operation(run, clock.value)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        root = operations[0]
        stored_existing = replace(existing, id=_anywhere_signal_id(root.id, existing))
        await AgentEvidenceRepository(session).append_discovery_signal(
            NewAgentDiscoverySignal(
                id=stored_existing.id,
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                stage_id=root.stage_id,
                provider_id=stored_existing.provider_id,
                origin=stored_existing.origin,
                destination=stored_existing.destination,
                departure_date=stored_existing.departure_date,
                return_date=stored_existing.return_date,
                amount_minor=stored_existing.observed_amount.minor_units,
                currency=stored_existing.observed_amount.currency,
                passengers=stored_existing.passengers,
                passenger_basis=PriceBasis.PROVIDER_SINGLE_ADULT_TICKET,
                source_kind=stored_existing.source_kind,
                freshness=Freshness.API_CACHED,
                observed_at=stored_existing.observed_at,
                signal_evidence={
                    "route_key": "LED-ORY",
                    "source_id": "aviasales_hot_offers",
                    "source_version": "fixture-v1",
                },
                fingerprint=execution_module._evidence_fingerprint(  # type: ignore[attr-defined]
                    stored_existing.id
                ),
                created_at=clock.value,
            )
        )
        await session.commit()

        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        stored = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == AgentOperationStatus.SUCCEEDED.value
    assert gateway.anywhere_calls[0].params.max_results == 1
    assert gateway.anywhere_calls[0].params.allowed_destination_airports == frozenset(
        {"CDG", "NCE", "ORY"}
    )
    assert gateway.anywhere_calls[0].params.excluded_destination_airports == frozenset({"ORY"})
    assert {(signal.destination, signal.amount_minor) for signal in stored} == {
        ("ORY", 9_000),
        ("NCE", 5_000),
    }
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_family_run_uses_single_adult_discovery_and_actual_mix_for_exact(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-family-mix.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=1,
        exact_searches=1,
        logical_budget=2,
        scope_variant="anywhere",
        adults=2,
        children=1,
        infants=0,
        anywhere_max_destination_seeds=1,
        anywhere_exact_verification_limit=1,
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 10_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        execution_service = _service(execution_module, session, gateway, clock)
        terminal = await _run_until_terminal(
            execution_service,
            session,
            limit=12,
        )
        stored = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert len(gateway.anywhere_calls) == 1
    discovery_params = gateway.anywhere_calls[0].params
    assert (
        discovery_params.adults,
        discovery_params.children,
        discovery_params.infants,
    ) == (1, 0, 0)
    assert len(stored) == 1 and stored[0].passengers == 1
    assert len(gateway.start_calls) == 1
    assert gateway.start_calls[0].params.passengers == 3
    await engine.dispose()


@pytest.mark.anyio
async def test_terminal_anywhere_discovery_failure_has_typed_zero_pair_coverage(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-discovery-terminal.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=8,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        await session.rollback()
        view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "failed"
    assert terminal.error_code == "agent_no_discovery_results"
    suggest = tuple(
        operation
        for operation in operations
        if operation.kind is AgentOperationKind.SUGGEST_DISCOVERY
    )
    assert len(suggest) == 1
    assert suggest[0].status is AgentOperationStatus.SKIPPED
    assert suggest[0].attempt_count == 1
    assert suggest[0].error_code == "agent_no_discovery_results"
    assert view.coverage_error_code is None
    assert view.coverage_report is not None
    report = view.coverage_report
    assert report.completion == "failed"
    assert report.frozen_input.origins == ("LED",)
    assert report.frozen_input.destinations == ()
    assert (report.planned, report.attempted, report.succeeded, report.failed, report.skipped) == (
        0,
        0,
        0,
        0,
        0,
    )
    assert report.pairs == ()
    assert report.reason_counts == {"agent_no_discovery_results": 1}
    assert report.discovery_phase is not None
    assert report.discovery_phase.status == "failed"
    assert report.discovery_phase.terminal_reason == "agent_no_discovery_results"
    assert report.discovery_phase.source_ids == ("aviasales_hot_offers",)
    assert report.discovery_phase.max_destination_seeds == 40
    assert report.discovery_phase.exact_verification_limit == 20
    await engine.dispose()


@pytest.mark.anyio
async def test_task10_anywhere_range_coverage_uses_exact_source_signal_pairs(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-range-coverage.db")
    await _seed_run(
        sessions,
        date_mode="range",
        calendar_searches=40,
        exact_searches=20,
        logical_budget=60,
        scope_variant="anywhere",
    )
    clock = MutableClock()
    cdg = replace(
        _signal(uuid4(), date(2026, 9, 10), 20_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    ory = replace(
        _signal(uuid4(), date(2026, 9, 12), 10_000),
        destination="ORY",
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(cdg, ory)])

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=16,
        )
        await session.rollback()
        view = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "completed"
    assert view.coverage_report is not None
    report = view.coverage_report
    assert report.planned == report.attempted == report.succeeded == 2
    assert report.failed == report.skipped == 0
    assert tuple((pair.destination, pair.departure_date, pair.status) for pair in report.pairs) == (
        ("ORY", date(2026, 9, 12), "succeeded"),
        ("CDG", date(2026, 9, 10), "succeeded"),
    )
    await engine.dispose()


@pytest.mark.anyio
async def test_anywhere_coverage_projection_rejects_tampered_snapshot_and_source_record(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "anywhere-projection-integrity.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        calendar_searches=1,
        exact_searches=1,
        logical_budget=2,
        scope_variant="anywhere",
        anywhere_max_destination_seeds=1,
        anywhere_exact_verification_limit=1,
    )
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        execution_service = _service(execution_module, session, gateway, clock)
        terminal = await _run_until_terminal(
            execution_service,
            session,
            limit=16,
        )
        assert terminal.status == "completed"
        await session.rollback()
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        )
        valid = await lifecycle.get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)
        assert valid.coverage_error_code is None
        assert valid.coverage_report is not None

        snapshot_row = (
            (
                await session.execute(
                    select(agent_run_scope_snapshots_table).where(
                        agent_run_scope_snapshots_table.c.run_id == str(RUN_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        original_snapshot = json.loads(str(snapshot_row["snapshot_json"]))
        original_snapshot_fingerprint = str(snapshot_row["fingerprint"])

        narrowed = json.loads(json.dumps(original_snapshot))
        narrowed["origins"] = ["SVO"]
        wrong_catalog = json.loads(json.dumps(original_snapshot))
        wrong_catalog["catalog_checksum"] = "sha256:" + "f" * 64
        over_limit = json.loads(json.dumps(original_snapshot))
        over_limit["destinations"] = ["CDG", "NCE"]
        over_limit["source_signal_ids"] = [
            *original_snapshot["source_signal_ids"],
            "99999999-9999-9999-9999-999999999999",
        ]
        snapshot_tampers = (
            (narrowed, execution_module._scope_snapshot_fingerprint(narrowed)),  # type: ignore[attr-defined]
            (
                wrong_catalog,
                execution_module._scope_snapshot_fingerprint(wrong_catalog),  # type: ignore[attr-defined]
            ),
            (over_limit, execution_module._scope_snapshot_fingerprint(over_limit)),  # type: ignore[attr-defined]
            (original_snapshot, "sha256:" + "0" * 64),
        )
        for payload, fingerprint in snapshot_tampers:
            await session.execute(
                update(agent_run_scope_snapshots_table)
                .where(agent_run_scope_snapshots_table.c.run_id == str(RUN_ID))
                .values(
                    snapshot_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
                    fingerprint=fingerprint,
                )
            )
            await session.commit()
            projected = await lifecycle.get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)
            assert projected.coverage_report is None
            assert projected.coverage_error_code == "agent_coverage_projection_invalid"
            with pytest.raises(execution_module.AgentExecutionError):  # type: ignore[attr-defined]
                await execution_service._workflow(terminal)
            await session.execute(
                update(agent_run_scope_snapshots_table)
                .where(agent_run_scope_snapshots_table.c.run_id == str(RUN_ID))
                .values(
                    snapshot_json=str(snapshot_row["snapshot_json"]),
                    fingerprint=original_snapshot_fingerprint,
                )
            )
            await session.commit()

        await session.execute(
            update(agent_run_scope_snapshots_table)
            .where(agent_run_scope_snapshots_table.c.run_id == str(RUN_ID))
            .values(created_at=terminal.deadline_at + timedelta(seconds=1))
        )
        await session.commit()
        projected = await lifecycle.get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)
        assert projected.coverage_report is None
        assert projected.coverage_error_code == "agent_coverage_projection_invalid"
        with pytest.raises(execution_module.AgentExecutionError):  # type: ignore[attr-defined]
            await execution_service._workflow(terminal)
        await session.execute(
            update(agent_run_scope_snapshots_table)
            .where(agent_run_scope_snapshots_table.c.run_id == str(RUN_ID))
            .values(created_at=snapshot_row["created_at"])
        )
        await session.commit()

        source_row = (
            (
                await session.execute(
                    select(agent_discovery_signals_table).where(
                        agent_discovery_signals_table.c.run_id == str(RUN_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        source_tampers = (
            {"provider_id": "foreign_provider"},
            {"currency": "USD"},
            {"amount_minor": None, "currency": None},
            {"passengers": 2},
            {"fingerprint": "sha256:" + "0" * 64},
            {"observed_at": source_row["created_at"] - timedelta(minutes=10)},
            {
                "signal_evidence_json": json.dumps(
                    {
                        "route_key": "LED-CDG",
                        "source_id": "foreign_source",
                        "source_version": "fixture-v1",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            },
        )
        source_columns = tuple(source_row.keys())
        for values in source_tampers:
            await session.execute(
                update(agent_discovery_signals_table)
                .where(agent_discovery_signals_table.c.id == source_row["id"])
                .values(**values)
            )
            await session.commit()
            projected = await lifecycle.get_run(HOUSEHOLD_ID, PLAN_ID, RUN_ID)
            assert projected.coverage_report is None
            assert projected.coverage_error_code == "agent_coverage_projection_invalid"
            with pytest.raises(execution_module.AgentExecutionError):  # type: ignore[attr-defined]
                await execution_service._workflow(terminal)
            await session.execute(
                update(agent_discovery_signals_table)
                .where(agent_discovery_signals_table.c.id == source_row["id"])
                .values(
                    **{
                        column: source_row[column]
                        for column in source_columns
                        if column not in {"id", "household_id", "run_id", "stage_id"}
                    }
                )
            )
            await session.commit()

        await session.execute(
            delete(agent_run_scope_snapshots_table).where(
                agent_run_scope_snapshots_table.c.run_id == str(RUN_ID)
            )
        )
        await session.execute(
            update(agent_discovery_signals_table)
            .where(agent_discovery_signals_table.c.id == source_row["id"])
            .values(
                signal_evidence_json=json.dumps(
                    {
                        "route_key": "LED-CDG",
                        "source_id": "foreign_source",
                        "source_version": "fixture-v1",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        )
        await session.commit()
        with pytest.raises(execution_module.AgentExecutionError) as freeze_error:  # type: ignore[attr-defined]
            await execution_service._freeze_anywhere_scope(terminal, clock.value)
        assert freeze_error.value.code == "agent_discovery_evidence_invalid"

    await engine.dispose()


@pytest.mark.anyio
async def test_terminal_coverage_marks_started_but_unfinished_pair_incomplete(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "terminal-incomplete-pair.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        exact_searches=1,
        logical_budget=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == AgentOperationStatus.SUCCEEDED.value
    exact_start = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    pair = CoveragePair("LED", "CDG", date(2026, 9, 10), None)
    outcome = _coverage_operation_outcomes((pair,), exact_start, terminal=True)[pair]
    assert outcome.status == "failed"
    assert outcome.reason == "agent_pair_incomplete"
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("requested_strategies", "approved_strategies"),
    ((("direct",), ("through_ticket",)),),
)
async def test_task9_fails_closed_for_mismatched_approved_strategies(
    tmp_path: Path,
    execution_module: ModuleType,
    requested_strategies: tuple[str, ...],
    approved_strategies: tuple[str, ...],
) -> None:
    label = f"{requested_strategies[0]}-{approved_strategies[0]}"
    engine, sessions = await _session_factory(tmp_path, f"unsupported-strategy-{label}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=requested_strategies,
        approved_strategies=approved_strategies,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        circuit_rows = (
            await session.execute(
                select(func.count()).select_from(agent_provider_circuit_state_table)
            )
        ).scalar_one()

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_strategy_unsupported"
    assert terminal.http_attempts_consumed == 0
    assert operations == ()
    assert circuit_rows == reservations == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_hidden_city_uses_distinct_research_operation_and_stays_out_of_ranking_actions(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "hidden-city-isolated.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=("direct", "hidden_city"),
        calendar_searches=4,
        exact_searches=3,
        logical_budget=7,
    )
    clock = MutableClock()
    onward = DiscoverySignal(
        id=uuid4(),
        provider_id="aviasales_search",
        origin="LED",
        destination="FCO",
        departure_date=date(2026, 9, 10),
        return_date=None,
        observed_amount=Money(15_000, "RUB"),
        observed_at=clock(),
        source_kind=DiscoverySource.HOT_OFFER,
        passengers=1,
    )
    gateway = ResumableFakeGateway(
        clock,
        anywhere_results=[(onward,)],
        connecting_evidence=True,
        connection_airport="CDG",
        private_booking_descriptor=True,
    )

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=24,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        descriptors = await AgentEvidenceRepository(session).list_booking_action_descriptors(
            HOUSEHOLD_ID,
            RUN_ID,
            active_at=clock(),
        )
        ranking_operation = next(
            operation for operation in operations if operation.kind is AgentOperationKind.RANKING
        )
        assert ranking_operation.result_id is not None
        ranking = await AgentEvidenceRepository(session).get_ranking_snapshot(
            HOUSEHOLD_ID,
            ranking_operation.result_id,
        )
        await session.rollback()
        results = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
        ).get_run_results(
            HOUSEHOLD_ID,
            PLAN_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert any(
        operation.kind is AgentOperationKind.HIDDEN_CITY_DISCOVERY for operation in operations
    )
    hidden_records = tuple(
        record
        for record in evidence
        if record.itinerary_evidence.get("search_role") == "hidden_city"
    )
    base_records = tuple(
        record
        for record in evidence
        if record.itinerary_evidence.get("search_role", "base") == "base"
    )
    assert len(hidden_records) == len(base_records) == 1
    assert hidden_records[0].itinerary_evidence["hidden_city_desired_airport"] == "CDG"
    assert (
        hidden_records[0].itinerary_evidence["hidden_city_actionability"]
        == "research_only_not_actionable"
    )
    assert ranking is not None
    assert ranking.confirmed_evidence_ids == (base_records[0].id,)
    assert tuple(item.confirmed_evidence_id for item in descriptors) == (base_records[0].id,)
    assert results.state == "ready"
    assert results.report is not None
    assert len(results.hidden_city_candidates) == 1
    assert results.hidden_city_candidates[0].source_evidence.id == hidden_records[0].id
    assert results.hidden_city_candidates[0].booking_action_available is False
    assert results.hidden_city_candidates[0].watch_available is False
    await engine.dispose()


@pytest.mark.anyio
async def test_production_plan_snapshot_executes_hidden_city_research_end_to_end(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "hidden-city-production-chain.db")
    clock = MutableClock()
    onward = DiscoverySignal(
        id=uuid4(),
        provider_id="aviasales_search",
        origin="LED",
        destination="FCO",
        departure_date=date(2026, 9, 10),
        return_date=None,
        observed_amount=Money(15_000, "RUB"),
        observed_at=clock(),
        source_kind=DiscoverySource.HOT_OFFER,
        passengers=1,
    )
    gateway = ResumableFakeGateway(
        clock,
        anywhere_results=[(onward,)],
        connecting_evidence=True,
        connection_airport="CDG",
    )

    async with sessions() as session:
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
            provider_gateway=gateway,
        )
        plan = await lifecycle.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections={
                    "departure_date": "2026-09-10",
                    "requested_strategies": ["direct", "hidden_city"],
                },
                coverage=CoverageMode.QUICK,
            )
        )
        assert plan.estimate is not None
        assert plan.estimate.calendar_searches == 4
        assert plan.estimate.exact_searches == 3
        run_view = await lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                approved_by_session_id=SESSION_ID,
                plan_id=plan.plan_id,
                revision_id=plan.revision_id,
                expected_revision=plan.revision,
                content_hash=plan.content_hash,
                idempotency_key="production-hidden-city",
                hidden_city_warning_version=HIDDEN_CITY_WARNING_VERSION,
            )
        )
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            run_id=run_view.run_id,
            limit=24,
        )
        await session.rollback()
        results = await lifecycle.get_run_results(
            HOUSEHOLD_ID,
            plan.plan_id,
            run_view.run_id,
        )

    assert terminal.status == "completed"
    assert results.state == "ready"
    assert results.report is not None
    assert len(results.hidden_city_candidates) == 1
    hidden = results.hidden_city_candidates[0]
    assert hidden.desired_airport == "CDG"
    assert hidden.ticketed_destination == "FCO"
    assert hidden.booking_action_available is False
    assert hidden.watch_available is False
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ("split_ticket", "self_transfer"))
async def test_split_strategies_are_accepted_and_begin_with_confirmed_exact_search(
    tmp_path: Path,
    execution_module: ModuleType,
    strategy: Literal["split_ticket", "self_transfer"],
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"supported-{strategy}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=(strategy,),
        exact_searches=5,
        logical_budget=5,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)

    assert step.operation_claimed is True
    assert run is not None and run.status == "running" and run.error_code is None
    assert len(gateway.start_calls) == 1
    assert any(operation.kind is AgentOperationKind.EXACT_START for operation in operations)
    await engine.dispose()


@pytest.mark.anyio
async def test_split_searches_are_derived_only_from_confirmed_hubs_within_approved_reserve(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "confirmed-split-hub.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=("split_ticket",),
        exact_searches=5,
        logical_budget=5,
        poll_rounds=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)
        confirmed = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    (source_evidence,) = confirmed
    exact_starts = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    assert {
        (
            operation.immutable_input["origin"],
            operation.immutable_input["destination"],
        )
        for operation in exact_starts
    } == {("LED", "CDG"), ("LED", "AMS"), ("AMS", "CDG")}
    split_starts = tuple(
        operation
        for operation in exact_starts
        if operation.immutable_input.get("search_role") == "split_component"
    )
    assert len(split_starts) == 2
    assert {
        operation.immutable_input["split_source_evidence_id"] for operation in split_starts
    } == {str(source_evidence.id)}
    assert len(exact_starts) <= 5
    await engine.dispose()


@pytest.mark.anyio
async def test_split_flow_persists_composed_candidate_and_all_typed_ranking_views(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "split-composition-ranking.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=("split_ticket",),
        exact_searches=5,
        logical_budget=5,
        poll_rounds=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=20,
        )
        evidence_repository = AgentEvidenceRepository(session)
        composed = await evidence_repository.list_composed_candidates(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        ranking_operation = next(
            operation for operation in operations if operation.kind is AgentOperationKind.RANKING
        )
        assert ranking_operation.result_id is not None
        ranking_record = await evidence_repository.get_ranking_snapshot(
            HOUSEHOLD_ID,
            ranking_operation.result_id,
        )

    assert terminal.status == "completed"
    assert len(composed) == 1
    assert composed[0].component_evidence_ids
    assert composed[0].protection_status is ProtectionStatus.SELF_TRANSFER
    assert ranking_record is not None
    ranking = ranking_snapshot_from_payload(ranking_record.ranking)
    assert tuple(view.name for view in ranking.views) == tuple(RankingView)
    split_view = ranking.view(RankingView.SPLIT_SELF_TRANSFER)
    assert len(split_view.candidates) == 1
    assert split_view.candidates[0].reference.kind is CandidateKind.COMPOSED_ROUTE
    assert split_view.candidates[0].reference.id == composed[0].id
    assert set(ranking.composed_candidate_ids) == {composed[0].id}
    await engine.dispose()


@pytest.mark.anyio
async def test_round_trip_split_preserves_two_directions_and_never_searches_same_airport(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "round-trip-split.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        trip_shape="round_trip",
        requested_strategies=("split_ticket", "self_transfer"),
        exact_searches=9,
        logical_budget=9,
        poll_rounds=1,
        analysis_modes=("buy_timing", "error_fare"),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=40,
        )
        evidence_repository = AgentEvidenceRepository(session)
        composed = await evidence_repository.list_composed_candidates(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        analysis_record = await evidence_repository.get_analysis_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    split_starts = tuple(
        operation
        for operation in operations
        if operation.kind is AgentOperationKind.EXACT_START
        and operation.immutable_input.get("search_role") == "split_component"
    )
    assert terminal.status == "completed"
    assert {
        (
            operation.immutable_input["leg_ordinal"],
            operation.immutable_input["origin"],
            operation.immutable_input["destination"],
            operation.immutable_input["departure_date"],
        )
        for operation in split_starts
    } == {
        (0, "LED", "AMS", "2026-09-10"),
        (0, "AMS", "CDG", "2026-09-10"),
        (1, "CDG", "AMS", "2026-09-20"),
        (1, "AMS", "LED", "2026-09-20"),
    }
    assert all(
        operation.immutable_input["origin"] != operation.immutable_input["destination"]
        for operation in split_starts
    )
    assert len(composed) == 1
    facts = composed[0].itinerary_evidence
    assert facts["trip_shape"] == "round_trip"
    assert [
        (leg["ordinal"], leg["origin"], leg["destination"], leg["departure_date"])
        for leg in facts["ordered_legs"]
    ] == [
        (0, "LED", "CDG", "2026-09-10"),
        (1, "CDG", "LED", "2026-09-20"),
    ]
    assert analysis_record is not None
    assert analysis_record.analysis["scope_status"] == "unsupported_trip_structure"
    assert "buy_timing" not in analysis_record.analysis
    assert "anomaly" not in analysis_record.analysis
    await engine.dispose()


@pytest.mark.anyio
async def test_approved_analysis_modes_persist_evidence_gated_snapshot_without_extra_io(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "fare-analysis.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        analysis_modes=("buy_timing", "error_fare", "currency_compare"),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        analysis_operation = next(
            operation for operation in operations if operation.kind is AgentOperationKind.ANALYSIS
        )
        assert analysis_operation.result_id is not None
        snapshot = await AgentEvidenceRepository(session).get_analysis_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        circuit_rows = (
            await session.execute(
                select(func.count()).select_from(agent_provider_circuit_state_table)
            )
        ).scalar_one()
        await session.rollback()
        results = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run_results(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert terminal.status == "completed"
    assert len(evidence) == 1
    assert evidence[0].history_series_hash is not None
    assert analysis_operation.result_type is AgentOperationResultType.ANALYSIS_SNAPSHOT
    assert snapshot is not None
    assert snapshot.id == analysis_operation.result_id
    assert snapshot.source_evidence_ids == (evidence[0].id,)
    assert snapshot.analysis["version"] == "fare-analysis-snapshot-v1"
    assert snapshot.analysis["aggregation_mode"] == "market_minimum"
    assert snapshot.analysis["scope_status"] == "supported"
    assert snapshot.analysis["provider_id"] == "aviasales_search"
    assert snapshot.analysis["freshness"] == "live"
    assert snapshot.analysis["passengers"] == 1
    assert snapshot.analysis["passenger_basis"] == "total_for_passengers"
    assert snapshot.analysis["primary_amount"] == {
        "minor_units": 20_000,
        "currency": "RUB",
    }
    assert snapshot.analysis["origin"] == "LED"
    assert snapshot.analysis["destination"] == "CDG"
    assert snapshot.analysis["departure_date"] == "2026-09-10"
    assert snapshot.analysis["return_date"] is None
    assert snapshot.analysis["history_observation_count"] == 0
    history_fingerprint = snapshot.analysis["history_evidence_fingerprint"]
    assert isinstance(history_fingerprint, str)
    assert history_fingerprint.startswith("sha256:")
    assert snapshot.analysis["source_evidence_truncated"] is False
    assert snapshot.analysis["requested_modes"] == (
        "buy_timing",
        "error_fare",
        "currency_compare",
    )
    buy_timing = snapshot.analysis["buy_timing"]
    anomaly = snapshot.analysis["anomaly"]
    currency = snapshot.analysis["currency_comparison"]
    assert isinstance(buy_timing, Mapping)
    assert isinstance(anomaly, Mapping)
    assert isinstance(currency, Mapping)
    assert buy_timing["status"] == "insufficient_data"
    assert buy_timing["watch_action_available"] is True
    assert snapshot.analysis["watch_action"] == {
        "available": True,
        "origin": "LED",
        "destination": "CDG",
        "departure_date": "2026-09-10",
        "return_date": None,
        "passengers": 1,
        "currency": "RUB",
    }
    assert anomaly["status"] == "insufficient_data"
    assert currency["status"] == "fx_provider_unavailable"
    assert currency["savings_minor_units"] is None
    assert currency["savings_percent"] is None
    assert results.state == "ready"
    assert results.analysis == snapshot.analysis
    assert circuit_rows == 1
    assert reservations == gateway.provider_calls == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_active_task9_analysis_operation_recovers_after_upgrade(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "legacy-analysis-recovery.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        analysis_operation = None
        for _ in range(12):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            analysis_operation = next(
                (
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.ANALYSIS
                ),
                None,
            )
            if (
                analysis_operation is not None
                and analysis_operation.status is AgentOperationStatus.PENDING
            ):
                break
        assert analysis_operation is not None
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(analysis_operation.id))
            .values(
                immutable_input_json=json.dumps(
                    {"analysis_mode": "minimal_report", "version": "task9-v1"},
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        )
        await session.commit()

        terminal = await _run_until_terminal(service, session, limit=4)
        snapshot = await AgentEvidenceRepository(session).get_analysis_snapshot_for_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "completed"
    assert snapshot is not None
    assert snapshot.analysis["requested_modes"] == ()
    assert snapshot.analysis["scope_status"] == "supported"
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("immutable_input", "expected_state"),
    (
        ({"analysis_mode": "minimal_report", "version": "task9-v1"}, "ready"),
        ({"analysis_modes": [], "version": "fare-analysis-v1"}, "unavailable"),
    ),
)
async def test_only_legacy_task9_ranking_link_is_accepted_as_completed_analysis(
    tmp_path: Path,
    execution_module: ModuleType,
    immutable_input: dict[str, object],
    expected_state: Literal["ready", "unavailable"],
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"legacy-analysis-result-{expected_state}.db",
    )
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        assert terminal.status == "completed"
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        ranking = next(
            operation for operation in operations if operation.kind is AgentOperationKind.RANKING
        )
        analysis = next(
            operation for operation in operations if operation.kind is AgentOperationKind.ANALYSIS
        )
        assert ranking.result_id is not None
        await session.execute(
            delete(agent_analysis_snapshots_table).where(
                agent_analysis_snapshots_table.c.run_id == str(RUN_ID)
            )
        )
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(analysis.id))
            .values(
                immutable_input_json=json.dumps(
                    immutable_input,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                result_type=AgentOperationResultType.RANKING_SNAPSHOT.value,
                result_id=str(ranking.result_id),
            )
        )
        await session.commit()

        results = await AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(clock=clock),
            clock=clock,
        ).get_run_results(HOUSEHOLD_ID, PLAN_ID, RUN_ID)

    assert results.state == expected_state
    assert results.analysis is None
    assert (results.error_code is None) == (expected_state == "ready")
    await engine.dispose()


@pytest.mark.anyio
async def test_existing_analysis_snapshot_is_validated_before_retry_reuse(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "analysis-retry-binding.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        analysis_modes=("buy_timing",),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        analysis_operation = None
        for _ in range(12):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
            operations = await AgentOperationRepository(session).list_operations(
                HOUSEHOLD_ID,
                RUN_ID,
            )
            analysis_operation = next(
                (
                    operation
                    for operation in operations
                    if operation.kind is AgentOperationKind.ANALYSIS
                ),
                None,
            )
            if (
                analysis_operation is not None
                and analysis_operation.status is AgentOperationStatus.PENDING
            ):
                break
        assert analysis_operation is not None
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        await AgentEvidenceRepository(session).create_analysis_snapshot(
            NewAgentAnalysisSnapshot(
                id=uuid4(),
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                source_evidence_ids=(evidence[0].id,),
                analysis={
                    "version": "fare-analysis-snapshot-v1",
                    "source": "confirmed_exact_history",
                    "aggregation_mode": "market_minimum",
                    "scope_status": "supported",
                    "requested_modes": [],
                },
                created_at=clock(),
            )
        )
        await session.commit()

        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        stored_analysis = next(
            operation for operation in operations if operation.kind is AgentOperationKind.ANALYSIS
        )

    assert step.operation_status == "failed"
    assert stored_analysis.error_code == "agent_analysis_snapshot_conflict"
    await engine.dispose()


def test_analysis_history_validation_keeps_all_market_observations(
    execution_module: ModuleType,
) -> None:
    records = tuple(
        AgentConfirmedOfferEvidenceRecord(
            id=UUID(int=index + 1),
            household_id=HOUSEHOLD_ID,
            run_id=UUID(int=10_000 + index),
            stage_id=UUID(int=20_000 + index),
            provider_id="aviasales_search",
            source="exact_search",
            observed_at=NOW - timedelta(days=120 - index),
            freshness=Freshness.LIVE,
            passengers=1,
            passenger_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
            amount_minor=20_000 + index,
            currency="RUB",
            itinerary_evidence={"departure_date": "2026-09-10"},
            protection_status=ProtectionStatus.UNKNOWN,
            baggage_status=None,
            transfer_status=None,
            visa_status=None,
            history_series_hash="sha256:" + "a" * 64,
            fingerprint="sha256:" + f"{index:064x}",
            created_at=NOW - timedelta(days=120 - index),
        )
        for index in range(120)
    )

    duplicate_offer = replace(
        records[50],
        id=UUID(int=50_000),
        amount_minor=10_000,
        fingerprint="sha256:" + "f" * 64,
    )
    valid_records, observations = execution_module._valid_analysis_history_records(
        (*records, duplicate_offer)
    )

    assert len(valid_records) == 120
    assert len(observations) == 120
    assert valid_records[0].id == UUID(int=1)
    assert valid_records[-1].id == UUID(int=120)
    selected_run_offer = next(
        record for record in valid_records if record.run_id == duplicate_offer.run_id
    )
    assert selected_run_offer.id == duplicate_offer.id
    bounded = execution_module._bounded_analysis_source_records(valid_records, limit=99)
    assert len(bounded) == 99
    assert bounded[0].id == valid_records[0].id
    assert bounded[-1].id == valid_records[-1].id
    assert execution_module._history_evidence_fingerprint(
        valid_records
    ) != execution_module._history_evidence_fingerprint(bounded)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "column_name",
    (
        "approved_budget_json",
        "approved_strategies_json",
        "risk_warning_versions_json",
    ),
)
async def test_corrupt_approval_json_fails_typed_before_operation_or_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
    column_name: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"approval-json-{column_name}.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        await session.execute(
            update(agent_plan_execution_approvals_table)
            .where(agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID))
            .values({column_name: "{PRIVATE-INVALID-JSON"})
        )
        await session.commit()
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(HOUSEHOLD_ID, RUN_ID)

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_plan_snapshot_invalid"
    assert operations == () and terminal.http_attempts_consumed == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tamper", "value"),
    (
        ("budget", {"logical_operations": 999}),
        ("binding", None),
        ("approved_at", NOW - timedelta(seconds=1)),
    ),
)
async def test_approval_budget_identity_and_timestamps_are_bound_before_io(
    tmp_path: Path,
    execution_module: ModuleType,
    tamper: str,
    value: object,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"approval-binding-{tamper}.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        statement = update(agent_plan_execution_approvals_table).where(
            agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID)
        )
        if tamper == "budget":
            statement = statement.values(approved_budget_json=json.dumps(value))
        elif tamper == "binding":
            statement = statement.values(run_id=None, consumed_at=None)
        else:
            statement = statement.values(approved_at=value)
        await session.execute(statement)
        await session.commit()
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_plan_snapshot_invalid"
    assert terminal.http_attempts_consumed == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_revision_payload_hash_is_recomputed_before_approved_execution(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "revision-hash-tamper.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        row = (
            (
                await session.execute(
                    select(agent_search_plan_revisions_table).where(
                        agent_search_plan_revisions_table.c.id == str(REVISION_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        tampered_plan = json.loads(row["plan_json"])
        tampered_plan["intent"]["currency"] = "EUR"
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == str(REVISION_ID))
            .values(plan_json=json.dumps(tampered_plan, sort_keys=True, separators=(",", ":")))
        )
        await session.commit()
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_plan_snapshot_invalid"
    assert terminal.http_attempts_consumed == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "tamper",
    (
        "coverage",
        "date_mode",
        "capability",
        "cost_formula",
        "exact_zero",
        "exact_count",
        "calendar_count",
    ),
)
async def test_coordinated_revision_and_approval_hash_tamper_still_fails_semantics(
    tmp_path: Path,
    execution_module: ModuleType,
    tamper: str,
) -> None:
    date_mode: Literal["exact", "flexible"] = "exact" if tamper == "exact_count" else "flexible"
    calendar_searches = 0 if date_mode == "exact" else 5
    exact_searches = 1 if date_mode == "exact" else 5
    engine, sessions = await _session_factory(tmp_path, f"coordinated-{tamper}.db")
    await _seed_run(
        sessions,
        date_mode=date_mode,
        calendar_searches=calendar_searches,
        exact_searches=exact_searches,
        logical_budget=calendar_searches + exact_searches,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        row = (
            (
                await session.execute(
                    select(agent_search_plan_revisions_table).where(
                        agent_search_plan_revisions_table.c.id == str(REVISION_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        plan = json.loads(row["plan_json"])
        capability = json.loads(row["capability_snapshot_json"])
        cost = json.loads(row["cost_model_snapshot_json"])
        revision_values: dict[str, object] = {}
        if tamper == "coverage":
            plan["coverage"] = "full"
            revision_values["plan_json"] = json.dumps(
                plan,
                sort_keys=True,
                separators=(",", ":"),
            )
        elif tamper == "date_mode":
            plan["intent"]["date_mode"] = "range"
            revision_values["plan_json"] = json.dumps(
                plan,
                sort_keys=True,
                separators=(",", ":"),
            )
        elif tamper == "capability":
            capability["provider_id"] = "other_provider"
            revision_values["capability_snapshot_json"] = json.dumps(
                capability,
                sort_keys=True,
                separators=(",", ":"),
            )
        elif tamper == "cost_formula":
            cost["worst_case_exact_http_attempts"] += 1
            revision_values["cost_model_snapshot_json"] = json.dumps(
                cost,
                sort_keys=True,
                separators=(",", ":"),
            )
        else:
            if tamper == "exact_zero":
                calendar_searches, exact_searches = 5, 0
            elif tamper == "exact_count":
                calendar_searches, exact_searches = 0, 2
            else:
                calendar_searches, exact_searches = 2, 5
            logical_operations = calendar_searches + exact_searches
            http_attempts = (
                calendar_searches * cost["start_attempts"]
                + exact_searches * cost["worst_case_exact_http_attempts"]
            )
            revision_values.update(
                estimated_calendar_searches=calendar_searches,
                estimated_exact_searches=exact_searches,
                estimated_logical_operations=logical_operations,
                estimated_http_attempts=http_attempts,
            )
            approved_budget = {
                "calendar_searches": calendar_searches,
                "exact_searches": exact_searches,
                "logical_operations": logical_operations,
                "http_attempts": http_attempts,
                "deadline_seconds": row["estimated_deadline_seconds"],
            }
            await session.execute(
                update(agent_plan_execution_approvals_table)
                .where(agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID))
                .values(
                    approved_budget_json=json.dumps(
                        approved_budget,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            )
            await session.execute(
                update(agent_plan_runs_table)
                .where(agent_plan_runs_table.c.id == str(RUN_ID))
                .values(
                    logical_operation_budget=logical_operations,
                    http_attempt_budget=http_attempts,
                )
            )
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == str(REVISION_ID))
            .values(**revision_values)
        )
        revision = await AgentPlanRepository(session).get_revision(
            HOUSEHOLD_ID,
            REVISION_ID,
        )
        assert revision is not None
        coordinated_hash = recompute_agent_plan_revision_content_hash(revision)
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == str(REVISION_ID))
            .values(content_hash=coordinated_hash)
        )
        await session.execute(
            update(agent_plan_execution_approvals_table)
            .where(agent_plan_execution_approvals_table.c.id == str(APPROVAL_ID))
            .values(revision_content_hash=coordinated_hash)
        )
        await session.commit()

        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_claimed is False and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_plan_snapshot_invalid"
    assert operations == ()
    assert terminal.http_attempts_consumed == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("strategy", ("direct", "through_ticket"))
async def test_task9_keeps_singleton_normal_strategy_execution(
    tmp_path: Path,
    execution_module: ModuleType,
    strategy: Literal["direct", "through_ticket"],
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"supported-strategy-{strategy}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        requested_strategies=(strategy,),
        approved_strategies=(strategy,),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()

    assert step.operation_status == "succeeded"
    assert gateway.provider_calls == 1
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("date_mode", ("exact", "flexible"))
async def test_empty_requested_strategies_execute_as_default_through_ticket_semantics(
    tmp_path: Path,
    execution_module: ModuleType,
    date_mode: Literal["exact", "flexible"],
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"default-through-ticket-{date_mode}.db",
    )
    flexible = date_mode == "flexible"
    await _seed_run(
        sessions,
        date_mode=date_mode,
        calendar_searches=5 if flexible else 0,
        exact_searches=5 if flexible else 1,
        logical_budget=10 if flexible else 1,
        requested_strategies=(),
        approved_strategies=(),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)
    if flexible:
        gateway.calendar_results.append(_complete_flexible_signals())

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=24,
        )
        evidence_items = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        approval = await AgentRunRepository(session).get_approval(
            HOUSEHOLD_ID,
            APPROVAL_ID,
        )

    assert terminal.status == "completed"
    assert approval is not None and approval.snapshot.approved_strategies == ()
    expected_evidence = 5 if flexible else 1
    assert len(evidence_items) == expected_evidence
    assert all(evidence.itinerary_evidence["stops"] == 1 for evidence in evidence_items)
    assert len(gateway.poll_calls) == expected_evidence
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("date_mode", ("exact", "flexible"))
async def test_parser_planner_lifecycle_to_executor_keeps_empty_default_strategy(
    tmp_path: Path,
    execution_module: ModuleType,
    date_mode: Literal["exact", "flexible"],
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"production-default-strategy-{date_mode}.db",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)
    if date_mode == "flexible":
        gateway.calendar_results.append(_complete_flexible_signals())
    selections: dict[str, object] = {
        "departure_date": "2026-09-10",
        "requested_strategies": [],
    }
    if date_mode == "flexible":
        selections.update(date_mode="flexible", flex_days=2)

    async with sessions() as session:
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
            provider_gateway=gateway,
        )
        plan = await lifecycle.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections=selections,
                coverage=CoverageMode.QUICK,
            )
        )
        run_view = await lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                approved_by_session_id=SESSION_ID,
                plan_id=plan.plan_id,
                revision_id=plan.revision_id,
                expected_revision=plan.revision,
                content_hash=plan.content_hash,
                idempotency_key=f"production-default-{date_mode}",
            )
        )
        executor = _service(execution_module, session, gateway, clock)
        terminal = None
        for _ in range(24):
            await executor.run_step(
                household_id=HOUSEHOLD_ID,
                run_id=run_view.run_id,
            )
            await session.commit()
            terminal = await AgentRunRepository(session).get_run(
                HOUSEHOLD_ID,
                run_view.run_id,
            )
            assert terminal is not None
            if terminal.status in {"completed", "partial", "failed", "cancelled"}:
                break
        approval = await AgentRunRepository(session).get_approval(
            HOUSEHOLD_ID,
            terminal.approval_id,
        )
        evidence_items = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            run_view.run_id,
        )

    assert terminal.status == "completed", (terminal.error_code, plan.estimate)
    assert approval is not None and approval.snapshot.approved_strategies == ()
    expected_evidence = 5 if date_mode == "flexible" else 1
    assert len(evidence_items) == expected_evidence
    assert all(evidence.itinerary_evidence["stops"] == 1 for evidence in evidence_items)
    await engine.dispose()


@pytest.mark.anyio
async def test_approved_scope_is_immutable_after_airport_catalog_mutation(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "approved-catalog-mutation.db")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    catalog = _MutableApprovalAirportCatalog(
        airports=(
            Airport(
                iata_code="LED",
                name="Pulkovo",
                municipality="Saint Petersburg",
                country_code="RU",
                latitude=59.8003,
                longitude=30.2625,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="task10.mutable_catalog",
            ),
            Airport(
                iata_code="CDG",
                name="Charles de Gaulle",
                municipality="Paris",
                country_code="FR",
                latitude=49.0097,
                longitude=2.5479,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="task10.mutable_catalog",
            ),
            Airport(
                iata_code="ORY",
                name="Orly",
                municipality="Paris",
                country_code="FR",
                latitude=48.7262,
                longitude=2.3652,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="task10.mutable_catalog",
            ),
        )
    )

    async with sessions() as session:
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=catalog),
            ),
            clock=clock,
            provider_gateway=gateway,
        )
        plan = await lifecycle.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → France",
                selections={"departure_date": "2026-09-10", "requested_strategies": []},
                coverage=CoverageMode.FULL,
            )
        )
        assert plan.estimate is not None and plan.estimate.exact_searches == 2
        run_view = await lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                approved_by_session_id=SESSION_ID,
                plan_id=plan.plan_id,
                revision_id=plan.revision_id,
                expected_revision=plan.revision,
                content_hash=plan.content_hash,
                idempotency_key="approved-catalog-mutation",
            )
        )
        reads_at_approval = catalog.reads
        catalog.airports += (
            Airport(
                iata_code="BVA",
                name="Beauvais",
                municipality="Beauvais",
                country_code="FR",
                latitude=49.4544,
                longitude=2.1128,
                airport_type=AirportType.LARGE_AIRPORT,
                active=True,
                scheduled_service=True,
                commercial_provenance="task10.mutable_catalog.v2",
            ),
        )
        catalog.forbid_reads = True

        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            run_id=run_view.run_id,
            limit=16,
        )

    assert terminal.status == "completed"
    assert catalog.reads == reads_at_approval
    assert {call.params.destination.code for call in gateway.start_calls} == {"CDG", "ORY"}
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("date_mode", "expected_calendar", "expected_exact"),
    (
        ("exact", 0, 1),
        ("flexible", 5, 5),
    ),
)
async def test_parser_planner_lifecycle_executes_native_round_trip_surface(
    tmp_path: Path,
    execution_module: ModuleType,
    date_mode: Literal["exact", "flexible"],
    expected_calendar: int,
    expected_exact: int,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"production-round-trip-{date_mode}.db",
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    if date_mode == "flexible":
        gateway.calendar_results.append(_complete_flexible_signals(return_date=date(2026, 9, 12)))
    selections: dict[str, object] = {
        "departure_date": "2026-09-10",
        "return_date": "2026-09-12",
        "requested_strategies": [],
    }
    if date_mode == "flexible":
        selections.update(date_mode="flexible", flex_days=2)

    async with sessions() as session:
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
            provider_gateway=gateway,
        )
        plan = await lifecycle.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → CDG",
                selections=selections,
                coverage=CoverageMode.QUICK,
            )
        )
        assert plan.estimate is not None
        assert plan.estimate.calendar_searches == expected_calendar
        assert plan.estimate.exact_searches == expected_exact
        run_view = await lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                approved_by_session_id=SESSION_ID,
                plan_id=plan.plan_id,
                revision_id=plan.revision_id,
                expected_revision=plan.revision,
                content_hash=plan.content_hash,
                idempotency_key=f"production-round-trip-{date_mode}",
            )
        )
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            run_id=run_view.run_id,
            limit=24,
        )
        evidence_items = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            run_view.run_id,
        )

    assert terminal.status == "completed", (terminal.error_code, plan.estimate)
    assert len(evidence_items) == expected_exact
    assert all(len(evidence.itinerary_evidence["segments"]) == 2 for evidence in evidence_items)
    assert all(evidence.itinerary_evidence["stops"] == 0 for evidence in evidence_items)
    assert len(gateway.calendar_calls) == expected_calendar
    assert len(gateway.start_calls) == expected_exact
    assert {call.params.return_date for call in gateway.start_calls} == {"2026-09-12"}
    await engine.dispose()


@pytest.mark.anyio
async def test_parser_planner_lifecycle_executes_round_trip_anywhere_from_one_way_seed(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "production-round-trip-anywhere.db")
    clock = MutableClock()
    signal = replace(
        _signal(uuid4(), date(2026, 9, 10), 18_000),
        source_kind=DiscoverySource.HOT_OFFER,
    )
    gateway = ResumableFakeGateway(clock, anywhere_results=[(signal,)])

    async with sessions() as session:
        lifecycle = AgentLifecycleService(
            session=session,
            parser=IntentParser(),
            builder=AgentPlanBuilder(
                clock=clock,
                scope_resolver=ScopeResolver(repository=_ProductionShapeAirportCatalog()),
            ),
            clock=clock,
            provider_gateway=gateway,
        )
        plan = await lifecycle.create_plan(
            CreateAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                text="LED → anywhere",
                selections={
                    "departure_date": "2026-09-10",
                    "return_date": "2026-09-12",
                    "requested_strategies": [],
                },
                coverage=CoverageMode.QUICK,
            )
        )
        assert plan.state == "awaiting_approval", plan.clarifications
        assert plan.estimate is not None
        assert (plan.estimate.calendar_searches, plan.estimate.exact_searches) == (40, 20)
        assert plan.summary.scope[1].frozen is True
        assert plan.summary.scope[1].reciprocal_anywhere_return is True
        assert plan.summary.scope[1].origin_airports == ()
        run_view = await lifecycle.execute_plan(
            ExecuteAgentPlan(
                household_id=HOUSEHOLD_ID,
                user_id=USER_ID,
                approved_by_session_id=SESSION_ID,
                plan_id=plan.plan_id,
                revision_id=plan.revision_id,
                expected_revision=plan.revision,
                content_hash=plan.content_hash,
                idempotency_key="production-round-trip-anywhere",
            )
        )
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            run_id=run_view.run_id,
            limit=20,
        )
        snapshot = await AgentOperationRepository(session).get_scope_snapshot_for_run(
            HOUSEHOLD_ID,
            run_view.run_id,
        )
        await session.rollback()
        projected = await lifecycle.get_run(HOUSEHOLD_ID, plan.plan_id, run_view.run_id)

    assert terminal.status == "completed", terminal.error_code
    assert len(gateway.anywhere_calls) == 1
    assert gateway.anywhere_calls[0].params.one_way is True
    assert snapshot is not None
    assert snapshot.snapshot["destinations"] == ("CDG",)
    assert len(gateway.start_calls) == 1
    assert gateway.start_calls[0].params.return_date == "2026-09-12"
    assert projected.coverage_report is not None
    assert projected.coverage_report.pairs[0].return_date == date(2026, 9, 12)
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("strategy", "expected_evidence", "expected_status"),
    (
        ("direct", 0, "failed"),
        ("through_ticket", 1, "running"),
    ),
)
async def test_direct_strategy_rejects_connections_while_through_ticket_keeps_them(
    tmp_path: Path,
    execution_module: ModuleType,
    strategy: Literal["direct", "through_ticket"],
    expected_evidence: int,
    expected_status: Literal["failed", "running"],
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"strategy-topology-{strategy}.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        poll_rounds=1,
        requested_strategies=(strategy,),
        approved_strategies=(strategy,),
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, connecting_evidence=True)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        second = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert run is not None and run.status == expected_status
    assert len(evidence) == expected_evidence
    assert second.operation_status == ("failed" if strategy == "direct" else "succeeded")
    await engine.dispose()


@pytest.mark.anyio
async def test_direct_round_trip_persists_zero_stops_across_two_directions(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "round-trip-stops.db")
    await _seed_run(sessions, date_mode="exact", trip_shape="round_trip")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        for _ in range(2):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
        (stored,) = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert len(stored.itinerary_evidence["segments"]) == 2
    assert stored.itinerary_evidence["stops"] == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_flexible_round_trip_shortlist_ignores_cheaper_unapproved_return_date(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "round-trip-shortlist-binding.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        trip_shape="round_trip",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    gateway.calendar_results.append(
        (
            _signal(
                uuid4(),
                date(2026, 9, 10),
                5_000,
                return_date=date(2026, 9, 18),
            ),
            _signal(
                uuid4(),
                date(2026, 9, 10),
                10_000,
                return_date=date(2026, 9, 20),
            ),
        )
    )

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        for _ in range(6):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    starts = tuple(
        operation for operation in operations if operation.kind is AgentOperationKind.EXACT_START
    )
    assert len(starts) == 1
    assert starts[0].immutable_input["return_date"] == "2026-09-20"
    assert len(gateway.start_calls) == 1
    assert gateway.start_calls[0].params.return_date == "2026-09-20"
    await engine.dispose()


@pytest.mark.anyio
async def test_flexible_round_trip_snapshot_rejects_return_inside_outbound_surface(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "round-trip-invalid-chronology.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        trip_shape="round_trip",
        round_trip_return_date="2026-09-11",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_claimed is False
    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_plan_snapshot_invalid"
    assert operations == ()
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_restart_resumes_saved_exact_cursor_and_start_handoff_is_atomic(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "cursor-restart.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, poll_behaviors=[17, "evidence"])

    async with sessions() as session:
        first_process = _service(execution_module, session, gateway, clock)
        await first_process.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        after_start = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        start, first_poll = after_start
        assert start.result_type is AgentOperationResultType.OPERATION
        assert start.result_id == first_poll.id
        assert first_poll.handoff_predecessor_operation_id == start.id

        await first_process.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()

    async with sessions() as restarted_session:
        restarted = _service(execution_module, restarted_session, gateway, clock)
        await restarted.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await restarted_session.commit()
        await _run_until_terminal(restarted, restarted_session)

    assert [continuation.last_update_timestamp for continuation in gateway.poll_calls] == [0, 17]
    assert {continuation.search_id for continuation in gateway.poll_calls} == {"search-1"}
    assert {continuation.results_url for continuation in gateway.poll_calls} == {
        "results.aviasales.ru"
    }
    assert {continuation.request_id for continuation in gateway.poll_calls} == {"request-1"}
    await engine.dispose()


@pytest.mark.anyio
async def test_exact_poll_cadence_defers_without_sleep_and_deadline_preempts_due_poll(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "poll-cadence.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            poll_interval_seconds=2,
        )
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        calls_after_start = gateway.provider_calls

        idle = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        clock.value = NOW + timedelta(seconds=2)
        resumed = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()

    assert poll.status is AgentOperationStatus.RETRY_WAIT
    assert poll.attempt_count == 0
    assert poll.next_retry_at == NOW + timedelta(seconds=2)
    assert idle.operation_claimed is False
    assert calls_after_start == 1
    assert resumed.operation_status == "succeeded"
    assert len(gateway.poll_calls) == 1
    await engine.dispose()

    deadline_engine, deadline_sessions = await _session_factory(tmp_path, "poll-deadline.db")
    await _seed_run(deadline_sessions, date_mode="exact", deadline_seconds=1)
    deadline_clock = MutableClock()
    deadline_gateway = ResumableFakeGateway(deadline_clock)
    async with deadline_sessions() as session:
        service = _service(
            execution_module,
            session,
            deadline_gateway,
            deadline_clock,
            poll_interval_seconds=2,
        )
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        deadline_clock.value = NOW + timedelta(seconds=1)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_run_deadline_exceeded"
    assert len(deadline_gateway.poll_calls) == 0
    await deadline_engine.dispose()


@pytest.mark.anyio
async def test_http_reservation_is_durable_before_uncaught_process_crash(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "reservation-crash.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        start_attempts=2,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[SimulatedProcessCrash(), None],
    )

    async with sessions() as session:
        crashing = _service(
            execution_module,
            session,
            gateway,
            clock,
            durability_checkpoint=session.commit,
        )
        with pytest.raises(SimulatedProcessCrash):
            await crashing.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)

    async with sessions() as recovered_session:
        durable_run = await AgentRunRepository(recovered_session).get_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        (durable_operation,) = await AgentOperationRepository(recovered_session).list_operations(
            HOUSEHOLD_ID, RUN_ID
        )
        assert durable_run is not None
        assert durable_run.http_attempts_consumed == 1
        assert durable_operation.status is AgentOperationStatus.LEASED
        assert durable_operation.attempt_count == 1
        assert durable_operation.lease_expires_at is not None

        clock.value = durable_operation.lease_expires_at
        recovered = _service(
            execution_module,
            recovered_session,
            gateway,
            clock,
            durability_checkpoint=recovered_session.commit,
        )
        recovery_step = await recovered.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await recovered_session.commit()
        after_retry = await AgentRunRepository(recovered_session).get_run(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert after_retry is not None and after_retry.http_attempts_consumed == 2
    assert recovery_step.recovered_operation is True
    assert len(gateway.start_calls) == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_existing_confirmed_evidence_is_reused_without_duplicate_on_poll_retry(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "evidence-dedupe.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        assert gateway.start_calls
        continuation = ExactSearchContinuation(
            search_id="search-1",
            results_url="results.aviasales.ru",
            last_update_timestamp=0,
            request_id="request-1",
            evidence_namespace=gateway.start_calls[0].evidence_namespace,
            expected_origin="LED",
            expected_destination="CDG",
            expected_departure_date=date(2026, 9, 10),
            expected_return_date=None,
            expected_currency="RUB",
            passengers=1,
        )
        evidence = gateway.evidence_for(continuation)
        await AgentEvidenceRepository(session).append_confirmed_evidence(
            _stored_evidence(evidence, stage_id=poll.stage_id)
        )
        await session.commit()

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()

    assert count == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_cancel_before_next_claim_and_expired_deadline_make_zero_new_provider_calls(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "cancel-no-io.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        calls_before_cancel = gateway.provider_calls
        await AgentRunRepository(session).set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancel_requested",
            changed_at=NOW + timedelta(seconds=1),
        )
        await session.commit()
        clock.value = NOW + timedelta(seconds=2)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        cancelled = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (cancelled_stage,) = await AgentOperationRepository(session).list_stages(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert cancelled is not None and cancelled.status == "cancelled"
    assert cancelled_stage.status is AgentStageStatus.PARTIAL
    assert gateway.provider_calls == calls_before_cancel == 1
    await engine.dispose()

    deadline_engine, deadline_sessions = await _session_factory(
        tmp_path,
        "deadline-no-io.db",
    )
    await _seed_run(deadline_sessions, date_mode="exact", deadline_seconds=1)
    deadline_clock = MutableClock(NOW + timedelta(seconds=2))
    deadline_gateway = ResumableFakeGateway(deadline_clock)
    async with deadline_sessions() as session:
        service = _service(execution_module, session, deadline_gateway, deadline_clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        expired = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert expired is not None and expired.status == "failed"
    assert expired.error_code == "agent_run_deadline_exceeded"
    assert expired.logical_operations_consumed == 0
    assert expired.http_attempts_consumed == 0
    assert deadline_gateway.provider_calls == 0
    await deadline_engine.dispose()


@pytest.mark.anyio
async def test_cancel_only_stage_is_cancelled_while_deadline_only_stage_is_skipped(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    cancel_engine, cancel_sessions = await _session_factory(tmp_path, "cancel-stage.db")
    await _seed_run(cancel_sessions, date_mode="exact")
    cancel_clock = MutableClock()
    cancel_gateway = ResumableFakeGateway(cancel_clock)
    async with cancel_sessions() as session:
        service = _service(execution_module, session, cancel_gateway, cancel_clock)
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        await service._ensure_initial_operation(run, cancel_clock())
        await AgentRunRepository(session).set_status(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
            status="cancel_requested",
            changed_at=NOW + timedelta(seconds=1),
        )
        await session.commit()
        cancel_clock.value = NOW + timedelta(seconds=2)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (cancel_stage,) = await AgentOperationRepository(session).list_stages(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert cancel_stage.status is AgentStageStatus.CANCELLED
    assert cancel_gateway.provider_calls == 0
    await cancel_engine.dispose()

    deadline_engine, deadline_sessions = await _session_factory(tmp_path, "deadline-stage.db")
    await _seed_run(deadline_sessions, date_mode="exact", deadline_seconds=1)
    deadline_clock = MutableClock()
    deadline_gateway = ResumableFakeGateway(deadline_clock)
    async with deadline_sessions() as session:
        service = _service(execution_module, session, deadline_gateway, deadline_clock)
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        await service._ensure_initial_operation(run, deadline_clock())
        await session.commit()
        deadline_clock.value = NOW + timedelta(seconds=2)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (deadline_stage,) = await AgentOperationRepository(session).list_stages(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert deadline_stage.status is AgentStageStatus.SKIPPED
    assert deadline_gateway.provider_calls == 0
    await deadline_engine.dispose()


@pytest.mark.anyio
async def test_deadline_preserves_evidence_but_fails_without_saved_ranking_snapshot(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "deadline-partial.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
        deadline_seconds=5,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    gateway.calendar_results.append(
        (
            _signal(uuid4(), date(2026, 9, 10), 10_000),
            _signal(uuid4(), date(2026, 9, 11), 11_000),
        )
    )

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        for _ in range(8):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
        evidence_before = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        calls_before_deadline = gateway.provider_calls
        assert len(evidence_before) == 1

        clock.value = NOW + timedelta(seconds=6)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        evidence_after = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        stages = await AgentOperationRepository(session).list_stages(HOUSEHOLD_ID, RUN_ID)

    exact_stage = next(stage for stage in stages if stage.kind is AgentPlanStageKind.EXACT_SEARCH)
    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_run_deadline_exceeded"
    assert evidence_after == evidence_before
    assert gateway.provider_calls == calls_before_deadline
    assert exact_stage.status is AgentStageStatus.PARTIAL
    await engine.dispose()


@pytest.mark.anyio
async def test_http_and_logical_budgets_stop_before_unreserved_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "http-budget.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        logical_budget=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    async with sessions() as session:
        await session.execute(
            update(agent_plan_runs_table)
            .where(agent_plan_runs_table.c.id == str(RUN_ID))
            .values(http_attempts_consumed=8)
        )
        await session.commit()
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )

    assert terminal.status == "failed"
    assert terminal.error_code == "agent_http_budget_exhausted"
    assert terminal.logical_operations_consumed == 1
    assert terminal.http_attempts_consumed == 9
    assert len(gateway.start_calls) == 1
    assert gateway.poll_calls == []
    await engine.dispose()

    logical_engine, logical_sessions = await _session_factory(
        tmp_path,
        "logical-budget.db",
    )
    await _seed_run(
        logical_sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    logical_clock = MutableClock()
    logical_gateway = ResumableFakeGateway(logical_clock)
    logical_gateway.calendar_results.append(_complete_flexible_signals())
    async with logical_sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, logical_gateway, logical_clock),
            session,
            limit=24,
        )

    assert terminal.status == "completed"
    assert terminal.logical_operations_consumed == 10
    assert terminal.http_attempts_consumed == 15
    assert len(logical_gateway.calendar_calls) == 5
    assert len(logical_gateway.start_calls) == 5
    assert len(logical_gateway.poll_calls) == 5
    await logical_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (AviasalesSearchAuthFailed(), "provider_auth"),
        (AviasalesSearchBlocked(), "provider_forbidden"),
        (AviasalesSearchSchemaError(), "provider_schema"),
        (AviasalesSearchHttpStatusError(status_code=418), "provider_client_error"),
    ),
)
async def test_401_403_and_schema_failures_are_terminal_and_body_free(
    tmp_path: Path,
    execution_module: ModuleType,
    failure: BaseException,
    expected_code: str,
) -> None:
    engine, sessions = await _session_factory(tmp_path, f"terminal-{expected_code}.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, start_behaviors=[failure])

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "failed"
    assert operation.status is AgentOperationStatus.FAILED
    assert operation.error_code == expected_code
    assert operation.next_retry_at is None
    assert gateway.provider_calls == 1
    assert str(failure) not in (terminal.error_message or "")
    await engine.dispose()


@pytest.mark.anyio
async def test_malformed_start_outcome_is_schema_failure_before_success_handoff(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "malformed-start-outcome.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    start_calls = 0

    async def malformed_start(
        _gateway: ResumableFakeGateway,
        *_args: object,
        **_kwargs: object,
    ) -> object:
        nonlocal start_calls
        start_calls += 1
        return ExactPollOutcome(evidence=(), next_cursor=1, complete=False)

    monkeypatch.setattr(ResumableFakeGateway, "start_exact", malformed_start)
    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservation = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().one()
        )

    assert terminal.status == "failed"
    assert len(operations) == 1
    assert operations[0].kind is AgentOperationKind.EXACT_START
    assert operations[0].status is AgentOperationStatus.FAILED
    assert operations[0].error_code == "provider_schema"
    assert reservation["circuit_outcome"] == "non_transient_failure"
    assert start_calls == 1
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("malformation", ("cursor", "binding", "cardinality"))
async def test_invalid_poll_outcome_never_becomes_live(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    malformation: str,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"invalid-poll-{malformation}.db",
    )
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()

        async def invalid_poll(
            fake_gateway: ResumableFakeGateway,
            continuation: ExactSearchContinuation,
            **_kwargs: object,
        ) -> ExactPollOutcome:
            fake_gateway.poll_calls.append(continuation)
            if malformation == "cursor":
                return ExactPollOutcome(
                    evidence=(),
                    next_cursor=(1 if continuation.last_update_timestamp == 0 else 0),
                    complete=False,
                )
            base = fake_gateway.evidence_for(continuation)
            if malformation == "binding":
                return ExactPollOutcome(
                    evidence=(replace(base, origin="SVO"),),
                    next_cursor=continuation.last_update_timestamp + 1,
                    complete=False,
                )
            oversized: list[ConfirmedOfferEvidence] = []
            for index in range(51):
                provider_offer_id = f"fixture-offer-{index}"
                oversized.append(
                    replace(
                        base,
                        id=uuid5(
                            continuation.evidence_namespace,
                            f"exact|{provider_offer_id}|{continuation.passengers}",
                        ),
                        provider_offer_id=provider_offer_id,
                    )
                )
            return ExactPollOutcome(
                evidence=tuple(oversized),
                next_cursor=continuation.last_update_timestamp + 1,
                complete=False,
            )

        monkeypatch.setattr(ResumableFakeGateway, "poll_exact_once", invalid_poll)
        terminal = await _run_until_terminal(service, session)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
        reservations = (
            (
                await session.execute(
                    select(agent_provider_http_attempts_table).order_by(
                        agent_provider_http_attempts_table.c.reserved_at
                    )
                )
            )
            .mappings()
            .all()
        )

    assert terminal.status == "failed"
    expected_kinds = [
        AgentOperationKind.EXACT_START,
        AgentOperationKind.EXACT_POLL,
    ]
    if malformation == "cursor":
        expected_kinds.append(AgentOperationKind.EXACT_POLL)
    assert [operation.kind for operation in operations] == expected_kinds
    assert operations[-1].status is AgentOperationStatus.FAILED
    assert operations[-1].error_code == "provider_schema"
    assert evidence_count == 0
    expected_circuit_outcomes = ["success", "non_transient_failure"]
    if malformation == "cursor":
        expected_circuit_outcomes.insert(1, "success")
    assert [row["circuit_outcome"] for row in reservations] == expected_circuit_outcomes
    assert len(gateway.poll_calls) == (2 if malformation == "cursor" else 1)
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("offset_seconds", "expected_status", "expected_evidence"),
    (
        (-300, "succeeded", 1),
        (300, "succeeded", 1),
        (-301, "failed", 0),
        (301, "failed", 0),
    ),
)
async def test_exact_live_evidence_is_bounded_to_response_clock_skew(
    tmp_path: Path,
    execution_module: ModuleType,
    offset_seconds: int,
    expected_status: str,
    expected_evidence: int,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"exact-live-window-{offset_seconds}.db",
    )
    await _seed_run(sessions, date_mode="exact", deadline_seconds=1800)
    response_time = NOW + timedelta(minutes=10)
    clock = MutableClock(response_time)
    gateway = ResumableFakeGateway(
        clock,
        evidence_observed_at=response_time + timedelta(seconds=offset_seconds),
    )

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )

    assert step.operation_status == expected_status
    assert poll.status.value == expected_status
    assert len(evidence) == expected_evidence
    assert poll.error_code == ("provider_schema" if expected_status == "failed" else None)
    await engine.dispose()


@pytest.mark.anyio
async def test_stale_calendar_replay_is_provider_schema_before_live_persistence(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "calendar-stale-replay.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
        deadline_seconds=1800,
    )
    response_time = NOW + timedelta(minutes=10)
    clock = MutableClock(response_time)
    gateway = ResumableFakeGateway(
        clock,
        calendar_results=[
            (
                _signal(
                    uuid4(),
                    date(2026, 9, 8),
                    9_000,
                    observed_at=response_time - timedelta(seconds=301),
                ),
            )
        ],
    )

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        signals = await AgentEvidenceRepository(session).list_discovery_signals(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        first_calendar = next(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.CALENDAR_SEARCH
            and operation.immutable_input["departure_date"] == "2026-09-08"
        )

    assert step.operation_status == "failed"
    assert first_calendar.error_code == "provider_schema"
    assert signals == ()
    await engine.dispose()


@pytest.mark.anyio
async def test_provider_preflight_denial_is_terminal_before_permit_or_http_reservation(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "provider-preflight.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    preflight_calls = 0

    def deny_provider() -> None:
        nonlocal preflight_calls
        preflight_calls += 1
        raise AviasalesSearchPolicyDenied("disabled:private-provider-secret")

    async with sessions() as session:
        terminal = await _run_until_terminal(
            _service(
                execution_module,
                session,
                gateway,
                clock,
                provider_preflight=deny_provider,
            ),
            session,
        )
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal.status == "failed"
    assert terminal.http_attempts_consumed == 0
    assert operation.status is AgentOperationStatus.FAILED
    assert operation.error_code == "provider_policy_denied"
    assert preflight_calls == 1
    assert reservations == 0
    assert gateway.provider_calls == 0
    assert "private-provider-secret" not in (terminal.error_message or "")
    await engine.dispose()


@pytest.mark.anyio
async def test_preflight_deadline_crossing_skips_before_permit_reservation_or_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "preflight-deadline-crossing.db")
    await _seed_run(sessions, date_mode="exact", deadline_seconds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    def advance_past_deadline() -> None:
        clock.value += timedelta(seconds=2)

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            provider_preflight=advance_past_deadline,
        )
        first = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        repeated = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()
        circuit_rows = (
            await session.execute(
                select(func.count()).select_from(agent_provider_circuit_state_table)
            )
        ).scalar_one()

    assert first.operation_status == "skipped" and first.run_status == "failed"
    assert repeated.operation_claimed is False and repeated.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_run_deadline_exceeded"
    assert terminal.http_attempts_consumed == 0
    assert operation.status is AgentOperationStatus.SKIPPED
    assert operation.error_code == "agent_run_deadline_exceeded"
    assert circuit_rows == reservations == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_deadline_crossing_after_circuit_acquire_abandons_permit_before_reservation(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "permit-deadline-crossing.db")
    await _seed_run(sessions, date_mode="exact", deadline_seconds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        original_acquire = service._operations.acquire_circuit_permit

        async def acquire_then_expire(**kwargs: object):
            permit = await original_acquire(**kwargs)
            clock.value += timedelta(seconds=2)
            return permit

        monkeypatch.setattr(
            service._operations,
            "acquire_circuit_permit",
            acquire_then_expire,
        )
        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operation = (
            (
                await session.execute(
                    select(agent_run_operations_table).where(
                        agent_run_operations_table.c.run_id == str(RUN_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert step.operation_status == "skipped" and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_run_deadline_exceeded"
    assert terminal.http_attempts_consumed == 0
    assert operation["status"] == AgentOperationStatus.SKIPPED.value
    assert operation["circuit_permit_token_digest"] is None
    assert reservations == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_cancel_crossing_after_circuit_acquire_abandons_permit_before_reservation(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "permit-cancel-crossing.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        original_acquire = service._operations.acquire_circuit_permit

        async def acquire_then_cancel(**kwargs: object):
            permit = await original_acquire(**kwargs)
            await AgentRunRepository(session).set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancel_requested",
                changed_at=clock(),
            )
            return permit

        monkeypatch.setattr(
            service._operations,
            "acquire_circuit_permit",
            acquire_then_cancel,
        )
        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operation = (
            (
                await session.execute(
                    select(agent_run_operations_table).where(
                        agent_run_operations_table.c.run_id == str(RUN_ID)
                    )
                )
            )
            .mappings()
            .one()
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert step.operation_status == "skipped" and step.run_status == "cancelled"
    assert terminal is not None and terminal.status == "cancelled"
    assert terminal.http_attempts_consumed == 0
    assert operation["status"] == AgentOperationStatus.SKIPPED.value
    assert operation["circuit_permit_token_digest"] is None
    assert reservations == gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_checkpoint_deadline_crossing_skips_dispatch_and_releases_half_open_probe(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "checkpoint-deadline-crossing.db")
    await _seed_run(sessions, date_mode="exact", deadline_seconds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        await session.execute(
            insert(agent_provider_circuit_state_table).values(
                provider_id="aviasales_search",
                state="open",
                consecutive_transient_failures=1,
                opened_at=NOW - timedelta(seconds=30),
                cooldown_until=NOW,
                half_open_probe_operation_id=None,
                half_open_probe_attempt_number=None,
                half_open_probe_token_digest=None,
                half_open_probe_expires_at=None,
                generation=1,
                version=1,
                updated_at=NOW,
            )
        )
        await session.commit()

        async def checkpoint_then_expire() -> None:
            await session.commit()
            clock.value += timedelta(seconds=2)

        step = await _service(
            execution_module,
            session,
            gateway,
            clock,
            durability_checkpoint=checkpoint_then_expire,
        ).run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservation = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().one()
        )
        circuit = (
            (await session.execute(select(agent_provider_circuit_state_table))).mappings().one()
        )

    assert step.operation_status == "skipped" and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_run_deadline_exceeded"
    assert terminal.http_attempts_consumed == 1
    assert operation.status is AgentOperationStatus.SKIPPED
    assert reservation["circuit_outcome"] is None
    assert circuit["state"] == "open"
    assert circuit["half_open_probe_token_digest"] is None
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_checkpoint_cancel_crossing_skips_dispatch_and_abandons_reservation(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "checkpoint-cancel-crossing.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:

        async def checkpoint_then_cancel() -> None:
            await session.commit()
            await AgentRunRepository(session).set_status(
                household_id=HOUSEHOLD_ID,
                run_id=RUN_ID,
                status="cancel_requested",
                changed_at=clock(),
            )
            await session.commit()

        step = await _service(
            execution_module,
            session,
            gateway,
            clock,
            durability_checkpoint=checkpoint_then_cancel,
        ).run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservation = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().one()
        )

    assert step.operation_status == "skipped" and step.run_status == "cancelled"
    assert terminal is not None and terminal.status == "cancelled"
    assert terminal.http_attempts_consumed == 1
    assert operation.status is AgentOperationStatus.SKIPPED
    assert reservation["circuit_outcome"] is None
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_exact_start_response_after_deadline_does_not_materialize_future_poll(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "response-after-deadline.db")
    await _seed_run(sessions, date_mode="exact", deadline_seconds=1)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, advance_on_start_seconds=2)

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == "skipped" and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "agent_run_deadline_exceeded"
    assert len(operations) == 1
    assert operations[0].kind is AgentOperationKind.EXACT_START
    assert operations[0].status is AgentOperationStatus.SKIPPED
    assert gateway.provider_calls == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_huge_retry_after_is_bounded_and_terminal_when_no_retry_window_remains(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "huge-retry-after.db")
    await _seed_run(
        sessions,
        date_mode="exact",
        deadline_seconds=1800,
        start_attempts=3,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchRateLimited(retry_after_seconds=10**30)],
    )

    async with sessions() as session:
        step = await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        reservation = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().one()
        )

    assert step.operation_status == "failed" and step.run_status == "failed"
    assert terminal is not None and terminal.error_code == "provider_rate_limited"
    assert terminal.http_attempts_consumed == 1
    assert operation.status is AgentOperationStatus.FAILED
    assert operation.error_code == "provider_rate_limited"
    assert operation.next_retry_at is None
    assert reservation["circuit_outcome"] == "non_transient_failure"
    assert gateway.provider_calls == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_429_uses_retry_after_and_does_not_hide_an_internal_retry(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "rate-limit.db")
    await _seed_run(sessions, date_mode="exact", start_attempts=3)
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchRateLimited(retry_after_seconds=47)],
    )

    async with sessions() as session:
        await _service(execution_module, session, gateway, clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        (stage,) = await AgentOperationRepository(session).list_stages(HOUSEHOLD_ID, RUN_ID)

    assert run is not None and run.status == "running"
    assert run.http_attempts_consumed == 1
    assert operation.status is AgentOperationStatus.RETRY_WAIT
    assert operation.next_retry_at == NOW + timedelta(seconds=47)
    assert operation.error_code == "provider_rate_limited"
    assert stage.status is AgentStageStatus.RUNNING
    assert gateway.provider_calls == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_provider_response_time_drives_retry_and_completion_without_stale_lease_write(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    rate_engine, rate_sessions = await _session_factory(tmp_path, "response-time-rate.db")
    await _seed_run(rate_sessions, date_mode="exact", start_attempts=3)
    rate_clock = MutableClock()
    rate_gateway = ResumableFakeGateway(
        rate_clock,
        start_behaviors=[AviasalesSearchRateLimited(retry_after_seconds=47)],
        advance_on_start_seconds=7,
    )
    async with rate_sessions() as session:
        await _service(execution_module, session, rate_gateway, rate_clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert waiting.next_retry_at == NOW + timedelta(seconds=54)
    await rate_engine.dispose()

    success_engine, success_sessions = await _session_factory(tmp_path, "response-time-success.db")
    await _seed_run(success_sessions, date_mode="exact")
    success_clock = MutableClock()
    success_gateway = ResumableFakeGateway(success_clock, advance_on_start_seconds=3)
    async with success_sessions() as session:
        await _service(execution_module, session, success_gateway, success_clock).run_step(
            household_id=HOUSEHOLD_ID,
            run_id=RUN_ID,
        )
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        start = next(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.EXACT_START
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )

    assert start.completed_at == NOW + timedelta(seconds=3)
    assert poll.created_at == NOW + timedelta(seconds=3)
    await success_engine.dispose()

    stale_engine, stale_sessions = await _session_factory(tmp_path, "response-time-stale.db")
    await _seed_run(stale_sessions, date_mode="exact")
    stale_clock = MutableClock()
    stale_gateway = ResumableFakeGateway(stale_clock, advance_on_start_seconds=61)
    async with stale_sessions() as session:
        step = await _service(
            execution_module,
            session,
            stale_gateway,
            stale_clock,
            operation_lease_seconds=60,
        ).run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == "leased"
    assert len(operations) == 1
    assert operations[0].status is AgentOperationStatus.LEASED
    assert operations[0].completed_at is None
    assert stale_gateway.provider_calls == 1
    await stale_engine.dispose()


@pytest.mark.anyio
async def test_provider_clock_advance_past_deadline_fails_without_saved_ranking_snapshot(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "response-time-partial.db")
    await _seed_run(sessions, date_mode="exact", deadline_seconds=5)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, advance_on_poll_seconds=6)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        evidence = await AgentEvidenceRepository(session).list_confirmed_evidence(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert step.operation_status == "succeeded"
    assert step.run_status == "failed"
    assert run is not None and run.status == "failed"
    assert run.error_code == "agent_run_deadline_exceeded"
    assert len(evidence) == 1
    assert gateway.provider_calls == 2
    await engine.dispose()


@pytest.mark.anyio
async def test_transport_and_5xx_retries_are_new_bounded_leases_and_http_attempts(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "network-retry.db")
    await _seed_run(sessions, date_mode="exact", start_attempts=2)
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchTransportError(), None],
    )
    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert waiting.next_retry_at is not None
        clock.value = waiting.next_retry_at
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        after_retry = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)

    assert after_retry is not None
    assert after_retry.http_attempts_consumed == 2
    assert len(gateway.start_calls) == 2
    await engine.dispose()

    failed_engine, failed_sessions = await _session_factory(tmp_path, "server-bounded.db")
    await _seed_run(failed_sessions, date_mode="exact", start_attempts=2)
    failed_clock = MutableClock()
    failed_gateway = ResumableFakeGateway(
        failed_clock,
        start_behaviors=[
            AviasalesSearchHttpStatusError(status_code=503),
            AviasalesSearchHttpStatusError(status_code=503),
        ],
    )
    async with failed_sessions() as session:
        service = _service(execution_module, session, failed_gateway, failed_clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert waiting.next_retry_at is not None
        failed_clock.value = waiting.next_retry_at
        terminal = await _run_until_terminal(service, session)
        (server_failure,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )

    assert terminal.status == "failed"
    assert terminal.http_attempts_consumed == 2
    assert server_failure.error_code == "provider_server"
    assert len(failed_gateway.start_calls) == 2
    await failed_engine.dispose()


@pytest.mark.anyio
async def test_open_circuit_makes_zero_call_and_successful_half_open_probe_closes_it(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit.db")
    await _seed_run(sessions, date_mode="exact", start_attempts=4)
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchTransportError(), None],
    )
    service_policy = {
        "circuit_failure_threshold": 1,
        "circuit_cooldown_seconds": 30,
    }

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            **service_policy,
        )
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert waiting.next_retry_at is not None
        clock.value = waiting.next_retry_at

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        assert gateway.provider_calls == 1
        (circuit_wait,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert circuit_wait.next_retry_at is not None
        clock.value = circuit_wait.next_retry_at

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        circuit = await AgentOperationRepository(session).get_circuit_state("aviasales_search")

    assert gateway.provider_calls == 2
    assert circuit is not None
    assert circuit.state.value == "closed"
    assert circuit.consecutive_transient_failures == 0
    await engine.dispose()


@pytest.mark.anyio
async def test_late_success_after_newer_circuit_generation_persists_valid_handoff(
    tmp_path: Path,
    execution_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "late-circuit-success.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        original_record = service._operations.record_circuit_success

        async def advance_generation_then_record(**kwargs: object):
            await session.execute(
                update(agent_provider_circuit_state_table)
                .where(agent_provider_circuit_state_table.c.provider_id == "aviasales_search")
                .values(
                    state="open",
                    consecutive_transient_failures=7,
                    opened_at=clock(),
                    cooldown_until=clock() + timedelta(seconds=60),
                    half_open_probe_operation_id=None,
                    half_open_probe_attempt_number=None,
                    half_open_probe_token_digest=None,
                    half_open_probe_expires_at=None,
                    generation=agent_provider_circuit_state_table.c.generation + 3,
                    version=agent_provider_circuit_state_table.c.version + 3,
                    updated_at=clock(),
                )
            )
            return await original_record(**kwargs)

        monkeypatch.setattr(
            service._operations,
            "record_circuit_success",
            advance_generation_then_record,
        )
        step = await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        circuit = await AgentOperationRepository(session).get_circuit_state("aviasales_search")
        reservation = (
            (await session.execute(select(agent_provider_http_attempts_table))).mappings().one()
        )

    assert step.operation_status == "succeeded" and step.run_status == "running"
    assert gateway.provider_calls == 1
    assert len(operations) == 2
    assert operations[0].kind is AgentOperationKind.EXACT_START
    assert operations[0].status is AgentOperationStatus.SUCCEEDED
    assert operations[0].result_type is AgentOperationResultType.OPERATION
    assert operations[0].result_id == operations[1].id
    assert circuit is not None and circuit.state.value == "open"
    assert circuit.consecutive_transient_failures == 7
    assert circuit.generation == 3
    assert reservation["circuit_outcome"] == "success"
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("approved_rpm", "current_rpm", "effective_rpm"),
    ((5, 20, 5), (20, 3, 3)),
)
async def test_approved_and_current_rpm_use_lower_limit_before_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
    approved_rpm: int,
    current_rpm: int,
    effective_rpm: int,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"approved-rpm-{approved_rpm}-{current_rpm}.db",
    )
    await _seed_run(
        sessions,
        date_mode="exact",
        poll_rounds=10,
        attempts_per_poll=2,
        requests_per_minute=approved_rpm,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, poll_behaviors=list(range(1, 11)))

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            provider_rpm=current_rpm,
        )
        for _ in range(effective_rpm + 1):
            await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
            await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        waiting = next(
            operation
            for operation in operations
            if operation.status is AgentOperationStatus.RETRY_WAIT
        )
        private_permit = (
            await session.execute(
                select(agent_run_operations_table.c.circuit_permit_token_digest).where(
                    agent_run_operations_table.c.id == str(waiting.id)
                )
            )
        ).scalar_one()
        circuit = await AgentOperationRepository(session).get_circuit_state("aviasales_search")

    assert gateway.provider_calls == effective_rpm
    assert waiting.error_code == "agent_provider_rate_wait"
    assert waiting.next_retry_at == NOW + timedelta(minutes=1)
    assert private_permit is None
    assert circuit is not None and circuit.state.value == "closed"
    await engine.dispose()


@pytest.mark.anyio
async def test_half_open_local_rate_denial_releases_probe_for_unrelated_operation(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "half-open-local-denial.db")
    await _seed_run(
        sessions,
        date_mode="range",
        calendar_searches=3,
        exact_searches=3,
        logical_budget=6,
        start_attempts=4,
        requests_per_minute=1,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[AviasalesSearchTransportError()],
    )

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=30,
        )
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        workflow = await service._workflow(run)
        stage = await service._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=clock.value,
        )
        await service._materialize_exact_start(
            run,
            stage.id,
            workflow,
            departure_date=workflow.departure_date,
            return_date=workflow.return_date,
            ordinal=0,
            now=clock.value,
        )
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert waiting.next_retry_at is not None
        clock.value = waiting.next_retry_at
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (circuit_wait,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert circuit_wait.next_retry_at is not None
        clock.value = circuit_wait.next_retry_at

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        released = await AgentOperationRepository(session).get_circuit_state("aviasales_search")
        assert released is not None
        assert released.state.value == "open"
        assert released.cooldown_until == clock.value
        assert released.half_open_probe_operation_id is None

        sibling = await service._materialize_exact_start(
            run,
            stage.id,
            workflow,
            departure_date=workflow.departure_date + timedelta(days=1),
            return_date=workflow.return_date,
            ordinal=1,
            now=clock.value,
        )
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        sibling_after = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            sibling.id,
        )
        released_again = await AgentOperationRepository(session).get_circuit_state(
            "aviasales_search"
        )

    assert gateway.provider_calls == 1
    assert sibling_after is not None
    assert sibling_after.status is AgentOperationStatus.RETRY_WAIT
    assert sibling_after.error_code == "agent_provider_rate_wait"
    assert released_again is not None and released_again.state.value == "open"
    assert released_again.half_open_probe_operation_id is None
    await engine.dispose()


@pytest.mark.anyio
async def test_half_open_rate_limited_response_closes_circuit_and_keeps_retry_after(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "half-open-provider-429.db")
    await _seed_run(
        sessions,
        date_mode="range",
        calendar_searches=3,
        exact_searches=3,
        logical_budget=6,
        start_attempts=4,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[
            AviasalesSearchTransportError(),
            AviasalesSearchRateLimited(retry_after_seconds=47),
            None,
        ],
    )

    async with sessions() as session:
        service = _service(
            execution_module,
            session,
            gateway,
            clock,
            circuit_failure_threshold=1,
            circuit_cooldown_seconds=30,
        )
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        workflow = await service._workflow(run)
        stage = await service._stage(
            run,
            AgentPlanStageKind.EXACT_SEARCH,
            prefix=0x02,
            now=clock.value,
        )
        await service._materialize_exact_start(
            run,
            stage.id,
            workflow,
            departure_date=workflow.departure_date,
            return_date=workflow.return_date,
            ordinal=0,
            now=clock.value,
        )
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (waiting,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert waiting.next_retry_at is not None
        clock.value = waiting.next_retry_at
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (circuit_wait,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        assert circuit_wait.next_retry_at is not None
        clock.value = circuit_wait.next_retry_at

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        (rate_wait,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        circuit = await AgentOperationRepository(session).get_circuit_state("aviasales_search")
        assert circuit is not None and circuit.state.value == "closed"
        assert circuit.half_open_probe_operation_id is None

        sibling = await service._materialize_exact_start(
            run,
            stage.id,
            workflow,
            departure_date=workflow.departure_date + timedelta(days=1),
            return_date=workflow.return_date,
            ordinal=1,
            now=clock.value,
        )
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        sibling_after = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            sibling.id,
        )

    assert rate_wait.status is AgentOperationStatus.RETRY_WAIT
    assert rate_wait.error_code == "provider_rate_limited"
    assert rate_wait.next_retry_at == clock.value + timedelta(seconds=47)
    assert sibling_after is not None
    assert sibling_after.status is AgentOperationStatus.SUCCEEDED
    assert gateway.provider_calls == 3
    await engine.dispose()


@pytest.mark.anyio
async def test_useful_confirmed_evidence_plus_failure_is_partial_but_none_is_failed(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "partial.db")
    await _seed_run(
        sessions,
        date_mode="flexible",
        calendar_searches=5,
        exact_searches=5,
        logical_budget=10,
    )
    clock = MutableClock()
    gateway = ResumableFakeGateway(
        clock,
        start_behaviors=[None, AviasalesSearchSchemaError()],
    )
    gateway.calendar_results.append(
        (
            _signal(uuid4(), date(2026, 9, 10), 10_000),
            _signal(uuid4(), date(2026, 9, 11), 11_000),
        )
    )

    async with sessions() as session:
        partial = await _run_until_terminal(
            _service(execution_module, session, gateway, clock),
            session,
            limit=20,
        )
        evidence_count = (
            await session.execute(
                select(func.count()).select_from(agent_confirmed_offer_evidence_table)
            )
        ).scalar_one()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        ranking_operations = tuple(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.RANKING
            and operation.status is AgentOperationStatus.SUCCEEDED
            and operation.result_type is AgentOperationResultType.RANKING_SNAPSHOT
            and operation.result_id is not None
        )
        assert len(ranking_operations) == 1
        ranking = await AgentEvidenceRepository(session).get_ranking_snapshot(
            HOUSEHOLD_ID,
            ranking_operations[0].result_id,
        )

    assert evidence_count == 1
    assert partial.status == "partial"
    assert partial.error_code == "agent_run_partial"
    assert ranking is not None and ranking.run_id == RUN_ID
    await engine.dispose()

    failed_engine, failed_sessions = await _session_factory(tmp_path, "failed.db")
    await _seed_run(failed_sessions, date_mode="exact")
    failed_clock = MutableClock()
    failed_gateway = ResumableFakeGateway(
        failed_clock,
        start_behaviors=[AviasalesSearchSchemaError()],
    )
    async with failed_sessions() as session:
        failed = await _run_until_terminal(
            _service(execution_module, session, failed_gateway, failed_clock),
            session,
        )

    assert failed.status == "failed"
    assert failed.error_code == "provider_schema"
    await failed_engine.dispose()


@pytest.mark.anyio
async def test_household_scope_and_private_continuation_never_cross_public_boundary(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "private-boundary.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        with pytest.raises(execution_module.AgentExecutionError) as denied:
            await service.run_step(household_id=OTHER_HOUSEHOLD_ID, run_id=RUN_ID)
        assert denied.value.code == "agent_run_not_found"
        assert gateway.provider_calls == 0

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        raw_private = (
            await session.execute(
                select(agent_run_operations_table.c.private_continuation_json).where(
                    agent_run_operations_table.c.id == str(poll.id)
                )
            )
        ).scalar_one()

    assert "search-1" in raw_private
    assert "results.aviasales.ru" in raw_private
    assert not hasattr(poll, "private_continuation")
    assert "search-1" not in repr(poll)
    assert "results.aviasales.ru" not in repr(poll)
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "immutable_patch",
    (
        {"origin": "SVO"},
        {"departure_date": "2030-01-01"},
        {"adults": 2, "passengers": 2},
        {"currency": "USD"},
    ),
)
async def test_tampered_exact_start_facts_fail_before_permit_reservation_or_io(
    tmp_path: Path,
    execution_module: ModuleType,
    immutable_patch: dict[str, object],
) -> None:
    label = next(iter(immutable_patch))
    engine, sessions = await _session_factory(tmp_path, f"start-binding-{label}.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        assert run is not None
        await service._ensure_initial_operation(run, clock())
        (operation,) = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        tampered = {**operation.immutable_input, **immutable_patch}
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(operation.id))
            .values(immutable_input_json=json.dumps(tampered, separators=(",", ":")))
        )
        await session.commit()

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        failed = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            operation.id,
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert terminal.http_attempts_consumed == 0
    assert failed is not None and failed.status is AgentOperationStatus.FAILED
    assert reservations == 0
    assert gateway.provider_calls == 0
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "private_patch",
    (
        {"search_id": "tampered-search"},
        {"search_session": "tampered-results.aviasales.ru"},
        {"request_id": "tampered-request"},
        {"evidence_namespace": "99999999-9999-9999-9999-999999999999"},
        {"origin": "SVO"},
        {"departure_date": "2030-01-01"},
        {"currency": "USD"},
        {"passengers": 2},
    ),
)
async def test_tampered_exact_poll_binding_fails_before_new_reservation_or_io(
    tmp_path: Path,
    execution_module: ModuleType,
    private_patch: dict[str, object],
) -> None:
    label = next(iter(private_patch))
    engine, sessions = await _session_factory(tmp_path, f"poll-binding-{label}.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        raw_private = (
            await session.execute(
                select(agent_run_operations_table.c.private_continuation_json).where(
                    agent_run_operations_table.c.id == str(poll.id)
                )
            )
        ).scalar_one()
        tampered = {**json.loads(raw_private), **private_patch}
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(poll.id))
            .values(private_continuation_json=json.dumps(tampered, separators=(",", ":")))
        )
        await session.commit()
        calls_before = gateway.provider_calls

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        failed = await AgentOperationRepository(session).get_operation(HOUSEHOLD_ID, poll.id)
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert terminal.http_attempts_consumed == 1
    assert failed is not None and failed.status is AgentOperationStatus.FAILED
    assert reservations == 1
    assert gateway.provider_calls == calls_before == 1
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "private_patch",
    (
        {"search_id": "tampered-search"},
        {"search_session": "tampered-results.aviasales.ru"},
        {"request_id": "tampered-request"},
    ),
)
async def test_tampered_later_poll_private_identity_fails_before_reservation_or_io(
    tmp_path: Path,
    execution_module: ModuleType,
    private_patch: dict[str, object],
) -> None:
    label = next(iter(private_patch))
    engine, sessions = await _session_factory(tmp_path, f"later-poll-binding-{label}.db")
    await _seed_run(sessions, date_mode="exact", poll_rounds=3)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock, poll_behaviors=[17, "evidence"])

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        later_poll = next(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.EXACT_POLL
            and operation.immutable_input["poll_round"] == 2
        )
        raw_private = (
            await session.execute(
                select(agent_run_operations_table.c.private_continuation_json).where(
                    agent_run_operations_table.c.id == str(later_poll.id)
                )
            )
        ).scalar_one()
        tampered = {**json.loads(raw_private), **private_patch}
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(later_poll.id))
            .values(private_continuation_json=json.dumps(tampered, separators=(",", ":")))
        )
        await session.commit()
        calls_before = gateway.provider_calls
        reservations_before = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        failed = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            later_poll.id,
        )
        reservations_after = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert failed is not None and failed.status is AgentOperationStatus.FAILED
    assert reservations_after == reservations_before
    assert gateway.provider_calls == calls_before == 2
    await engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("broken_link", ("root_result", "poll_root"))
async def test_tampered_poll_handoff_chain_fails_before_new_reservation_or_io(
    tmp_path: Path,
    execution_module: ModuleType,
    broken_link: str,
) -> None:
    engine, sessions = await _session_factory(
        tmp_path,
        f"poll-chain-{broken_link}.db",
    )
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        root = next(
            operation
            for operation in operations
            if operation.kind is AgentOperationKind.EXACT_START
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        if broken_link == "root_result":
            await session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(root.id))
                .values(result_id=str(uuid4()))
            )
        else:
            await session.execute(
                update(agent_run_operations_table)
                .where(agent_run_operations_table.c.id == str(poll.id))
                .values(logical_root_operation_id=str(poll.id))
            )
        await session.commit()
        calls_before = gateway.provider_calls

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        failed = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            poll.id,
        )
        reservations = (
            await session.execute(
                select(func.count()).select_from(agent_provider_http_attempts_table)
            )
        ).scalar_one()

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_operation_input_invalid"
    assert failed is not None and failed.status is AgentOperationStatus.FAILED
    assert failed.error_code == "agent_operation_input_invalid"
    assert reservations == 1
    assert gateway.provider_calls == calls_before == 1
    await engine.dispose()


@pytest.mark.anyio
async def test_corrupt_private_continuation_is_body_free_terminal_and_makes_zero_provider_io(
    tmp_path: Path,
    execution_module: ModuleType,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "PRIVATE-CONTINUATION-SENTINEL"
    corrupt_private = {
        "search_id": "private-search",
        "search_session": "results.aviasales.ru",
        "cursor": 0,
        "request_id": "private-request",
        "evidence_namespace": sentinel,
        "origin": "LED",
        "destination": "CDG",
        "departure_date": "2026-09-10",
        "return_date": None,
        "currency": "RUB",
        "passengers": 1,
        "poll_round": 1,
    }
    with pytest.raises(execution_module.AgentExecutionError) as invalid:
        execution_module._continuation_from_private(corrupt_private)
    rendered = "".join(traceback.format_exception(invalid.value))
    assert invalid.value.code == "agent_private_continuation_invalid"
    assert invalid.value.__cause__ is None
    assert invalid.value.__context__ is None
    assert sentinel not in str(invalid.value)
    assert sentinel not in repr(invalid.value)
    assert sentinel not in rendered

    invalid_host_sentinel = "PRIVATE-HOST-SENTINEL.invalid"
    invalid_host_private = {
        **corrupt_private,
        "search_session": invalid_host_sentinel,
        "evidence_namespace": str(uuid4()),
    }
    with pytest.raises(execution_module.AgentExecutionError) as invalid_host:
        execution_module._continuation_from_private(invalid_host_private)
    host_rendered = "".join(traceback.format_exception(invalid_host.value))
    assert invalid_host.value.code == "agent_private_continuation_invalid"
    assert invalid_host.value.__cause__ is None
    assert invalid_host.value.__context__ is None
    assert invalid_host_sentinel not in str(invalid_host.value)
    assert invalid_host_sentinel not in host_rendered

    engine, sessions = await _session_factory(tmp_path, "private-corrupt.db")
    await _seed_run(sessions, date_mode="exact")
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)
    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        operations = await AgentOperationRepository(session).list_operations(
            HOUSEHOLD_ID,
            RUN_ID,
        )
        poll = next(
            operation for operation in operations if operation.kind is AgentOperationKind.EXACT_POLL
        )
        await session.execute(
            update(agent_run_operations_table)
            .where(agent_run_operations_table.c.id == str(poll.id))
            .values(private_continuation_json=json.dumps(corrupt_private))
        )
        await session.commit()
        calls_before = gateway.provider_calls

        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        terminal = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, RUN_ID)
        failed_poll = await AgentOperationRepository(session).get_operation(
            HOUSEHOLD_ID,
            poll.id,
        )

    assert terminal is not None and terminal.status == "failed"
    assert terminal.error_code == "agent_private_continuation_invalid"
    assert failed_poll is not None and failed_poll.status is AgentOperationStatus.FAILED
    assert gateway.provider_calls == calls_before
    assert sentinel not in caplog.text
    await engine.dispose()


@pytest.mark.anyio
async def test_exact_poll_uses_private_passenger_binding_not_mutable_operation_input(
    tmp_path: Path,
    execution_module: ModuleType,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "private-passengers.db")
    await _seed_run(sessions, date_mode="exact", adults=2)
    clock = MutableClock()
    gateway = ResumableFakeGateway(clock)

    async with sessions() as session:
        service = _service(execution_module, session, gateway, clock)
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=RUN_ID)
        await session.commit()

    assert len(gateway.poll_calls) == 1
    assert gateway.poll_calls[0].passengers == 2
    assert gateway.poll_calls[0].evidence_namespace == gateway.start_calls[0].evidence_namespace
    await engine.dispose()


def _service(
    module: ModuleType,
    session: AsyncSession,
    gateway: ResumableFakeGateway,
    clock: MutableClock,
    *,
    circuit_failure_threshold: int = 5,
    circuit_cooldown_seconds: int = 120,
    durability_checkpoint: Callable[[], Awaitable[None]] | None = None,
    provider_preflight: Callable[[], None] | None = None,
    candidate_page_size: int = 100,
    poll_interval_seconds: int = 0,
    operation_lease_seconds: int = 60,
    provider_rpm: int = 20,
):
    return module.AgentExecutionService(
        session=session,
        gateway=gateway,
        worker_id="agent-worker-test",
        clock=clock,
        policy=module.AgentExecutionPolicy(
            provider_rpm=provider_rpm,
            operation_lease_seconds=operation_lease_seconds,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_cooldown_seconds=circuit_cooldown_seconds,
            circuit_probe_lease_seconds=30,
            candidate_page_size=candidate_page_size,
            poll_interval_seconds=poll_interval_seconds,
        ),
        durability_checkpoint=durability_checkpoint or session.commit,
        provider_preflight=provider_preflight,
    )


async def _run_until_terminal(
    service: object,
    session: AsyncSession,
    *,
    limit: int = 12,
    run_id: UUID = RUN_ID,
):
    for _ in range(limit):
        await service.run_step(household_id=HOUSEHOLD_ID, run_id=run_id)  # type: ignore[attr-defined]
        await session.commit()
        run = await AgentRunRepository(session).get_run(HOUSEHOLD_ID, run_id)
        assert run is not None
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            return run
    pytest.fail("agent run did not reach a terminal state within the bounded test steps")


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
    date_mode: Literal["exact", "flexible", "range", "rolling_90_days"],
    calendar_searches: int = 0,
    exact_searches: int = 1,
    logical_budget: int = 1,
    http_budget: int | None = None,
    deadline_seconds: int = 600,
    start_attempts: int = 3,
    poll_rounds: int = 3,
    attempts_per_poll: int = 2,
    adults: int = 1,
    children: int = 0,
    infants: int = 0,
    trip_shape: Literal["one_way", "round_trip", "open_jaw", "multi_city"] = "one_way",
    round_trip_return_date: str = "2026-09-20",
    return_tamper: Literal["none", "intent", "scope"] = "none",
    scope_variant: Literal[
        "singleton",
        "country",
        "city",
        "region",
        "anywhere",
        "nearby",
        "return_extra",
    ] = "singleton",
    requested_strategies: tuple[str, ...] = ("direct",),
    approved_strategies: tuple[str, ...] | None = None,
    analysis_modes: tuple[str, ...] = (),
    requests_per_minute: int = 20,
    coverage: Literal["quick", "full"] = "quick",
    anywhere_max_destination_seeds: int = 40,
    anywhere_exact_verification_limit: int = 20,
    anywhere_origin_airports: tuple[str, ...] = ("LED",),
) -> None:
    if logical_budget != calendar_searches + exact_searches:
        raise ValueError("test logical budget must match planned calendar + exact work")
    worst_case_exact_http_attempts = start_attempts + poll_rounds * attempts_per_poll
    expected_http_budget = (
        exact_searches * worst_case_exact_http_attempts + calendar_searches * start_attempts
    )
    if http_budget is None:
        http_budget = expected_http_budget
    end_date = (
        "2026-09-12"
        if date_mode == "range"
        else "2026-12-08"
        if date_mode == "rolling_90_days"
        else None
    )
    plan = {
        "coverage": coverage,
        "approval": {"generation": 1, "expires_at": (NOW + timedelta(hours=1)).isoformat()},
        "intent": {
            "origin_text": "LED",
            "destination_text": "CDG",
            "trip_shape": trip_shape,
            "date_mode": date_mode,
            "adults": adults,
            "children": children,
            "infants": infants,
            "currency": "RUB",
            "requested_strategies": list(requested_strategies),
            "preset_id": None,
            "analysis_modes": list(analysis_modes),
            "legs": [
                {
                    "origin": {"kind": "airport", "value": "LED"},
                    "destination": {"kind": "airport", "value": "CDG"},
                    "date_constraint": {
                        "mode": date_mode,
                        "start_date": "2026-09-10",
                        "end_date": end_date,
                        "flex_days": 2 if date_mode == "flexible" else 0,
                    },
                }
            ],
        },
        "clarifications": [],
    }
    if {"split_ticket", "self_transfer"}.intersection(requested_strategies):
        plan["composition"] = {
            "version": "confirmed-hubs-v1",
            "max_hubs_per_leg": 2,
            "source": "confirmed_connection_airports",
        }
    if "hidden_city" in requested_strategies:
        plan["hidden_city"] = {
            "version": "hidden-city-search-v1",
            "plan_leg_index": 0,
            "desired_airports": ["CDG"],
            "discovery": {
                "origin_airports": ["LED"],
                "date_start": "2026-09-10",
                "date_end": end_date or "2026-09-10",
                "allowed_country_codes": [],
                "excluded_country_codes": [],
                "discovery_source_ids": ["aviasales_hot_offers"],
                "max_destination_seeds": 4,
                "exact_verification_limit": 2,
                "catalog_checksum": "sha256:" + "a" * 64,
                "taxonomy_version": "v1",
                "eligible_destination_countries": [
                    {"code": "FCO", "country_code": "IT"},
                ],
            },
        }
    scope = {
        "coverage": coverage,
        "legs": [
            {
                "origin": {
                    "requested_scope": {"kind": "airport", "value": "LED"},
                    "airport_codes": ["LED"],
                    "catalog_checksum": "sha256:" + "a" * 64,
                    "taxonomy_version": "v1",
                    "commercial_provenance": "fixture",
                    "coverage": coverage,
                    "nearby_radius_km": 0,
                },
                "destination": {
                    "requested_scope": {"kind": "airport", "value": "CDG"},
                    "airport_codes": ["CDG"],
                    "catalog_checksum": "sha256:" + "a" * 64,
                    "taxonomy_version": "v1",
                    "commercial_provenance": "fixture",
                    "coverage": coverage,
                    "nearby_radius_km": 0,
                },
                "anywhere": None,
                "date_constraint": {
                    "mode": date_mode,
                    "start_date": "2026-09-10",
                    "end_date": end_date,
                    "flex_days": 2 if date_mode == "flexible" else 0,
                },
            }
        ],
    }
    first_intent_leg = plan["intent"]["legs"][0]
    first_scope_leg = scope["legs"][0]
    if scope_variant in {"country", "city", "region"}:
        requested_value = {
            "country": "FR",
            "city": "PAR",
            "region": "western-europe",
        }[scope_variant]
        airport_codes = {
            "country": ["CDG", "LYS", "NCE", "ORY"],
            "city": ["CDG", "ORY"],
            "region": ["AMS", "CDG", "FRA", "LHR"],
        }[scope_variant]
        first_intent_leg["destination"] = {
            "kind": scope_variant,
            "value": requested_value,
        }
        first_scope_leg["destination"]["requested_scope"] = {
            "kind": scope_variant,
            "value": requested_value,
        }
        first_scope_leg["destination"]["airport_codes"] = airport_codes
    elif scope_variant == "anywhere":
        first_intent_leg["destination"] = {"kind": "anywhere", "value": None}
        first_scope_leg["origin"]["airport_codes"] = list(anywhere_origin_airports)
        first_scope_leg["destination"] = None
        first_scope_leg["anywhere"] = {
            "origin_airports": list(anywhere_origin_airports),
            "date_start": "2026-09-10",
            "date_end": end_date or "2026-09-10",
            "allowed_country_codes": [],
            "excluded_country_codes": [],
            "discovery_source_ids": ["aviasales_hot_offers"],
            "max_destination_seeds": anywhere_max_destination_seeds,
            "exact_verification_limit": anywhere_exact_verification_limit,
            "catalog_checksum": "sha256:" + "a" * 64,
            "taxonomy_version": "v1",
            "eligible_destination_countries": {
                "CDG": "FR",
                "NCE": "FR",
                "ORY": "FR",
            },
        }
    elif scope_variant == "nearby":
        first_scope_leg["destination"]["nearby_radius_km"] = 100
        first_scope_leg["destination"]["airport_codes"] = ["CDG", "ORY"]
    if trip_shape != "one_way":
        intent_return_origin = "SVO" if return_tamper == "intent" else "CDG"
        scope_return_origin = "SVO" if return_tamper == "scope" else "CDG"
        plan["intent"]["legs"].append(
            {
                "origin": {"kind": "airport", "value": intent_return_origin},
                "destination": {"kind": "airport", "value": "LED"},
                "date_constraint": {
                    "mode": "exact",
                    "start_date": round_trip_return_date,
                    "end_date": None,
                    "flex_days": 0,
                },
            }
        )
        scope["legs"].append(
            {
                "origin": {
                    "requested_scope": {
                        "kind": "airport",
                        "value": scope_return_origin,
                    },
                    "airport_codes": [scope_return_origin],
                    "catalog_checksum": "sha256:" + "a" * 64,
                    "taxonomy_version": "v1",
                    "commercial_provenance": "fixture",
                    "coverage": coverage,
                    "nearby_radius_km": 0,
                },
                "destination": {
                    "requested_scope": {"kind": "airport", "value": "LED"},
                    "airport_codes": ["LED"],
                    "catalog_checksum": "sha256:" + "a" * 64,
                    "taxonomy_version": "v1",
                    "commercial_provenance": "fixture",
                    "coverage": coverage,
                    "nearby_radius_km": 0,
                },
                "anywhere": None,
                "date_constraint": {
                    "mode": "exact",
                    "start_date": round_trip_return_date,
                    "end_date": None,
                    "flex_days": 0,
                },
            }
        )
        if scope_variant == "return_extra":
            scope["legs"][1]["origin"]["airport_codes"] = ["CDG", "ORY"]
    async with sessions() as session:
        revision = await AgentPlanRepository(session).create_plan(
            NewAgentPlan(
                id=PLAN_ID,
                household_id=HOUSEHOLD_ID,
                created_by_user_id=USER_ID,
                created_at=NOW,
            ),
            NewAgentPlanRevision(
                id=REVISION_ID,
                state="awaiting_approval",
                plan=plan,
                scope_snapshot=scope,
                capability_snapshot={
                    "provider_id": "aviasales_search",
                    "version": "fixture-v1",
                    "one_way": "supported",
                    "round_trip": "supported",
                    "native_open_jaw": "unknown",
                    "native_multi_city": "unknown",
                    "explicit_connection_protection": "unknown",
                    "airport_location_semantics": "supported",
                    "city_location_semantics": "unknown",
                },
                cost_model_snapshot={
                    "version": "fixture-cost-v1",
                    "start_attempts": start_attempts,
                    "poll_rounds": poll_rounds,
                    "attempts_per_poll": attempts_per_poll,
                    "requests_per_minute": requests_per_minute,
                    "worst_case_exact_http_attempts": worst_case_exact_http_attempts,
                },
                parser_version="fixture-parser-v1",
                planner_version="fixture-planner-v1",
                estimated_calendar_searches=calendar_searches,
                estimated_exact_searches=exact_searches,
                estimated_logical_operations=logical_budget,
                estimated_http_attempts=http_budget,
                estimated_deadline_seconds=deadline_seconds,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            ),
        )
        approval = NewAgentPlanApproval(
            id=APPROVAL_ID,
            household_id=HOUSEHOLD_ID,
            revision_id=REVISION_ID,
            approved_by_user_id=USER_ID,
            approved_at=NOW,
            expires_at=NOW + timedelta(hours=1),
            snapshot=AgentPlanApprovalSnapshot(
                revision_content_hash=revision.content_hash,
                approved_by_session_id=SESSION_ID,
                approved_budget={
                    "calendar_searches": calendar_searches,
                    "exact_searches": exact_searches,
                    "logical_operations": logical_budget,
                    "http_attempts": http_budget,
                    "deadline_seconds": deadline_seconds,
                },
                approved_strategies=(
                    approved_strategies if approved_strategies is not None else requested_strategies
                ),
                risk_warning_versions=(
                    {"hidden_city": "hidden-city-v1"}
                    if "hidden_city"
                    in (
                        approved_strategies
                        if approved_strategies is not None
                        else requested_strategies
                    )
                    else {}
                ),
            ),
        )
        await AgentRunRepository(session).approve_and_execute(
            approval=approval,
            run=NewAgentPlanRun(
                id=RUN_ID,
                execute_idempotency_key=f"execute:{RUN_ID}",
                created_at=NOW,
                deadline_at=NOW + timedelta(seconds=deadline_seconds),
            ),
        )
        await session.commit()


def _signal(
    signal_id: UUID,
    departure_date: date,
    amount_minor: int,
    *,
    observed_at: datetime = NOW,
    return_date: date | None = None,
) -> DiscoverySignal:
    return DiscoverySignal(
        id=signal_id,
        provider_id="aviasales_search",
        origin="LED",
        destination="CDG",
        departure_date=departure_date,
        return_date=return_date,
        observed_amount=Money(amount_minor, "RUB"),
        observed_at=observed_at,
        source_kind=DiscoverySource.CALENDAR,
        passengers=1,
    )


def _complete_flexible_signals(
    *,
    return_date: date | None = None,
) -> tuple[DiscoverySignal, ...]:
    return tuple(
        _signal(
            uuid4(),
            date(2026, 9, day),
            10_000 + day,
            return_date=return_date,
        )
        for day in range(8, 13)
    )


def _calendar_signal_id(namespace: UUID, signal: DiscoverySignal) -> UUID:
    identity = "|".join(
        (
            "aviasales_search",
            "calendar",
            signal.origin,
            signal.destination,
            signal.departure_date.isoformat(),
            signal.return_date.isoformat() if signal.return_date is not None else "",
            str(signal.observed_amount.minor_units),
            signal.observed_amount.currency,
        )
    )
    return uuid5(namespace, f"discovery|{identity}")


def _anywhere_signal_id(namespace: UUID, signal: DiscoverySignal) -> UUID:
    identity = "|".join(
        (
            "aviasales_search",
            "hot_offer",
            signal.origin,
            signal.destination,
            signal.departure_date.isoformat(),
            signal.return_date.isoformat() if signal.return_date is not None else "",
            str(signal.observed_amount.minor_units),
            signal.observed_amount.currency,
            str(signal.passengers),
        )
    )
    return uuid5(namespace, f"discovery|{identity}")


def _stored_evidence(
    evidence: ConfirmedOfferEvidence,
    *,
    stage_id: UUID,
) -> NewAgentConfirmedOfferEvidence:
    return NewAgentConfirmedOfferEvidence(
        id=evidence.id,
        household_id=HOUSEHOLD_ID,
        run_id=RUN_ID,
        stage_id=stage_id,
        provider_id=evidence.provider_id,
        source="exact_search",
        observed_at=evidence.observed_at,
        freshness=Freshness.LIVE,
        passengers=evidence.passengers,
        passenger_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
        amount_minor=evidence.total_amount.minor_units,
        currency=evidence.total_amount.currency,
        itinerary_evidence={
            "origin": evidence.origin,
            "destination": evidence.destination,
            "segments": [
                {
                    "origin": segment.origin,
                    "destination": segment.destination,
                    "depart_at": segment.depart_at,
                    "arrive_at": segment.arrive_at,
                    "carrier": segment.airline_code,
                    "flight_number": segment.flight_number,
                }
                for segment in evidence.segments
            ],
            "seller": evidence.seller_name,
            "ticket_structure": "provider_ticket",
            "stops": max(0, len(evidence.segments) - 1),
        },
        protection_status=evidence.protection_status,
        baggage_status=None,
        transfer_status=None,
        visa_status=None,
        fingerprint="sha256:" + hashlib.sha256(str(evidence.id).encode("ascii")).hexdigest(),
        created_at=evidence.observed_at,
    )
