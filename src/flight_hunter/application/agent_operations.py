from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from flight_hunter.application.agent_scope import finite_route_pairs
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
    ServerPrivateCircuitPermit,
    canonical_operation_input_json,
    canonical_sanitized_json,
)


class ProviderFailureClass(StrEnum):
    AUTH = "auth"
    FORBIDDEN = "forbidden"
    SCHEMA = "schema"
    RATE_LIMITED = "rate_limited"
    NETWORK = "network"
    SERVER = "server"


class CoveragePairStatus(StrEnum):
    PLANNED = "planned"
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True, order=True)
class CoveragePair:
    origin: str
    destination: str
    departure_date: date
    return_date: date | None

    def __post_init__(self) -> None:
        origin = self.origin.strip().upper()
        destination = self.destination.strip().upper()
        if not re.fullmatch(r"^[A-Z]{3}$", origin):
            raise ValueError("coverage origin must be an IATA code")
        if not re.fullmatch(r"^[A-Z]{3}$", destination):
            raise ValueError("coverage destination must be an IATA code")
        if type(self.departure_date) is not date:
            raise TypeError("coverage departure_date must be a date")
        if self.return_date is not None:
            if type(self.return_date) is not date:
                raise TypeError("coverage return_date must be a date or None")
            if self.return_date < self.departure_date:
                raise ValueError("coverage return_date cannot precede departure_date")
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "destination", destination)


@dataclass(frozen=True, slots=True)
class CoveragePairOutcome:
    status: CoveragePairStatus | str
    reason: str | None = None

    def __post_init__(self) -> None:
        status = CoveragePairStatus(self.status)
        if status is CoveragePairStatus.PLANNED:
            raise ValueError("planned is derived from an absent coverage outcome")
        reason = self.reason
        if reason is not None and not re.fullmatch(r"^[a-z][a-z0-9_]{2,79}$", reason):
            raise ValueError("coverage reason must be a stable machine-readable code")
        if status in {CoveragePairStatus.FAILED, CoveragePairStatus.SKIPPED}:
            if reason is None:
                raise ValueError("failed or skipped coverage outcome requires a reason")
        elif reason is not None:
            raise ValueError("coverage reason is only valid for failed or skipped outcomes")
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class FrozenCoverageInput:
    coverage: str
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    date_start: date
    date_end: date
    catalog_checksums: tuple[str, ...]
    taxonomy_versions: tuple[str, ...]
    return_date: date | None = None
    explicit_pairs: tuple[CoveragePair, ...] = ()

    def __post_init__(self) -> None:
        if self.coverage not in {"quick", "full"}:
            raise ValueError("coverage must be quick or full")
        origins = _coverage_iata_tuple(self.origins, "origins")
        destinations = _coverage_iata_tuple(self.destinations, "destinations")
        if type(self.date_start) is not date or type(self.date_end) is not date:
            raise TypeError("coverage date bounds must be dates")
        if self.date_end < self.date_start:
            raise ValueError("coverage date_end cannot precede date_start")
        if self.return_date is not None:
            if type(self.return_date) is not date:
                raise TypeError("coverage return_date must be a date or None")
            if self.return_date < self.date_end:
                raise ValueError("coverage return_date cannot precede the departure surface")
        checksums = _stable_text_tuple(self.catalog_checksums, "catalog_checksums")
        versions = _stable_text_tuple(self.taxonomy_versions, "taxonomy_versions")
        explicit_pairs = tuple(self.explicit_pairs)
        if not all(isinstance(pair, CoveragePair) for pair in explicit_pairs):
            raise TypeError("explicit_pairs must contain CoveragePair values")
        if len(explicit_pairs) != len(set(explicit_pairs)):
            raise ValueError("explicit_pairs must be unique")
        if any(
            pair.origin not in origins
            or pair.destination not in destinations
            or pair.origin == pair.destination
            or not self.date_start <= pair.departure_date <= self.date_end
            or pair.return_date != self.return_date
            for pair in explicit_pairs
        ):
            raise ValueError("explicit coverage pair is outside frozen input")
        object.__setattr__(self, "origins", origins)
        object.__setattr__(self, "destinations", destinations)
        object.__setattr__(self, "catalog_checksums", checksums)
        object.__setattr__(self, "taxonomy_versions", versions)
        object.__setattr__(self, "explicit_pairs", explicit_pairs)


@dataclass(frozen=True, slots=True)
class CoveragePairResult:
    pair: CoveragePair
    status: CoveragePairStatus
    reason: str | None


@dataclass(frozen=True, slots=True)
class CoverageReport:
    frozen_input: FrozenCoverageInput
    coverage: str
    completion: str
    planned: int
    attempted: int
    succeeded: int
    failed: int
    skipped: int
    pairs: tuple[CoveragePairResult, ...]
    reason_counts: Mapping[str, int]


