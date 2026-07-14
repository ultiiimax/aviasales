from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from flight_hunter.persistence.agent_repositories import (
    AgentCircuitStateRecord,
    AgentOperationKind,
    AgentOperationRepository,
    AgentOperationResultType,
    AgentOperationStatus,
    AgentRunOperationRecord,
    CircuitPermitResult,
    CircuitPermitStatus,
    NewAgentRunOperation,
    canonical_sanitized_json,
)


class ProviderFailureClass(StrEnum):
    AUTH = "auth"
    FORBIDDEN = "forbidden"
    SCHEMA = "schema"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    SERVER = "server"


@dataclass(frozen=True, slots=True)
class OperationSpec:
    id: UUID
    household_id: UUID
    run_id: UUID
    stage_id: UUID
    provider_id: str | None
    kind: AgentOperationKind
    immutable_input: Mapping[str, object]
    logical_workflow_input: Mapping[str, object]
    consumes_logical_unit: bool
    private_continuation: Mapping[str, object] | None
    max_attempts: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RetryDecision:
    status: AgentOperationStatus
    next_retry_at: datetime | None
    error_code: str


def canonical_json(value: Mapping[str, object]) -> str:
    return canonical_sanitized_json(value)


def operation_fingerprint(
    operation_kind: AgentOperationKind | str,
    immutable_input: Mapping[str, object],
) -> str:
    kind = AgentOperationKind(operation_kind)
    return _sha256_fingerprint(
        {
            "operation_kind": kind.value,
            "immutable_input": immutable_input,
        }
    )


def logical_workflow_fingerprint(
    workflow_kind: str,
    immutable_input: Mapping[str, object],
) -> str:
    if not isinstance(workflow_kind, str) or not workflow_kind.strip():
        raise ValueError("workflow_kind must not be blank")
    return _sha256_fingerprint(
        {
            "workflow_kind": workflow_kind.strip(),
            "immutable_input": immutable_input,
        }
    )


def retry_decision(
    *,
    failure_class: ProviderFailureClass | str,
    attempt_count: int,
    max_attempts: int,
    now: datetime,
    retry_after: datetime | None = None,
) -> RetryDecision:
    _require_aware(now, "now")
    if type(attempt_count) is not int or attempt_count < 1:
        raise ValueError("attempt_count must be a positive integer")
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if attempt_count > max_attempts:
        raise ValueError("attempt_count cannot exceed max_attempts")
    classification = ProviderFailureClass(failure_class)
    error_code = f"provider_{classification.value}"
    if classification in {
        ProviderFailureClass.AUTH,
        ProviderFailureClass.FORBIDDEN,
        ProviderFailureClass.SCHEMA,
    }:
        return RetryDecision(AgentOperationStatus.FAILED, None, error_code)
    if attempt_count >= max_attempts:
        return RetryDecision(AgentOperationStatus.FAILED, None, error_code)
    if classification is ProviderFailureClass.RATE_LIMITED:
        if retry_after is None:
            raise ValueError("rate_limited failure requires retry_after")
        _require_aware(retry_after, "retry_after")
        if retry_after <= now:
            raise ValueError("retry_after must be after now")
        return RetryDecision(AgentOperationStatus.RETRY_WAIT, retry_after, error_code)
    delay_seconds = min(300, 5 * (2 ** (attempt_count - 1)))
    return RetryDecision(
        AgentOperationStatus.RETRY_WAIT,
        now + timedelta(seconds=delay_seconds),
        error_code,
    )


