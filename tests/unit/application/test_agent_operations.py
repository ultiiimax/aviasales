from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

import flight_hunter.persistence.agent_repositories as agent_repository_types
from flight_hunter.application.agent_operations import (
    CircuitPermitStatus,
    OperationSpec,
    ProviderFailureClass,
    canonical_json,
    logical_workflow_fingerprint,
    operation_fingerprint,
    retry_decision,
)
from flight_hunter.persistence.agent_repositories import (
    AgentOperationKind,
    AgentOperationStatus,
    CircuitPermitResult,
    NewAgentRunOperation,
)

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
    with pytest.raises(ValueError, match="passengers"):
        operation_fingerprint(
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


def test_review_network_and_server_retry_use_bounded_jitter_without_lowering_retry_after() -> None:
    low = retry_decision(
        failure_class=ProviderFailureClass.NETWORK,
        attempt_count=3,
        max_attempts=8,
        now=NOW,
        jitter_source=lambda: 0.0,
    )
    middle = retry_decision(
        failure_class=ProviderFailureClass.SERVER,
        attempt_count=3,
        max_attempts=8,
        now=NOW,
        jitter_source=lambda: 0.5,
    )
    high = retry_decision(
        failure_class=ProviderFailureClass.NETWORK,
        attempt_count=3,
        max_attempts=8,
        now=NOW,
        jitter_source=lambda: 1.0,
    )
    capped = retry_decision(
        failure_class=ProviderFailureClass.SERVER,
        attempt_count=7,
        max_attempts=8,
        now=NOW,
        jitter_source=lambda: 1.0,
    )
    retry_after = NOW + timedelta(seconds=47)
    limited = retry_decision(
        failure_class=ProviderFailureClass.RATE_LIMITED,
        attempt_count=1,
        max_attempts=8,
        now=NOW,
        retry_after=retry_after,
        jitter_source=lambda: (_ for _ in ()).throw(AssertionError("jitter must not run")),
    )

    assert low.next_retry_at == NOW + timedelta(seconds=16)
    assert middle.next_retry_at == NOW + timedelta(seconds=20)
    assert high.next_retry_at == NOW + timedelta(seconds=24)
    assert capped.next_retry_at == NOW + timedelta(seconds=300)
    assert limited.next_retry_at == retry_after


@pytest.mark.parametrize("sample", [-0.01, 1.01, math.nan])
def test_review_retry_jitter_rejects_out_of_range_or_non_finite_samples(sample: float) -> None:
    with pytest.raises(ValueError, match="jitter"):
        retry_decision(
            failure_class=ProviderFailureClass.NETWORK,
            attempt_count=1,
            max_attempts=3,
            now=NOW,
            jitter_source=lambda: sample,
        )


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


def test_review_circuit_permit_result_enforces_status_specific_shape() -> None:
    permit_type = agent_repository_types.ServerPrivateCircuitPermit
    mode_type = agent_repository_types.CircuitPermitMode
    permit = permit_type(
        provider_id="aviasales_search",
        operation_id=UUID("77777777-7777-7777-7777-777777777777"),
        operation_attempt_number=1,
        generation=4,
        mode=mode_type.CLOSED,
        token="permit-super-secret",
        expires_at=NOW + timedelta(seconds=30),
    )

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
            CircuitPermitResult(
                status,
                retry_at=NOW + timedelta(seconds=1),
                permit=permit,
            )
        with pytest.raises(ValueError, match="requires permit"):
            CircuitPermitResult(status)

    allowed = CircuitPermitResult(CircuitPermitStatus.ALLOWED, permit=permit)
    assert allowed.permit == permit
    assert "permit-super-secret" not in repr(permit)
    assert "permit-super-secret" not in repr(allowed)


def test_review_private_operation_dtos_do_not_leak_continuation_in_repr() -> None:
    operation_id = UUID("77777777-7777-7777-7777-777777777777")
    common = {
        "id": operation_id,
        "household_id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "run_id": UUID("55555555-5555-5555-5555-555555555555"),
        "stage_id": UUID("66666666-6666-6666-6666-666666666666"),
        "provider_id": "aviasales_search",
        "kind": AgentOperationKind.EXACT_START,
        "immutable_input": {"origin": "LED", "destination": "CDG"},
        "private_continuation": {"search_session": "opaque-private-state"},
        "max_attempts": 3,
        "created_at": NOW,
    }
    spec = OperationSpec(
        **common,
        logical_workflow_input={"origin": "LED", "destination": "CDG"},
        consumes_logical_unit=True,
    )
    stored = NewAgentRunOperation(
        **common,
        operation_fingerprint="sha256:" + "a" * 64,
        logical_operation_fingerprint="sha256:" + "b" * 64,
        consumes_logical_unit=True,
    )

    assert "opaque-private-state" not in repr(spec)
    assert "opaque-private-state" not in repr(stored)
    assert "private_continuation=" not in repr(spec)
    assert "private_continuation=" not in repr(stored)

    mutated = replace(spec, private_continuation={"search_id": "another-private-value"})
    assert "another-private-value" not in repr(mutated)
