from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from flight_hunter.application.agent_operations import (
    AgentProviderCircuitBreaker,
    CircuitPermitStatus,
    ProviderFailureClass,
    canonical_json,
    logical_workflow_fingerprint,
    operation_fingerprint,
    retry_decision,
)
from flight_hunter.persistence.agent_repositories import (
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationStatus,
    CircuitPermitResult,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import mapper_registry

NOW = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)


def test_operation_fingerprint_is_stable_across_mapping_order() -> None:
    first = operation_fingerprint(
        AgentOperationKind.EXACT_START,
        {
            "origin": "LED",
            "destination": "CDG",
            "passengers": {"adults": 1, "children": 0},
        },
    )
    second = operation_fingerprint(
        AgentOperationKind.EXACT_START,
        {
            "passengers": {"children": 0, "adults": 1},
            "destination": "CDG",
            "origin": "LED",
        },
    )

    assert first == second
    assert first.startswith("sha256:")


def test_fingerprint_changes_with_operation_kind_or_typed_immutable_input() -> None:
    base = operation_fingerprint(
        AgentOperationKind.EXACT_START,
        {"origin": "LED", "destination": "CDG", "passengers": 1},
    )

    assert base != operation_fingerprint(
        AgentOperationKind.EXACT_POLL,
        {"origin": "LED", "destination": "CDG", "passengers": 1},
    )
    assert base != operation_fingerprint(
        AgentOperationKind.EXACT_START,
        {"origin": "LED", "destination": "CDG", "passengers": 2},
    )
    assert base != operation_fingerprint(
        AgentOperationKind.EXACT_START,
        {"origin": "LED", "destination": "CDG", "passengers": "1"},
    )


def test_start_and_poll_can_share_a_separate_logical_workflow_fingerprint() -> None:
    workflow = {"origin": "LED", "destination": "CDG", "date": "2026-09-01"}

    logical = logical_workflow_fingerprint("exact_search", workflow)
    start = operation_fingerprint(AgentOperationKind.EXACT_START, {**workflow, "phase": "start"})
    poll = operation_fingerprint(
        AgentOperationKind.EXACT_POLL,
        {**workflow, "phase": "poll", "round": 1},
    )

    assert start != poll
    assert logical == logical_workflow_fingerprint(
        "exact_search", {"date": "2026-09-01", "destination": "CDG", "origin": "LED"}
    )


def test_canonical_json_is_deterministic_and_rejects_non_json_or_secret_payloads() -> None:
    assert canonical_json({"b": [2, {"z": None, "a": True}], "a": 1}) == (
        '{"a":1,"b":[2,{"a":true,"z":null}]}'
    )
    with pytest.raises(ValueError, match="unsafe field"):
        canonical_json({"safe": [{"authorization": "Bearer secret"}]})
    with pytest.raises(ValueError, match="unsafe field"):
        canonical_json({"raw_provider_response": {"price": 1}})
    with pytest.raises(ValueError, match="unsafe field"):
        canonical_json({"nested": {"signed_url": "https://example.test/signed"}})
    with pytest.raises(TypeError, match="JSON"):
        canonical_json({"opaque": object()})
    with pytest.raises(ValueError, match="finite"):
        canonical_json({"score": float("nan")})
    assert canonical_json({"note": "HTTPS protocol metadata, not a URL"}) == (
        '{"note":"HTTPS protocol metadata, not a URL"}'
    )


@pytest.mark.parametrize(
    "failure_class",
    [
        ProviderFailureClass.AUTH,
        ProviderFailureClass.FORBIDDEN,
        ProviderFailureClass.SCHEMA,
    ],
)
def test_auth_forbidden_and_schema_failures_are_terminal(
    failure_class: ProviderFailureClass,
) -> None:
    decision = retry_decision(
        failure_class=failure_class,
        attempt_count=1,
        max_attempts=5,
        now=NOW,
    )

    assert decision.status is AgentOperationStatus.FAILED
    assert decision.next_retry_at is None
    assert decision.error_code == f"provider_{failure_class.value}"


def test_429_uses_retry_after_and_network_or_5xx_retry_is_bounded() -> None:
    retry_at = NOW + timedelta(seconds=47)
    limited = retry_decision(
        failure_class=ProviderFailureClass.RATE_LIMITED,
        attempt_count=1,
        max_attempts=3,
        now=NOW,
        retry_after=retry_at,
    )
    network = retry_decision(
        failure_class=ProviderFailureClass.NETWORK,
        attempt_count=1,
        max_attempts=3,
        now=NOW,
    )
    server_exhausted = retry_decision(
        failure_class=ProviderFailureClass.SERVER,
        attempt_count=3,
        max_attempts=3,
        now=NOW,
    )

    assert limited.status is AgentOperationStatus.RETRY_WAIT
    assert limited.next_retry_at == retry_at
    assert network.status is AgentOperationStatus.RETRY_WAIT
    assert network.next_retry_at is not None and network.next_retry_at > NOW
    assert server_exhausted.status is AgentOperationStatus.FAILED
    assert server_exhausted.next_retry_at is None


@pytest.mark.parametrize(
    ("attempt_count", "max_attempts"),
    [(0, 3), (4, 3), (1, 0), (True, 3)],
)
def test_retry_decision_rejects_invalid_attempt_bounds(
    attempt_count: int,
    max_attempts: int,
) -> None:
    with pytest.raises(ValueError, match="attempt"):
        retry_decision(
            failure_class=ProviderFailureClass.NETWORK,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            now=NOW,
        )


