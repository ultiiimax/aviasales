from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID


def require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class DataKind(StrEnum):
    CACHED = "cached"
    INDICATIVE = "indicative"
    LIVE = "live"
    BOOKABLE = "bookable"
    FEED = "feed"


class ExecutionContext(StrEnum):
    API_REQUEST = "api_request"
    SCHEDULER = "scheduler"
    TELEGRAM_CALLBACK = "telegram_callback"
    WEB_USER_ACTION = "web_user_action"
    WORKER = "worker"


class ProviderOperation(StrEnum):
    BOOKING_ACTION = "booking_action"
    LIVE_REFRESH = "live_refresh"
    SEARCH = "search"


class MergeScope(StrEnum):
    MERGEABLE = "mergeable"
    PROVIDER_ISOLATED = "provider_isolated"
    PRIVATE_TRANSIENT = "private_transient"


@dataclass(frozen=True, slots=True)
class ProviderPolicy:
    provider_id: str
    policy_version: str
    terms_url: str
    terms_verified_at: datetime

    enabled: bool
    credentials_present: bool
    access_approved: bool

    data_kind: DataKind
    background_requests_allowed: bool
    user_action_required: bool
    merge_with_other_sources_allowed: bool
    persist_raw_results_allowed: bool
    persist_normalized_results_allowed: bool
    booking_link_requires_click: bool
    preload_booking_links_allowed: bool
    server_side_only: bool
    real_user_ip_required: bool

    max_requests_per_minute: int | None
    max_requests_per_hour_per_user_ip: int | None
    cache_ttl_seconds: int
    result_ttl_seconds: int | None
    max_concurrent_requests: int

    supports_flexible_dates: bool
    supports_nearby_airports: bool
    supports_multi_city: bool
    supports_one_way: bool
    supports_round_trip: bool
    supports_baggage: bool
    supports_fare_rules: bool

    notes: str

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        require_aware_datetime(self.terms_verified_at, "terms_verified_at")
        if self.max_requests_per_minute is not None and self.max_requests_per_minute < 0:
            raise ValueError("max_requests_per_minute cannot be negative")
        if (
            self.max_requests_per_hour_per_user_ip is not None
            and self.max_requests_per_hour_per_user_ip < 0
        ):
            raise ValueError("max_requests_per_hour_per_user_ip cannot be negative")
        if self.cache_ttl_seconds < 0:
            raise ValueError("cache_ttl_seconds cannot be negative")
        if self.result_ttl_seconds is not None and self.result_ttl_seconds < 0:
            raise ValueError("result_ttl_seconds cannot be negative")
        if self.max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        if self.booking_link_requires_click and self.preload_booking_links_allowed:
            raise ValueError("booking links cannot both require click and allow preload")

    @property
    def merge_scope(self) -> MergeScope:
        if self.merge_with_other_sources_allowed:
            return MergeScope.MERGEABLE
        return MergeScope.PROVIDER_ISOLATED

    @classmethod
    def fake(cls, *, terms_verified_at: datetime) -> ProviderPolicy:
        return cls(
            provider_id="fake",
            policy_version="2026-06-23",
            terms_url="https://flight-hunter.local/policies/fake-provider",
            terms_verified_at=terms_verified_at,
            enabled=True,
            credentials_present=True,
            access_approved=True,
            data_kind=DataKind.CACHED,
            background_requests_allowed=True,
            user_action_required=False,
            merge_with_other_sources_allowed=True,
            persist_raw_results_allowed=False,
            persist_normalized_results_allowed=True,
            booking_link_requires_click=True,
            preload_booking_links_allowed=False,
            server_side_only=True,
            real_user_ip_required=False,
            max_requests_per_minute=None,
            max_requests_per_hour_per_user_ip=None,
            cache_ttl_seconds=300,
            result_ttl_seconds=86400,
            max_concurrent_requests=8,
            supports_flexible_dates=True,
            supports_nearby_airports=True,
            supports_multi_city=False,
            supports_one_way=True,
            supports_round_trip=True,
            supports_baggage=False,
            supports_fare_rules=False,
            notes="Deterministic demo source. Not a real fare provider.",
        )

    @classmethod
    def aviasales_search(
        cls,
        *,
        terms_verified_at: datetime,
        credentials_present: bool,
        access_approved: bool,
        enabled: bool,
    ) -> ProviderPolicy:
        return cls(
            provider_id="aviasales_search",
            policy_version="2026-06-23",
            terms_url=(
                "https://support.travelpayouts.com/hc/en-us/articles/"
                "30565016140434-Aviasales-Flight-Search-API-real-time-and-multi-city-search"
            ),
            terms_verified_at=terms_verified_at,
            enabled=enabled,
            credentials_present=credentials_present,
            access_approved=access_approved,
            data_kind=DataKind.LIVE,
            background_requests_allowed=False,
            user_action_required=True,
            merge_with_other_sources_allowed=False,
            persist_raw_results_allowed=False,
            persist_normalized_results_allowed=True,
            booking_link_requires_click=True,
            preload_booking_links_allowed=False,
            server_side_only=True,
            real_user_ip_required=True,
            max_requests_per_minute=None,
            max_requests_per_hour_per_user_ip=100,
            cache_ttl_seconds=0,
            result_ttl_seconds=900,
            max_concurrent_requests=1,
            supports_flexible_dates=False,
            supports_nearby_airports=False,
            supports_multi_city=True,
            supports_one_way=True,
            supports_round_trip=True,
            supports_baggage=True,
            supports_fare_rules=True,
            notes=(
                "Disabled until approved access and feature flag. Each call requires a "
                "real user action grant and results stay provider-isolated."
            ),
        )

    @classmethod
    def aviasales_search_live(
        cls,
        *,
        terms_verified_at: datetime,
        credentials_present: bool,
        enabled: bool,
        internal_rpm: int = 20,
    ) -> ProviderPolicy:
        return cls(
            provider_id="aviasales_search",
            policy_version="2026-07-04",
            terms_url="https://tickets-api.aviasales.ru",
            terms_verified_at=terms_verified_at,
            enabled=enabled,
            credentials_present=credentials_present,
            access_approved=True,
            data_kind=DataKind.LIVE,
            background_requests_allowed=True,
            user_action_required=False,
            merge_with_other_sources_allowed=True,
            persist_raw_results_allowed=False,
            persist_normalized_results_allowed=True,
            booking_link_requires_click=False,
            preload_booking_links_allowed=False,
            server_side_only=True,
            real_user_ip_required=False,
            max_requests_per_minute=internal_rpm,
            max_requests_per_hour_per_user_ip=None,
            cache_ttl_seconds=0,
            result_ttl_seconds=900,
            max_concurrent_requests=2,
            supports_flexible_dates=False,
            supports_nearby_airports=False,
            supports_multi_city=True,
            supports_one_way=True,
            supports_round_trip=True,
            supports_baggage=True,
            supports_fare_rules=True,
            notes=(
                "Local hobby project: Aviasales mobile API used directly. Live data. "
                "Background watch scans allowed. Booking URL resolved lazily on click."
            ),
        )


@dataclass(frozen=True, slots=True)
class UserActionGrant:
    id: UUID
    user_id: UUID
    provider_id: str
    action_type: str
    request_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    source: str
    consumed_at: datetime | None

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("provider_id is required")
        if not self.action_type:
            raise ValueError("action_type is required")
        if not self.request_fingerprint:
            raise ValueError("request_fingerprint is required")
        require_aware_datetime(self.issued_at, "issued_at")
        require_aware_datetime(self.expires_at, "expires_at")
        if self.consumed_at is not None:
            require_aware_datetime(self.consumed_at, "consumed_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")

    def is_expired(self, now: datetime) -> bool:
        require_aware_datetime(now, "now")
        return now >= self.expires_at

    def consume(self, now: datetime) -> UserActionGrant:
        require_aware_datetime(now, "now")
        if self.consumed_at is not None:
            raise ValueError("grant is already consumed")
        return replace(self, consumed_at=now)