def build_coverage_report(
    *,
    frozen_input: FrozenCoverageInput,
    planned_pairs: tuple[CoveragePair, ...],
    outcomes: Mapping[CoveragePair, CoveragePairOutcome],
) -> CoverageReport:
    if not isinstance(frozen_input, FrozenCoverageInput):
        raise TypeError("frozen_input must be FrozenCoverageInput")
    planned = tuple(planned_pairs)
    if not planned or not all(isinstance(pair, CoveragePair) for pair in planned):
        raise ValueError("planned_pairs must contain at least one CoveragePair")
    if len(set(planned)) != len(planned):
        raise ValueError("planned coverage pairs must be unique")
    expected = _expected_coverage_pairs(frozen_input)
    planned_set = set(planned)
    if not all(_pair_is_in_frozen_input(pair, frozen_input) for pair in planned):
        raise ValueError("planned coverage pair is outside frozen input")
    if not set(outcomes).issubset(planned_set):
        raise ValueError("unapproved coverage pair outcome")
    complete_plan = planned + tuple(pair for pair in expected if pair not in planned_set)
    results = tuple(
        CoveragePairResult(
            pair=pair,
            status=(
                CoveragePairStatus(outcomes[pair].status)
                if pair in outcomes
                else CoveragePairStatus.PLANNED
            ),
            reason=(
                outcomes[pair].reason
                if pair in outcomes
                else "agent_pair_not_attempted"
                if pair in planned_set
                else "agent_pair_not_planned"
            ),
        )
        for pair in complete_plan
    )
    attempted = sum(
        result.status
        in {
            CoveragePairStatus.ATTEMPTED,
            CoveragePairStatus.SUCCEEDED,
            CoveragePairStatus.FAILED,
        }
        for result in results
    )
    succeeded = sum(result.status is CoveragePairStatus.SUCCEEDED for result in results)
    failed = sum(result.status is CoveragePairStatus.FAILED for result in results)
    skipped = sum(result.status is CoveragePairStatus.SKIPPED for result in results)
    if succeeded == len(results):
        completion = "full" if frozen_input.coverage == "full" else "complete"
    elif not outcomes:
        completion = "pending"
    else:
        completion = "partial"
    reasons = Counter(result.reason for result in results if result.reason is not None)
    return CoverageReport(
        frozen_input=frozen_input,
        coverage=frozen_input.coverage,
        completion=completion,
        planned=len(results),
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
        pairs=results,
        reason_counts=dict(sorted(reasons.items())),
    )


def _coverage_iata_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an ordered collection")
    normalized = tuple(value.strip().upper() for value in values)
    if not normalized or any(not re.fullmatch(r"^[A-Z]{3}$", value) for value in normalized):
        raise ValueError(f"{field_name} must contain IATA codes")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must contain unique IATA codes")
    return normalized


def _stable_text_tuple(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{field_name} must be an ordered collection")
    normalized = tuple(dict.fromkeys(value.strip() for value in values))
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"{field_name} must contain stable values")
    return normalized


def _pair_is_in_frozen_input(pair: CoveragePair, frozen: FrozenCoverageInput) -> bool:
    if frozen.explicit_pairs:
        return pair in frozen.explicit_pairs
    return (
        (pair.origin, pair.destination)
        in set(finite_route_pairs(frozen.origins, frozen.destinations))
        and frozen.date_start <= pair.departure_date <= frozen.date_end
        and pair.return_date == frozen.return_date
    )


def _expected_coverage_pairs(frozen: FrozenCoverageInput) -> tuple[CoveragePair, ...]:
    if frozen.explicit_pairs:
        return frozen.explicit_pairs
    return tuple(
        CoveragePair(origin, destination, departure_date, frozen.return_date)
        for origin, destination in finite_route_pairs(frozen.origins, frozen.destinations)
        for departure_date in (
            frozen.date_start + timedelta(days=offset)
            for offset in range((frozen.date_end - frozen.date_start).days + 1)
        )
    )


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
    private_continuation: Mapping[str, object] | None = field(repr=False)
    max_attempts: int
    created_at: datetime
    logical_root_operation_id: UUID | None = None


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
    canonical_operation_input_json(immutable_input)
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
    canonical_operation_input_json(immutable_input)
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
    jitter_source: Callable[[], float] = random.random,
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
    sample = jitter_source()
    if isinstance(sample, bool) or not isinstance(sample, (int, float)):
        raise ValueError("jitter source must return a finite number from 0 to 1")
    normalized_sample = float(sample)
    if not 0.0 <= normalized_sample <= 1.0 or not math.isfinite(normalized_sample):
        raise ValueError("jitter source must return a finite number from 0 to 1")
    base_delay_seconds = min(300, 5 * (2 ** min(attempt_count - 1, 6)))
    delay_seconds = min(
        300,
        max(1, round(base_delay_seconds * (0.8 + (0.4 * normalized_sample)))),
    )
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
                logical_root_operation_id=spec.logical_root_operation_id,
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
        *,
        household_id: UUID,
        run_id: UUID,
        operation_id: UUID,
        provider_id: str,
        worker_id: str,
        now: datetime,
    ) -> CircuitPermitResult:
        return await self._repository.acquire_circuit_permit(
            household_id=household_id,
            run_id=run_id,
            operation_id=operation_id,
            provider_id=provider_id,
            worker_id=worker_id,
            now=now,
            probe_lease_seconds=self._probe_lease_seconds,
        )

    async def record_failure(
        self,
        *,
        circuit_permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        failure_class: ProviderFailureClass | str,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        classification = ProviderFailureClass(failure_class)
        return await self._repository.record_circuit_failure(
            circuit_permit=circuit_permit,
            reservation_id=reservation_id,
            transient=classification in {ProviderFailureClass.NETWORK, ProviderFailureClass.SERVER},
            failure_threshold=self._transient_failure_threshold,
            cooldown_seconds=self._cooldown_seconds,
            now=now,
        )

    async def record_success(
        self,
        *,
        circuit_permit: ServerPrivateCircuitPermit,
        reservation_id: UUID,
        now: datetime,
    ) -> AgentCircuitStateRecord:
        return await self._repository.record_circuit_success(
            circuit_permit=circuit_permit,
            reservation_id=reservation_id,
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
