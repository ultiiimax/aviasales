from __future__ import annotations

from datetime import UTC, datetime

from flight_hunter.application.provider_registry import ProviderRegistry
from flight_hunter.config import AppSettings

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def test_registry_enables_aviasales_search_when_flag_and_credentials_exist() -> None:
    registry = ProviderRegistry.default(
        clock=lambda: NOW,
        settings=AppSettings(
            database_url="sqlite+aiosqlite:///:memory:",
            aviasales_search_enabled=True,
            aviasales_search_signature="secret-signature",
            aviasales_search_marker="secret-marker",
            aviasales_search_internal_rpm=20,
            telegram_enabled=False,
            telegram_webhook_secret=None,
        ),
    )

    providers = {status.provider_id: status for status in registry.statuses()}

    assert providers["aviasales_search"].enabled
    assert providers["aviasales_search"].credentials_present
    assert providers["aviasales_search"].blocked_reasons == ()
    assert "secret-signature" not in str(providers["aviasales_search"])
    assert "secret-marker" not in str(providers["aviasales_search"])
