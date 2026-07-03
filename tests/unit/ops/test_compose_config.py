from __future__ import annotations

from pathlib import Path


def test_deal_discovery_compose_profile_uses_pinned_internal_services() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    assert "searxng/searxng:2026.6.29-0e990f78a" in compose
    assert "unclecode/crawl4ai:0.8.9" in compose
    assert "searxng/searxng:latest" not in compose
    assert '"8080:8080"' not in compose
    assert '"11235:11235"' not in compose
    assert "http://searxng:8080" in compose
    assert "http://crawl4ai:11235" in compose
    assert 'CRAWL4AI_MODE: "${CRAWL4AI_MODE:-server}"' in compose
    assert "CRAWL4AI_API_TOKEN" in compose
    assert "CRAWL4AI_TIMEOUT_SECONDS" in compose
    assert "healthcheck:" in compose
    assert "crawl4ai_cache" in compose