def test_retry_decision_rejects_naive_now_or_retry_after() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        retry_decision(
            failure_class=ProviderFailureClass.NETWORK,
            attempt_count=1,
            max_attempts=3,
            now=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        retry_decision(
            failure_class=ProviderFailureClass.RATE_LIMITED,
            attempt_count=1,
            max_attempts=3,
            now=NOW,
            retry_after=NOW.replace(tzinfo=None),
        )


def test_circuit_permit_result_enforces_status_specific_retry_time() -> None:
    with pytest.raises(ValueError, match="requires retry_at"):
        CircuitPermitResult(CircuitPermitStatus.OPEN)
    with pytest.raises(ValueError, match="timezone-aware"):
        CircuitPermitResult(
            CircuitPermitStatus.OPEN,
            retry_at=NOW.replace(tzinfo=None),
        )
    for status in (
        CircuitPermitStatus.ALLOWED,
        CircuitPermitStatus.HALF_OPEN_PROBE,
    ):
        with pytest.raises(ValueError, match="only valid"):
            CircuitPermitResult(status, retry_at=NOW + timedelta(seconds=1))


@pytest.mark.anyio
async def test_persistent_circuit_survives_service_instance_and_denies_while_open(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-persistence.db")

    async with sessions() as session:
        circuit = _circuit(session)
        assert (
            await circuit.before_attempt("aviasales_search", "worker-a", NOW)
        ).status is CircuitPermitStatus.ALLOWED
        await circuit.record_failure("aviasales_search", ProviderFailureClass.NETWORK, NOW)
        opened = await circuit.record_failure(
            "aviasales_search", ProviderFailureClass.SERVER, NOW + timedelta(seconds=1)
        )
        await session.commit()
        assert opened.state.value == "open"

    async with sessions() as session:
        fresh_instance = _circuit(session)
        denied = await fresh_instance.before_attempt(
            "aviasales_search", "worker-b", NOW + timedelta(seconds=30)
        )
        assert denied.status is CircuitPermitStatus.OPEN
        assert denied.retry_at == NOW + timedelta(seconds=61)

    await engine.dispose()


@pytest.mark.anyio
async def test_after_cooldown_only_one_concurrent_half_open_probe_is_admitted(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-half-open.db")
    async with sessions() as session:
        circuit = _circuit(session)
        await circuit.record_failure("aviasales_search", ProviderFailureClass.NETWORK, NOW)
        await circuit.record_failure(
            "aviasales_search", ProviderFailureClass.SERVER, NOW + timedelta(seconds=1)
        )
        await session.commit()

    ready = 0
    ready_lock = asyncio.Lock()
    start = asyncio.Event()

    async def probe(worker_id: str) -> CircuitPermitStatus:
        nonlocal ready
        async with sessions() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            permit = await _circuit(session).before_attempt(
                "aviasales_search",
                worker_id,
                NOW + timedelta(seconds=62),
            )
            await session.commit()
            return permit.status

    statuses = await asyncio.gather(probe("worker-a"), probe("worker-b"))

    assert sorted(statuses, key=str) == sorted(
        [CircuitPermitStatus.HALF_OPEN_PROBE, CircuitPermitStatus.OPEN],
        key=str,
    )
    await engine.dispose()


@pytest.mark.anyio
async def test_successful_half_open_probe_closes_and_resets_circuit(tmp_path: Path) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-success.db")
    async with sessions() as session:
        circuit = _circuit(session)
        await circuit.record_failure("aviasales_search", ProviderFailureClass.NETWORK, NOW)
        await circuit.record_failure(
            "aviasales_search", ProviderFailureClass.SERVER, NOW + timedelta(seconds=1)
        )
        probe = await circuit.before_attempt(
            "aviasales_search", "worker-a", NOW + timedelta(seconds=62)
        )
        assert probe.status is CircuitPermitStatus.HALF_OPEN_PROBE
        closed = await circuit.record_success(
            "aviasales_search", "worker-a", NOW + timedelta(seconds=63)
        )
        await session.commit()

        assert closed.state.value == "closed"
        assert closed.consecutive_transient_failures == 0
        assert closed.half_open_probe_owner is None

    async with sessions() as session:
        permit = await _circuit(session).before_attempt(
            "aviasales_search", "worker-b", NOW + timedelta(seconds=64)
        )
        assert permit.status is CircuitPermitStatus.ALLOWED

    await engine.dispose()


@pytest.mark.anyio
async def test_terminal_failure_does_not_increment_transient_circuit_counter(
    tmp_path: Path,
) -> None:
    engine, sessions = await _session_factory(tmp_path, "circuit-terminal.db")
    async with sessions() as session:
        circuit = _circuit(session)
        state = await circuit.record_failure("aviasales_search", ProviderFailureClass.AUTH, NOW)
        await session.commit()

        assert state.state.value == "closed"
        assert state.consecutive_transient_failures == 0

    await engine.dispose()


async def _session_factory(
    tmp_path: Path,
    filename: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_database_engine(f"sqlite+aiosqlite:///{(tmp_path / filename).as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _circuit(session: AsyncSession) -> AgentProviderCircuitBreaker:
    return AgentProviderCircuitBreaker(
        AgentOperationRepository(session),
        transient_failure_threshold=2,
        cooldown_seconds=60,
        probe_lease_seconds=30,
    )
