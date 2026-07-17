from __future__ import annotations

from pathlib import Path


def test_env_example_exists_with_safe_placeholders() -> None:
    env_example = Path(".env.example")

    assert env_example.exists()

    content = env_example.read_text(encoding="utf-8")
    assert "APP_BASE_URL=http://127.0.0.1:8000" in content
    assert "API_BASE_URL=http://127.0.0.1:8000" in content
    assert "DATABASE_URL=sqlite+aiosqlite:///./flight_hunter_dev.db" in content
    assert "AUTH_BOOTSTRAP_TOKEN=" in content
    assert "AUTH_SESSION_TTL_SECONDS=2592000" in content
    assert "AUTH_ALLOW_LEGACY_HEADERS=false" in content
    assert "AUTH_LOCAL_AUTO_LOGIN=true" in content
    assert "APP_SECRET_KEY=\n" in content
    assert "AVIASALES_SEARCH_ENABLED=false" in content
    assert "AVIASALES_SEARCH_SIGNATURE=\n" in content
    assert "AVIASALES_SEARCH_MARKER=\n" in content
    assert "TELEGRAM_BOT_TOKEN=" in content
    assert "AGENT_PROVIDER=deterministic_presets" in content
    assert "AGENT_MCP_ENABLED=false" in content
    assert "AGENT_CODEX_CLI_ENABLED=false" in content
    assert "AGENT_CODEX_CLI_MODEL=gpt-5.4-mini" in content
    assert "AGENT_CODEX_CLI_TIMEOUT_SECONDS=15" in content
    assert "AGENT_OPENAI_ENABLED=false" in content
    assert "AGENT_OPENAI_MODEL=gpt-5.5" in content
    assert "AGENT_OPENAI_TIMEOUT_SECONDS=8" in content
    assert "AGENT_PLAN_TTL_SECONDS=86400" in content
    assert "AGENT_QUICK_LOGICAL_LIMIT=60" in content
    assert "AGENT_QUICK_CALENDAR_LIMIT=40" in content
    assert "AGENT_QUICK_EXACT_LIMIT=20" in content
    assert "AGENT_FULL_LOGICAL_LIMIT=240" in content
    assert "AGENT_ABSOLUTE_LOGICAL_LIMIT=1000" in content
    assert "AGENT_QUICK_DEADLINE_SECONDS=600" in content
    assert "AGENT_FULL_DEADLINE_SECONDS=1800" in content
    assert "AGENT_OPERATION_LEASE_SECONDS=120" in content
    assert "AGENT_POLL_INTERVAL_SECONDS=2" in content
    assert "AGENT_MAX_LAYOVER_SECONDS=64800" in content
    assert "AGENT_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=5" in content
    assert "AGENT_PROVIDER_CIRCUIT_COOLDOWN_SECONDS=120" in content
    assert "OPENAI_API_KEY=" in content
    assert "LIVE_REFRESH_MIN_GAP_SECONDS=600" in content
    assert "SCRAPING_OBSERVER_ENABLED=false" in content
    assert "SCRAPING_MIN_GAP_SECONDS=600" in content
    assert "PERSONAL_OBSERVER_ENABLED=false" in content
    assert "PERSONAL_OBSERVER_ARTIFACT_ROOT=.local/browser-artifacts" in content
    assert "PERSONAL_OBSERVER_NAVIGATION_TIMEOUT_MS=45000" in content
    assert "PERSONAL_OBSERVER_READY_SELECTOR=" in content
    assert "PERSONAL_OBSERVER_READY_TIMEOUT_MS=15000" in content
    assert "PERSONAL_OBSERVER_WAIT_FOR_NETWORK_IDLE=false" in content
    assert "PERSONAL_OBSERVER_MANUAL_CHECKPOINT_SECONDS=0" in content
    assert "PERSONAL_OBSERVER_SAVE_RUNTIME_MANIFESTS=false" in content
    assert "PERSONAL_OBSERVER_PROFILE_LOCK_TIMEOUT_SECONDS=0" in content
    assert "PERSONAL_OBSERVER_PROFILE_LOCK_STALE_SECONDS=3600" in content
    assert "PERSONAL_OBSERVER_REQUIRE_USER_ACTION=true" in content
    assert "PERSONAL_OBSERVER_AUTO_RUN=false" in content
    assert "SCRAPLING_USE_FETCHERS=false" in content
    assert "CRAWL4AI_ENABLED=false" in content
    assert "CRAWL4AI_MODE=library" in content
    assert "CRAWL4AI_BASE_URL=http://crawl4ai:11235" in content
    assert "CRAWL4AI_API_TOKEN=" in content
    assert "CRAWL4AI_TIMEOUT_SECONDS=30" in content
    assert "CRAWL4AI_IMAGE=unclecode/crawl4ai:0.8.9" in content
    assert "SEARXNG_ENABLED=false" in content
    assert "SEARXNG_BASE_URL=http://searxng:8080" in content
    assert "SEARXNG_IMAGE=searxng/searxng:2026.6.29-0e990f78a" in content
    assert "SEARXNG_IMAGE=searxng/searxng:latest" not in content
    assert "DEAL_DISCOVERY_JOB_DEADLINE_SECONDS=600" in content
    assert "DEAL_DISCOVERY_ALLOWED_HOSTS=" in content
    assert "RU_AGGREGATORS_ENABLED=aviasales_clickout,yandex_travel,tutu,onetwotrip" in content
    assert "CARRIER_LINKS_ENABLED=aeroflot,pobeda,s7,ural_airlines" in content
    assert "SOURCE_INTERNAL_RPM=10" in content
