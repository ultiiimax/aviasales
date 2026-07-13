from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from flight_hunter.config import AppSettings, load_env_file


def test_settings_detects_aviasales_search_credentials_without_exposing_value(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AVIASALES_SEARCH_ENABLED", "true")
    monkeypatch.setenv("AVIASALES_SEARCH_SIGNATURE", "secret-signature")
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "secret-marker")

    settings = AppSettings.from_env()

    assert settings.aviasales_search_enabled
    assert settings.aviasales_search_signature == "secret-signature"
    assert settings.aviasales_search_marker == "secret-marker"
    assert settings.aviasales_search_credentials_present


def test_aviasales_credentials_shape_is_validated_locally() -> None:
    valid = AppSettings(
        database_url="sqlite+aiosqlite:///:memory:",
        aviasales_search_enabled=True,
        aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
        aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
    )
    invalid = replace(
        valid,
        aviasales_search_signature="not-a-uuid",
        aviasales_search_marker="not-a-marker",
    )

    assert valid.aviasales_search_credentials_valid is True
    assert invalid.aviasales_search_credentials_present is True
    assert invalid.aviasales_search_credentials_valid is False


def test_settings_parse_invitation_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_BOOTSTRAP_TOKEN", "bootstrap-secret")
    monkeypatch.setenv("AUTH_SESSION_TTL_SECONDS", "120")
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_HEADERS", "false")

    settings = AppSettings.from_env()

    assert settings.auth_bootstrap_token == "bootstrap-secret"
    assert settings.auth_session_ttl_seconds == 120
    assert not settings.auth_allow_legacy_headers


def test_settings_disable_legacy_headers_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_ALLOW_LEGACY_HEADERS", raising=False)

    settings = AppSettings.from_env()

    assert not settings.auth_allow_legacy_headers


def test_load_env_file_sets_missing_values_without_overriding_existing_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AVIASALES_SEARCH_ENABLED=true\n"
        "AVIASALES_SEARCH_SIGNATURE=file-signature\n"
        "AVIASALES_SEARCH_MARKER=file-marker\n"
        "APP_SECRET_KEY=file-app-secret\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AVIASALES_SEARCH_MARKER", "existing-marker")

    load_env_file(env_file)
    settings = AppSettings.from_env()

    assert settings.aviasales_search_enabled
    assert settings.aviasales_search_signature == "file-signature"
    assert settings.aviasales_search_marker == "existing-marker"
    assert settings.app_secret_key == "file-app-secret"


