from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from flight_hunter.domain.offers import FlightOffer
from flight_hunter.domain.policy import require_aware_datetime


class ObserverCapability(StrEnum):
    PUBLIC_NAVIGATION = "public_navigation"
    PUBLIC_DOM_READ = "public_dom_read"
    TEMPORARY_REDACTED_HTML = "temporary_redacted_html"
    TEMPORARY_REDACTED_SCREENSHOT = "temporary_redacted_screenshot"


_PROHIBITED_CAPABILITIES = frozenset(
    {
        "challenge_bypass",
        "fingerprint_evasion",
        "cookie_reuse",
        "credential_reuse",
        "access_control_bypass",
        "background_execution",
    }
)


class PermissionStatus(StrEnum):
    ACTIVE = "active"
    MISSING = "missing"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    REVOKED = "revoked"


class ObservationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    OPENING_BROWSER = "opening_browser"
    WAITING_FOR_USER = "waiting_for_user"
    CAPTURING_DOM = "capturing_dom"
    PARSING = "parsing"
    SUCCEEDED = "succeeded"
    NEEDS_HUMAN = "needs_human"
    NO_PRICE_FOUND = "no_price_found"
    SOURCE_CHALLENGE = "source_challenge"
    SELECTOR_DRIFT = "selector_drift"
    TIMED_OUT = "timed_out"
    SOURCE_UNAVAILABLE = "source_unavailable"
    POLICY_DENIED = "policy_denied"
    FAILED = "failed"
    EXPIRED = "expired"


class ObservationErrorCode(StrEnum):
    BROWSER_RUNTIME_UNAVAILABLE = "browser_runtime_unavailable"
    POLICY_DENIED = "policy_denied"
    SOURCE_CHALLENGE = "source_challenge"
    SELECTOR_DRIFT = "selector_drift"
    TIMED_OUT = "timed_out"
    SOURCE_UNAVAILABLE = "source_unavailable"
    OPERATOR_ABORTED = "operator_aborted"
    EXPIRED = "expired"
    FAILED = "failed"


class OperatorCheckpointDecision(StrEnum):
    WAITING = "waiting"
    RESUME = "resume"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class PermissionAttestation:
    attestation_id: str
    source_id: str
    allowed_domains: tuple[str, ...]
    allowed_capabilities: tuple[ObserverCapability | str, ...]
    document_ref: str
    document_hash: str | None
    valid_from: datetime
    valid_until: datetime | None
    terms_verified_at: datetime
    approved_by: str
    revoked_at: datetime | None

    def __post_init__(self) -> None:
        if not self.attestation_id:
            raise ValueError("attestation_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.allowed_domains:
            raise ValueError("allowed_domains is required")
        if not self.allowed_capabilities:
            raise ValueError("allowed_capabilities is required")
        if not self.document_ref:
            raise ValueError("document_ref is required")
        if not self.approved_by:
            raise ValueError("approved_by is required")
        require_aware_datetime(self.valid_from, "valid_from")
        if self.valid_until is not None:
            require_aware_datetime(self.valid_until, "valid_until")
            if self.valid_until <= self.valid_from:
                raise ValueError("valid_until must be after valid_from")
        require_aware_datetime(self.terms_verified_at, "terms_verified_at")
        if self.revoked_at is not None:
            require_aware_datetime(self.revoked_at, "revoked_at")

        normalized = tuple(_normalize_capability(value) for value in self.allowed_capabilities)
        object.__setattr__(self, "allowed_capabilities", normalized)
        object.__setattr__(
            self,
            "allowed_domains",
            tuple(domain.lower() for domain in self.allowed_domains),
        )

    def status_at(self, now: datetime) -> PermissionStatus:
        require_aware_datetime(now, "now")
        if self.revoked_at is not None and self.revoked_at <= now:
            return PermissionStatus.REVOKED
        if now < self.valid_from:
            return PermissionStatus.NOT_YET_VALID
        if self.valid_until is not None and now >= self.valid_until:
            return PermissionStatus.EXPIRED
        return PermissionStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class BrowserSource:
    source_id: str
    display_name: str
    enabled: bool
    supported_routes: tuple[str, ...]
    current_health: str
    attestation: PermissionAttestation | None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.display_name:
            raise ValueError("display_name is required")
        if not self.current_health:
            raise ValueError("current_health is required")

    @property
    def background_allowed(self) -> bool:
        return False

    def permission_status(self, now: datetime) -> PermissionStatus:
        if self.attestation is None:
            return PermissionStatus.MISSING
        return self.attestation.status_at(now)


@dataclass(frozen=True, slots=True)
class LiveObservation:
    observation_id: UUID
    grant_id: UUID
    user_id: UUID
    source_id: str
    search_intent_hash: str
    status: ObservationStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime
    offers: tuple[FlightOffer, ...]
    error_code: ObservationErrorCode | None
    error_message: str | None

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.search_intent_hash:
            raise ValueError("search_intent_hash is required")
        require_aware_datetime(self.created_at, "created_at")
        if self.started_at is not None:
            require_aware_datetime(self.started_at, "started_at")
        if self.completed_at is not None:
            require_aware_datetime(self.completed_at, "completed_at")
        require_aware_datetime(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.error_code is None and self.error_message is not None:
            raise ValueError("error_message requires error_code")


def _normalize_capability(value: ObserverCapability | str) -> ObserverCapability:
    raw_value = value.value if isinstance(value, ObserverCapability) else value
    if raw_value in _PROHIBITED_CAPABILITIES:
        raise ValueError(f"prohibited capability: {raw_value}")
    try:
        return ObserverCapability(raw_value)
    except ValueError as exc:
        raise ValueError(f"unknown observer capability: {raw_value}") from exc
