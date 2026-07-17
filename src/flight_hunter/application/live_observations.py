from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from flight_hunter.application.live_refresh import LiveRefreshGate, LiveRefreshState
from flight_hunter.domain.money import Money
from flight_hunter.domain.observation import (
    BrowserSource,
    LiveObservation,
    ObservationStatus,
    ObserverCapability,
    PermissionAttestation,
    PermissionStatus,
)
from flight_hunter.domain.offers import FlightOffer, Freshness, SearchIntent
from flight_hunter.domain.places import PlaceKind
from flight_hunter.domain.policy import (
    DataKind,
    ExecutionContext,
    ProviderPolicy,
    UserActionGrant,
)
from flight_hunter.policy.guard import DenialCode


class GrantSource(StrEnum):
    WEB_CLICK = "web_click"
    TELEGRAM_CALLBACK = "telegram_callback"
    API_REQUEST = "api_request"


class GrantIssueCode(StrEnum):
    ISSUED = "issued"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_DISABLED = "source_disabled"
    PERMISSION_NOT_VERIFIED = "permission_not_verified"


class LiveObservationCreateCode(StrEnum):
    QUEUED = "queued"
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_DISABLED = "source_disabled"
    PERMISSION_NOT_VERIFIED = "permission_not_verified"
    USER_ACTION_GRANT_REQUIRED = "user_action_grant_required"
    USER_ACTION_GRANT_CONSUMED = "user_action_grant_consumed"
    USER_ACTION_GRANT_EXPIRED = "user_action_grant_expired"
    USER_ACTION_GRANT_FINGERPRINT_MISMATCH = "user_action_grant_fingerprint_mismatch"
    USER_ACTION_GRANT_PROVIDER_MISMATCH = "user_action_grant_provider_mismatch"
    USER_ACTION_GRANT_USER_MISMATCH = "user_action_grant_user_mismatch"
    BACKGROUND_NOT_ALLOWED = "background_not_allowed"
    LIVE_REFRESH_TOO_SOON = "live_refresh_too_soon"
    POLICY_DENIED = "policy_denied"


@dataclass(frozen=True, slots=True)
class GrantIssueDecision:
    allowed: bool
    code: GrantIssueCode
    message: str
    grant_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class LiveObservationCreateDecision:
    accepted: bool
    code: LiveObservationCreateCode
    message: str
    observation_id: UUID | None
    initial_status: ObservationStatus | None
    next_allowed_at: datetime | None


class BrowserSourceCatalog:
    def __init__(self, sources: Iterable[BrowserSource]) -> None:
        self._sources = {source.source_id: source for source in sources}

    @classmethod
    def demo(
        cls,
        *,
        enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> BrowserSourceCatalog:
        now = (clock or (lambda: datetime.now(UTC)))()
        attestation = PermissionAttestation(
            attestation_id="att_demo_browser",
            source_id="demo_browser",
            allowed_domains=("flight-hunter.local",),
            allowed_capabilities=(
                ObserverCapability.PUBLIC_NAVIGATION,
                ObserverCapability.PUBLIC_DOM_READ,
            ),
            document_ref="docs/provider-contracts/demo-browser-observer.md",
            document_hash=None,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=365),
            terms_verified_at=now,
            approved_by="flight-hunter-demo",
            revoked_at=None,
        )
        return cls(
            (
                BrowserSource(
                    source_id="demo_browser",
                    display_name="Demo live observer",
                    enabled=enabled,
                    supported_routes=("WAW-BCN", "MOW-LED"),
                    current_health="healthy" if enabled else "disabled",
                    attestation=attestation,
                ),
            )
        )

    def get(self, source_id: str) -> BrowserSource | None:
        return self._sources.get(source_id)

    def sources(self) -> tuple[BrowserSource, ...]:
        return tuple(self._sources.values())