def test_settings_parse_personal_observer_and_clickout_lists(monkeypatch) -> None:
    monkeypatch.setenv("PERSONAL_OBSERVER_ALLOWED_HOSTS", "travel.yandex.ru,www.tutu.ru")
    monkeypatch.setenv("PERSONAL_OBSERVER_ARTIFACT_ROOT", ".local/observer-artifacts")
    monkeypatch.setenv("PERSONAL_OBSERVER_NAVIGATION_TIMEOUT_MS", "55000")
    monkeypatch.setenv("PERSONAL_OBSERVER_READY_SELECTOR", "[data-flight-card]")
    monkeypatch.setenv("PERSONAL_OBSERVER_READY_TIMEOUT_MS", "9000")
    monkeypatch.setenv("PERSONAL_OBSERVER_WAIT_FOR_NETWORK_IDLE", "true")
    monkeypatch.setenv("PERSONAL_OBSERVER_MANUAL_CHECKPOINT_SECONDS", "7")
    monkeypatch.setenv("PERSONAL_OBSERVER_SAVE_RUNTIME_MANIFESTS", "true")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_LOCK_TIMEOUT_SECONDS", "3")
    monkeypatch.setenv("PERSONAL_OBSERVER_PROFILE_LOCK_STALE_SECONDS", "120")
    monkeypatch.setenv("RU_AGGREGATORS_ENABLED", "tutu")
    monkeypatch.setenv("CARRIER_LINKS_ENABLED", "s7,pobeda")
    monkeypatch.setenv("TELEGRAM_WATCH_CHECK_SOURCE_ID", "yandex_travel")
    monkeypatch.setenv("CRAWL4AI_MODE", "server")
    monkeypatch.setenv("CRAWL4AI_BASE_URL", "http://crawl4ai:11235")
    monkeypatch.setenv("CRAWL4AI_API_TOKEN", "server-secret")
    monkeypatch.setenv("CRAWL4AI_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("DEAL_DISCOVERY_JOB_DEADLINE_SECONDS", "900")
    monkeypatch.setenv("DEAL_DISCOVERY_ALLOWED_HOSTS", "example.com,*.deals.example")

    settings = AppSettings.from_env()

    assert settings.personal_observer_allowed_hosts == ("travel.yandex.ru", "www.tutu.ru")
    assert settings.personal_observer_artifact_root == ".local/observer-artifacts"
    assert settings.personal_observer_navigation_timeout_ms == 55_000
    assert settings.personal_observer_ready_selector == "[data-flight-card]"
    assert settings.personal_observer_ready_timeout_ms == 9_000
    assert settings.personal_observer_wait_for_network_idle is True
    assert settings.personal_observer_manual_checkpoint_seconds == 7
    assert settings.personal_observer_save_runtime_manifests is True
    assert settings.personal_observer_profile_lock_timeout_seconds == 3
    assert settings.personal_observer_profile_lock_stale_seconds == 120
    assert settings.telegram_watch_check_source_id == "yandex_travel"
    assert settings.crawl4ai_mode == "server"
    assert settings.crawl4ai_base_url == "http://crawl4ai:11235"
    assert settings.crawl4ai_api_token == "server-secret"
    assert settings.crawl4ai_timeout_seconds == 45
    assert settings.deal_discovery_job_deadline_seconds == 900
    assert settings.deal_discovery_allowed_hosts == ("example.com", "*.deals.example")
    assert settings.ru_aggregators_enabled == ("tutu",)
    assert settings.carrier_links_enabled == ("s7", "pobeda")
    assert settings.ru_clickout_enabled_source_ids == ("tutu", "s7", "pobeda")


def test_settings_default_carrier_links_include_extended_confirmation_sources() -> None:
    settings = AppSettings.from_env()

    assert {
        "ural_airlines",
        "nordwind",
        "red_wings",
        "smartavia",
        "azimuth",
        "utair",
        "rossiya",
        "turkish_airlines",
        "air_serbia",
        "pegasus",
        "uzbekistan_airways",
        "emirates",
        "qatar_airways",
        "etihad",
        "flydubai",
    }.issubset(settings.carrier_links_enabled)


def test_agent_planning_settings_have_bounded_defaults() -> None:
    settings = AppSettings.from_env()

    assert settings.agent_plan_ttl_seconds == 86_400
    assert settings.agent_quick_logical_limit == 60
    assert settings.agent_quick_calendar_limit == 40
    assert settings.agent_quick_exact_limit == 20
    assert settings.agent_full_logical_limit == 240
    assert settings.agent_absolute_logical_limit == 1_000
    assert settings.agent_quick_deadline_seconds == 600
    assert settings.agent_full_deadline_seconds == 1_800
    assert settings.agent_operation_lease_seconds == 120
    assert settings.agent_max_layover_seconds == 64_800
    assert settings.agent_provider_circuit_failure_threshold == 5
    assert settings.agent_provider_circuit_cooldown_seconds == 120


@pytest.mark.parametrize(
    "name",
    (
        "AGENT_PLAN_TTL_SECONDS",
        "AGENT_QUICK_LOGICAL_LIMIT",
        "AGENT_QUICK_CALENDAR_LIMIT",
        "AGENT_QUICK_EXACT_LIMIT",
        "AGENT_FULL_LOGICAL_LIMIT",
        "AGENT_ABSOLUTE_LOGICAL_LIMIT",
        "AGENT_QUICK_DEADLINE_SECONDS",
        "AGENT_FULL_DEADLINE_SECONDS",
        "AGENT_OPERATION_LEASE_SECONDS",
        "AGENT_MAX_LAYOVER_SECONDS",
        "AGENT_PROVIDER_CIRCUIT_FAILURE_THRESHOLD",
        "AGENT_PROVIDER_CIRCUIT_COOLDOWN_SECONDS",
    ),
)
def test_agent_planning_settings_reject_non_positive_values(monkeypatch, name: str) -> None:
    monkeypatch.setenv(name, "0")

    with pytest.raises(ValueError, match="must be positive"):
        AppSettings.from_env()


@pytest.mark.parametrize("name", ("AGENT_QUICK_LOGICAL_LIMIT", "AGENT_FULL_LOGICAL_LIMIT"))
def test_agent_default_budget_cannot_exceed_absolute_ceiling(monkeypatch, name: str) -> None:
    monkeypatch.setenv(name, "1001")

    with pytest.raises(ValueError, match="absolute logical limit"):
        AppSettings.from_env()
