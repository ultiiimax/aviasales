from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from flight_hunter.application.watch_scheduler import (
    ProviderRuntimeState,
    SchedulerProviderRegistry,
    WatchSchedulerPlanner,
    WatchScheduleState,
)
from flight_hunter.domain.policy import DataKind, ProviderPolicy

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
WATCH_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_scheduler_never_selects_background_disallowed_provider() -> None:
    provider_policy = ProviderPolicy.aviasales_search(
        terms_verified_at=NOW,
        credentials_present=True,
        access_approved=True,
        enabled=True,
    )
    planner = WatchSchedulerPlanner(clock=lambda: NOW)

    decision = planner.decide(
        _watch_state(),
        providers=(ProviderRuntimeState(policy=provider_policy),),
    )

    assert not decision.eligible
    assert decision.provider_ids == ()
    assert decision.provider_denials == {"aviasales_search": "background_not_allowed"}


def test_scheduler_skips_watch_while_cache_is_fresh() -> None:
    planner = WatchSchedulerPlanner(clock=lambda: NOW)

    decision = planner.decide(
        _watch_state(cache_fresh_until=NOW + timedelta(hours=2)),
        providers=(ProviderRuntimeState(policy=ProviderPolicy.fake(terms_verified_at=NOW)),),
    )

    assert not decision.eligible
    assert decision.provider_ids == ()
    assert decision.blocked_reasons == ("cache_fresh",)


def test_scheduler_selects_due_background_provider_when_quota_is_reserved() -> None:
    planner = WatchSchedulerPlanner(clock=lambda: NOW)

    decision = planner.decide(
        _watch_state(),
        providers=(ProviderRuntimeState(policy=ProviderPolicy.fake(terms_verified_at=NOW)),),
    )

    assert decision.eligible
    assert decision.provider_ids == ("fake",)
    assert decision.blocked_reasons == ()


def test_scheduler_blocks_provider_when_circuit_is_open() -> None:
    planner = WatchSchedulerPlanner(clock=lambda: NOW)

    decision = planner.decide(
        _watch_state(),
        providers=(
            ProviderRuntimeState(
                policy=ProviderPolicy.fake(terms_verified_at=NOW),
                circuit_open=True,
            ),
        ),
    )

    assert not decision.eligible
    assert decision.provider_denials == {"fake": "circuit_open"}


def test_scheduler_registry_accepts_cached_background_provider() -> None:
    registry = SchedulerProviderRegistry()

    accepted = registry.register(
        ProviderRuntimeState(policy=ProviderPolicy.fake(terms_verified_at=NOW))
    )

    assert accepted is True
    assert [provider.policy.provider_id for provider in registry.providers] == ["fake"]
    assert registry.denials == {}


def test_scheduler_registry_accepts_live_provider_when_policy_allows_background() -> None:
    live_policy = _provider_policy(
        "aviasales_search",
        data_kind=DataKind.LIVE,
        background_requests_allowed=True,
        user_action_required=False,
    )
    registry = SchedulerProviderRegistry()

    accepted = registry.register(ProviderRuntimeState(policy=live_policy))

    assert accepted is True
    assert [provider.policy.provider_id for provider in registry.providers] == ["aviasales_search"]
    assert registry.denials == {}


def test_scheduler_registry_rejects_user_action_provider_before_planning() -> None:
    user_action_policy = _provider_policy(
        "user_action_only_source",
        data_kind=DataKind.CACHED,
        background_requests_allowed=True,
        user_action_required=True,
    )
    registry = SchedulerProviderRegistry()

    accepted = registry.register(ProviderRuntimeState(policy=user_action_policy))

    assert accepted is False
    assert registry.providers == ()
    assert registry.denials == {"user_action_only_source": "user_action_required"}


def _watch_state(
    *,
    cache_fresh_until: datetime | None = None,
) -> WatchScheduleState:
    return WatchScheduleState(
        watch_id=WATCH_ID,
        enabled=True,
        paused_until=None,
        departure_date=date(2026, 10, 12),
        next_eligible_at=NOW - timedelta(minutes=1),
        cache_fresh_until=cache_fresh_until,
        allowed_provider_ids=(),
    )


def _provider_policy(provider_id: str, **overrides: object) -> ProviderPolicy:
    values: dict[str, object] = {
        "provider_id": provider_id,
        "policy_version": "2026-06-23",
        "terms_url": "https://example.test/terms",
        "terms_verified_at": NOW,
        "enabled": True,
        "credentials_present": True,
        "access_approved": True,
        "data_kind": DataKind.CACHED,
        "background_requests_allowed": True,
        "user_action_required": False,
        "merge_with_other_sources_allowed": True,
        "persist_raw_results_allowed": False,
        "persist_normalized_results_allowed": True,
        "booking_link_requires_click": True,
        "preload_booking_links_allowed": False,
        "server_side_only": True,
        "real_user_ip_required": False,
        "max_requests_per_minute": 30,
        "max_requests_per_hour_per_user_ip": None,
        "cache_ttl_seconds": 3600,
        "result_ttl_seconds": 86400,
        "max_concurrent_requests": 2,
        "supports_flexible_dates": True,
        "supports_nearby_airports": True,
        "supports_multi_city": False,
        "supports_one_way": True,
        "supports_round_trip": True,
        "supports_baggage": False,
        "supports_fare_rules": False,
        "notes": "test",
    }
    values.update(overrides)
    return ProviderPolicy(**values)