class LiveObservationService:
    def __init__(
        self,
        *,
        catalog: BrowserSourceCatalog,
        clock: Callable[[], datetime] | None = None,
        grant_ttl: timedelta = timedelta(minutes=5),
        result_ttl: timedelta = timedelta(minutes=15),
    ) -> None:
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(UTC))
        self._grant_ttl = grant_ttl
        self._result_ttl = result_ttl
        self._gate = LiveRefreshGate(clock=self._clock)
        self._grants: dict[UUID, UserActionGrant] = {}
        self._observations: dict[UUID, LiveObservation] = {}
        self._idempotency: dict[tuple[UUID, str], UUID] = {}
        self._last_refresh_at: dict[tuple[UUID, str, str], datetime] = {}

    def issue_grant(
        self,
        *,
        user_id: UUID,
        source_id: str,
        search_intent: SearchIntent,
        source: GrantSource,
    ) -> GrantIssueDecision:
        now = self._clock()
        browser_source = self._catalog.get(source_id)
        source_decision = self._validate_source(browser_source, now=now)
        if source_decision is not None:
            code, message = source_decision
            return GrantIssueDecision(
                allowed=False,
                code=GrantIssueCode(code.value),
                message=message,
                grant_token=None,
                expires_at=None,
            )

        grant_id = uuid4()
        expires_at = now + self._grant_ttl
        grant = UserActionGrant(
            id=grant_id,
            user_id=user_id,
            provider_id=source_id,
            action_type="live_observation",
            request_fingerprint=search_intent_fingerprint(search_intent),
            issued_at=now,
            expires_at=expires_at,
            source=source.value,
            consumed_at=None,
        )
        self._grants[grant_id] = grant
        return GrantIssueDecision(
            allowed=True,
            code=GrantIssueCode.ISSUED,
            message="user action grant issued",
            grant_token=str(grant_id),
            expires_at=expires_at,
        )

    def create_observation(
        self,
        *,
        user_id: UUID,
        source_id: str,
        search_intent: SearchIntent,
        grant_token: str,
        idempotency_key: str,
        context: ExecutionContext,
    ) -> LiveObservationCreateDecision:
        if (existing := self._idempotency.get((user_id, idempotency_key))) is not None:
            return LiveObservationCreateDecision(
                accepted=True,
                code=LiveObservationCreateCode.QUEUED,
                message="idempotent live observation request already accepted",
                observation_id=existing,
                initial_status=ObservationStatus.QUEUED,
                next_allowed_at=None,
            )

        now = self._clock()
        browser_source = self._catalog.get(source_id)
        source_decision = self._validate_source(browser_source, now=now)
        if source_decision is not None:
            code, message = source_decision
            return self._deny(code=LiveObservationCreateCode(code.value), message=message)
        if browser_source is None:
            return self._deny(
                code=LiveObservationCreateCode.SOURCE_NOT_FOUND,
                message="source not found",
            )

        grant = self._grant_for_token(grant_token)
        if grant is None:
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_REQUIRED,
                message="user action grant is required",
            )
        if grant.user_id != user_id:
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_USER_MISMATCH,
                message="user action grant belongs to a different user",
            )

        fingerprint = search_intent_fingerprint(search_intent)
        grant_decision = self._validate_grant_before_gap(
            grant=grant,
            source_id=source_id,
            request_fingerprint=fingerprint,
            now=now,
        )
        if grant_decision is not None:
            return grant_decision

        policy = self._policy_for_source(browser_source, now=now)
        decision = self._gate.authorize(
            policy,
            context=context,
            request_fingerprint=fingerprint,
            user_action_grant=grant,
            state=LiveRefreshState(
                provider_id=source_id,
                request_fingerprint=fingerprint,
                last_refresh_at=self._last_refresh_at.get((user_id, source_id, fingerprint)),
            ),
        )
        if not decision.allowed:
            return self._deny(
                code=_create_code_from_denial(decision.policy_decision.code),
                message=decision.message,
                next_allowed_at=decision.next_allowed_at,
            )

        if decision.policy_decision.consumed_grant is not None:
            self._grants[grant.id] = decision.policy_decision.consumed_grant

        observation_id = uuid4()
        queued = LiveObservation(
            observation_id=observation_id,
            grant_id=grant.id,
            user_id=user_id,
            source_id=source_id,
            search_intent_hash=fingerprint,
            status=ObservationStatus.QUEUED,
            created_at=now,
            started_at=None,
            completed_at=None,
            expires_at=now + self._result_ttl,
            offers=(),
            error_code=None,
            error_message=None,
        )
        self._observations[observation_id] = self._run_fake_worker(queued, search_intent)
        self._idempotency[(user_id, idempotency_key)] = observation_id
        self._last_refresh_at[(user_id, source_id, fingerprint)] = now
        return LiveObservationCreateDecision(
            accepted=True,
            code=LiveObservationCreateCode.QUEUED,
            message="live observation queued",
            observation_id=observation_id,
            initial_status=ObservationStatus.QUEUED,
            next_allowed_at=None,
        )

    def get_observation(
        self,
        *,
        user_id: UUID,
        observation_id: UUID,
    ) -> LiveObservation | None:
        observation = self._observations.get(observation_id)
        if observation is None or observation.user_id != user_id:
            return None
        return observation

    def list_sources(self) -> tuple[BrowserSource, ...]:
        return self._catalog.sources()

    def _validate_source(
        self,
        source: BrowserSource | None,
        *,
        now: datetime,
    ) -> tuple[GrantIssueCode, str] | None:
        if source is None:
            return GrantIssueCode.SOURCE_NOT_FOUND, "source not found"
        if not source.enabled:
            return GrantIssueCode.SOURCE_DISABLED, "source disabled"
        if source.permission_status(now) != PermissionStatus.ACTIVE:
            return GrantIssueCode.PERMISSION_NOT_VERIFIED, "source permission not verified"
        return None

    def _policy_for_source(self, source: BrowserSource, *, now: datetime) -> ProviderPolicy:
        attestation = source.attestation
        return ProviderPolicy(
            provider_id=source.source_id,
            policy_version="2026-06-23",
            terms_url="https://flight-hunter.local/policies/browser-observer",
            terms_verified_at=attestation.terms_verified_at if attestation is not None else now,
            enabled=source.enabled,
            credentials_present=attestation is not None,
            access_approved=source.permission_status(now) == PermissionStatus.ACTIVE,
            data_kind=DataKind.LIVE,
            background_requests_allowed=False,
            user_action_required=True,
            merge_with_other_sources_allowed=False,
            persist_raw_results_allowed=False,
            persist_normalized_results_allowed=True,
            booking_link_requires_click=True,
            preload_booking_links_allowed=False,
            server_side_only=True,
            real_user_ip_required=False,
            max_requests_per_minute=6,
            max_requests_per_hour_per_user_ip=12,
            cache_ttl_seconds=0,
            result_ttl_seconds=900,
            max_concurrent_requests=1,
            supports_flexible_dates=False,
            supports_nearby_airports=False,
            supports_multi_city=False,
            supports_one_way=True,
            supports_round_trip=True,
            supports_baggage=False,
            supports_fare_rules=False,
            notes="User-action-only fake live observation control plane.",
        )

    def _grant_for_token(self, token: str) -> UserActionGrant | None:
        try:
            grant_id = UUID(token)
        except ValueError:
            return None
        return self._grants.get(grant_id)

    def _validate_grant_before_gap(
        self,
        *,
        grant: UserActionGrant,
        source_id: str,
        request_fingerprint: str,
        now: datetime,
    ) -> LiveObservationCreateDecision | None:
        if grant.provider_id != source_id:
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_PROVIDER_MISMATCH,
                message="user action grant provider mismatch",
            )
        if grant.request_fingerprint != request_fingerprint:
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_FINGERPRINT_MISMATCH,
                message="user action grant fingerprint mismatch",
            )
        if grant.consumed_at is not None:
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_CONSUMED,
                message="user action grant consumed",
            )
        if grant.is_expired(now):
            return self._deny(
                code=LiveObservationCreateCode.USER_ACTION_GRANT_EXPIRED,
                message="user action grant expired",
            )
        return None

    def _run_fake_worker(
        self,
        queued: LiveObservation,
        search_intent: SearchIntent,
    ) -> LiveObservation:
        now = self._clock()
        offer = FlightOffer(
            provider_id=queued.source_id,
            provider_offer_id=f"live-{queued.observation_id}",
            origin=search_intent.origin,
            destination=search_intent.destination,
            departure_date=search_intent.departure_date,
            return_date=search_intent.return_date,
            total_price=Money(minor_units=151200, currency=search_intent.currency),
            passengers=search_intent.passengers,
            observed_at=now,
            freshness=Freshness.LIVE_OBSERVED,
            requires_live_confirmation=True,
            baggage_summary=None,
        )
        return replace(
            queued,
            status=ObservationStatus.SUCCEEDED,
            started_at=now,
            completed_at=now,
            offers=(offer,),
            error_code=None,
            error_message=None,
        )

    @staticmethod
    def _deny(
        *,
        code: LiveObservationCreateCode,
        message: str,
        next_allowed_at: datetime | None = None,
    ) -> LiveObservationCreateDecision:
        return LiveObservationCreateDecision(
            accepted=False,
            code=code,
            message=message,
            observation_id=None,
            initial_status=None,
            next_allowed_at=next_allowed_at,
        )


