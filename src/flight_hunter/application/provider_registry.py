from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from flight_hunter.application.search_planner import ProviderCandidate
from flight_hunter.config import AppSettings
from flight_hunter.domain.policy import DataKind, MergeScope, ProviderPolicy


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider_id: str
    enabled: bool
    credentials_present: bool
    access_approved: bool
    data_kind: DataKind
    merge_scope: MergeScope
    background_requests_allowed: bool
    user_action_required: bool
    blocked_reasons: tuple[str, ...]
    notes: str


class ProviderRegistry:
    def __init__(self, policies: Iterable[ProviderPolicy]) -> None:
        self._policies = {policy.provider_id: policy for policy in policies}

    @classmethod
    def default(
        cls,
        *,
        clock: Callable[[], datetime] | None = None,
        settings: AppSettings | None = None,
    ) -> ProviderRegistry:
        now = (clock or (lambda: datetime.now(UTC)))()
        app_settings = settings or AppSettings.from_env()
        return cls(
            (
                ProviderPolicy.fake(terms_verified_at=now),
                ProviderPolicy.aviasales_search_live(
                    terms_verified_at=now,
                    credentials_present=app_settings.aviasales_search_credentials_present,
                    enabled=app_settings.aviasales_search_enabled,
                    internal_rpm=app_settings.aviasales_search_internal_rpm,
                ),
                _skyscanner_indicative_policy(now),
                _skyscanner_live_policy(now),
                _duffel_policy(now),
            )
        )

    def statuses(self) -> tuple[ProviderStatus, ...]:
        return tuple(self._status_for(policy) for policy in self._policies.values())

    def search_candidates(
        self, provider_ids: tuple[str, ...] | None
    ) -> tuple[ProviderCandidate, ...]:
        policies = self._selected_policies(provider_ids)
        return tuple(
            ProviderCandidate(policy)
            for policy in policies
            if policy.enabled and policy.credentials_present and policy.access_approved
        )

    def planning_candidates(
        self, provider_ids: tuple[str, ...] | None
    ) -> tuple[ProviderCandidate, ...]:
        return tuple(ProviderCandidate(policy) for policy in self._selected_policies(provider_ids))

    def _selected_policies(
        self, provider_ids: tuple[str, ...] | None
    ) -> tuple[ProviderPolicy, ...]:
        if provider_ids is None:
            return tuple(self._policies.values())
        return tuple(
            policy for provider_id in provider_ids if (policy := self._policies.get(provider_id))
        )

    @staticmethod
    def _status_for(policy: ProviderPolicy) -> ProviderStatus:
        blocked_reasons: list[str] = []
        if not policy.enabled:
            blocked_reasons.append("provider_disabled")
        if not policy.credentials_present:
            blocked_reasons.append("credentials_missing")
        if not policy.access_approved:
            blocked_reasons.append("access_not_approved")

        return ProviderStatus(
            provider_id=policy.provider_id,
            enabled=policy.enabled,
            credentials_present=policy.credentials_present,
            access_approved=policy.access_approved,
            data_kind=policy.data_kind,
            merge_scope=policy.merge_scope,
            background_requests_allowed=policy.background_requests_allowed,
            user_action_required=policy.user_action_required,
            blocked_reasons=tuple(blocked_reasons),
            notes=policy.notes,
        )


def _skyscanner_indicative_policy(terms_verified_at: datetime) -> ProviderPolicy:
    return ProviderPolicy(
        provider_id="skyscanner_indicative",
        policy_version="2026-06-23",
        terms_url="https://developers.skyscanner.net/",
        terms_verified_at=terms_verified_at,
        enabled=False,
        credentials_present=False,
        access_approved=False,
        data_kind=DataKind.INDICATIVE,
        background_requests_allowed=False,
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
        cache_ttl_seconds=21600,
        result_ttl_seconds=86400,
        max_concurrent_requests=1,
        supports_flexible_dates=True,
        supports_nearby_airports=True,
        supports_multi_city=False,
        supports_one_way=True,
        supports_round_trip=True,
        supports_baggage=False,
        supports_fare_rules=False,
        notes="Disabled until partnership access and contract flags are verified.",
    )


def _skyscanner_live_policy(terms_verified_at: datetime) -> ProviderPolicy:
    return ProviderPolicy(
        provider_id="skyscanner_live",
        policy_version="2026-06-23",
        terms_url="https://developers.skyscanner.net/",
        terms_verified_at=terms_verified_at,
        enabled=False,
        credentials_present=False,
        access_approved=False,
        data_kind=DataKind.LIVE,
        background_requests_allowed=False,
        user_action_required=True,
        merge_with_other_sources_allowed=True,
        persist_raw_results_allowed=False,
        persist_normalized_results_allowed=True,
        booking_link_requires_click=True,
        preload_booking_links_allowed=False,
        server_side_only=True,
        real_user_ip_required=False,
        max_requests_per_minute=None,
        max_requests_per_hour_per_user_ip=None,
        cache_ttl_seconds=0,
        result_ttl_seconds=900,
        max_concurrent_requests=1,
        supports_flexible_dates=False,
        supports_nearby_airports=False,
        supports_multi_city=False,
        supports_one_way=True,
        supports_round_trip=True,
        supports_baggage=True,
        supports_fare_rules=True,
        notes="Live adapter disabled until approved partnership and user-action gating.",
    )


def _duffel_policy(terms_verified_at: datetime) -> ProviderPolicy:
    return ProviderPolicy(
        provider_id="duffel",
        policy_version="2026-06-23",
        terms_url="https://duffel.com/docs/api/v2/offer-requests",
        terms_verified_at=terms_verified_at,
        enabled=False,
        credentials_present=False,
        access_approved=False,
        data_kind=DataKind.BOOKABLE,
        background_requests_allowed=False,
        user_action_required=True,
        merge_with_other_sources_allowed=True,
        persist_raw_results_allowed=False,
        persist_normalized_results_allowed=True,
        booking_link_requires_click=True,
        preload_booking_links_allowed=False,
        server_side_only=True,
        real_user_ip_required=False,
        max_requests_per_minute=None,
        max_requests_per_hour_per_user_ip=None,
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
        notes="Disabled until credentials and contract background/live flags are configured.",
    )