class OperationScheduler:
    def __init__(self, repository: AgentOperationRepository) -> None:
        self._repository = repository

    async def materialize(self, spec: OperationSpec) -> AgentRunOperationRecord:
        workflow_kind = (
            "exact_search"
            if spec.kind in {AgentOperationKind.EXACT_START, AgentOperationKind.EXACT_POLL}
            else spec.kind.value
        )
        return await self._repository.materialize_operation(
            NewAgentRunOperation(
                id=spec.id,
                household_id=spec.household_id,
                run_id=spec.run_id,
                stage_id=spec.stage_id,
                provider_id=spec.provider_id,
                kind=spec.kind,
                operation_fingerprint=operation_fingerprint(
                    spec.kind,
                    spec.immutable_input,
                ),
                logical_operation_fingerprint=logical_workflow_fingerprint(
                    workflow_kind,
                    spec.logical_workflow_input,
                ),
                consumes_logical_unit=spec.consumes_logical_unit,
                immutable_input=spec.immutable_input,
                private_continuation=spec.private_continuation,
                max_attempts=spec.max_attempts,
                created_at=spec.created_at,
            )
        )

    async def record_failure(
        self,
        *,
        household_id: UUID,
        operation: AgentRunOperationRecord,
        worker_id: str,
        failure_class: ProviderFailureClass,
        now: datetime,
        retry_after: datetime | None = None,
    ) -> AgentRunOperationRecord:
        decision = retry_decision(
            failure_class=failure_class,
            attempt_count=operation.attempt_count,
            max_attempts=operation.max_attempts,
            now=now,
            retry_after=retry_after,
        )
        if decision.status is AgentOperationStatus.RETRY_WAIT:
            assert decision.next_retry_at is not None
            return await self._repository.schedule_retry(
                household_id=household_id,
                operation_id=operation.id,
                worker_id=worker_id,
                next_retry_at=decision.next_retry_at,
                error_code=decision.error_code,
                now=now,
            )
        return await self._repository.mark_operation_failed(
            household_id=household_id,
            operation_id=operation.id,
            worker_id=worker_id,
            error_code=decision.error_code,
            now=now,
        )

    async def record_success(
        self,
        *,
        household_id: UUID,
        operation_id: UUID,
        worker_id: str,
        result_type: AgentOperationResultType,
        result_id: UUID,
        now: datetime,
    ) -> AgentRunOperationRecord:
        return await self._repository.mark_operation_succeeded(
            household_id=household_id,
            operation_id=operation_id,
            worker_id=worker_id,
            result_type=result_type,
            result_id=result_id,
            now=now,
        )


class AgentProviderCircuitBreaker:
    def __init__(
        self,
        repository: AgentOperationRepository,
        *,
        transient_failure_threshold: int,
        cooldown_seconds: int,
        probe_lease_seconds: int,
    ) -> None:
        values = (
            transient_failure_threshold,
            cooldown_seconds,
            probe_lease_seconds,
        )
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("circuit policy values must be positive integers")
        self._repository = repository
        self._transient_failure_threshold = transient_failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._probe_lease_seconds = probe_lease_seconds

    async def before_attempt(
        self,
        provider_id: str,
        worker_id: str,
        now: datetime,
    ) -> CircuitPermitResult:
        return await self._repository.acquire_circuit_permit(
            provider_id=provider_id,
            worker_id=worker_id,
            now=now,
            probe_lease_seconds=self._probe_lease_seconds,
        )

    async def record_failure(
        self,
        provider_id: str,
        failure_class: ProviderFailureClass | str,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        classification = ProviderFailureClass(failure_class)
        return await self._repository.record_circuit_failure(
            provider_id=provider_id,
            transient=classification in {ProviderFailureClass.NETWORK, ProviderFailureClass.SERVER},
            failure_threshold=self._transient_failure_threshold,
            cooldown_seconds=self._cooldown_seconds,
            now=now,
        )

    async def record_success(
        self,
        provider_id: str,
        worker_id: str,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        return await self._repository.record_circuit_success(
            provider_id=provider_id,
            worker_id=worker_id,
            now=now,
        )


def _sha256_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = canonical_json(payload).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = [
    "AgentProviderCircuitBreaker",
    "CircuitPermitStatus",
    "OperationScheduler",
    "OperationSpec",
    "ProviderFailureClass",
    "RetryDecision",
    "canonical_json",
    "logical_workflow_fingerprint",
    "operation_fingerprint",
    "retry_decision",
]