def search_intent_fingerprint(search_intent: SearchIntent) -> str:
    payload = {
        "origin": search_intent.origin,
        "destination": search_intent.destination,
        "departure_date": search_intent.departure_date,
        "return_date": search_intent.return_date,
        "passengers": search_intent.passengers,
        "adults": search_intent.adults,
        "children": search_intent.children,
        "infants": search_intent.infants,
        "trip_type": str(search_intent.trip_type),
        "currency": search_intent.currency,
        "origin_kind": PlaceKind(search_intent.origin_kind).value,
        "destination_kind": PlaceKind(search_intent.destination_kind).value,
        "origin_airport_codes": list(search_intent.origin_airport_codes),
        "destination_airport_codes": list(search_intent.destination_airport_codes),
        "directory_version": search_intent.directory_version,
        "origin_membership_version": search_intent.origin_membership_version,
        "destination_membership_version": search_intent.destination_membership_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _create_code_from_denial(code: DenialCode) -> LiveObservationCreateCode:
    return {
        DenialCode.BACKGROUND_NOT_ALLOWED: LiveObservationCreateCode.BACKGROUND_NOT_ALLOWED,
        DenialCode.LIVE_REFRESH_TOO_SOON: LiveObservationCreateCode.LIVE_REFRESH_TOO_SOON,
        DenialCode.USER_ACTION_GRANT_CONSUMED: (
            LiveObservationCreateCode.USER_ACTION_GRANT_CONSUMED
        ),
        DenialCode.USER_ACTION_GRANT_EXPIRED: LiveObservationCreateCode.USER_ACTION_GRANT_EXPIRED,
        DenialCode.USER_ACTION_GRANT_FINGERPRINT_MISMATCH: (
            LiveObservationCreateCode.USER_ACTION_GRANT_FINGERPRINT_MISMATCH
        ),
        DenialCode.USER_ACTION_GRANT_PROVIDER_MISMATCH: (
            LiveObservationCreateCode.USER_ACTION_GRANT_PROVIDER_MISMATCH
        ),
        DenialCode.USER_ACTION_GRANT_REQUIRED: (
            LiveObservationCreateCode.USER_ACTION_GRANT_REQUIRED
        ),
    }.get(code, LiveObservationCreateCode.POLICY_DENIED)
