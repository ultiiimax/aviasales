from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.application.provider_registry import ProviderRegistry
from flight_hunter.config import AppSettings
from flight_hunter.domain.policy import DataKind, MergeScope

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_default_registry_exposes_policy_derived_provider_statuses() -> None:
    registry = ProviderRegistry.default(
        clock=lambda: NOW,
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_search_enabled=False,
            aviasales_search_signature=None,
            aviasales_search_marker=None,
            aviasales_search_internal_rpm=20,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
    )

    providers = {status.provider_id: status for status in registry.statuses()}

    assert providers["fake"].enabled
    assert providers["fake"].data_kind == DataKind.CACHED
    assert providers["fake"].merge_scope == MergeScope.MERGEABLE
    assert providers["aviasales_search"].data_kind == DataKind.LIVE
    assert providers["aviasales_search"].merge_scope == MergeScope.MERGEABLE
    assert providers["aviasales_search"].background_requests_allowed is True
    assert providers["aviasales_search"].user_action_required is False
    assert "credentials_missing" in providers["aviasales_search"].blocked_reasons
    assert "access_not_approved" not in providers["aviasales_search"].blocked_reasons
    assert "provider_disabled" in providers["aviasales_search"].blocked_reasons


def test_default_registry_search_candidates_include_enabled_demo_provider_only() -> None:
    registry = ProviderRegistry.default(
        clock=lambda: NOW,
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_search_enabled=False,
            aviasales_search_signature=None,
            aviasales_search_marker=None,
            aviasales_search_internal_rpm=20,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
    )

    candidates = registry.search_candidates(provider_ids=None)

    assert [candidate.policy.provider_id for candidate in candidates] == ["fake"]


def test_legacy_aviasales_policy_does_not_advertise_native_multi_city() -> None:
    registry = ProviderRegistry.default(
        clock=lambda: NOW,
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_search_enabled=False,
            aviasales_search_signature=None,
            aviasales_search_marker=None,
            aviasales_search_internal_rpm=20,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
    )

    (candidate,) = registry.planning_candidates(("aviasales_search",))

    assert candidate.policy.supports_multi_city is False
