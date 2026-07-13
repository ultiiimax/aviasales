from __future__ import annotations

from pathlib import Path

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
