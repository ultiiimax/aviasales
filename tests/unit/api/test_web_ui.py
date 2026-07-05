from __future__ import annotations

import re

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_root_serves_search_screen_without_cached_radar_or_secrets() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Flight Hunter" in response.text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in response.text
    assert '<meta name="theme-color" content="#126d7a">' in response.text
    assert 'navigator.serviceWorker.register("/service-worker.js")' in response.text
    assert 'id="search-form"' in response.text
    assert "/api/v1/providers" in response.text
    assert "/api/v1/searches" in response.text
    assert "/api/v1/browser-sources" in response.text
    assert "/api/v1/live-observation-grants" in response.text
    assert "/api/v1/live-observations" in response.text
    assert "/api/v1/personal-observations/grants" in response.text
    assert "/api/v1/personal-observations" in response.text
    assert "/api/v1/deals/discover" in response.text
    assert "/api/v1/manual-price-confirmations" in response.text
    assert "/api/v1/auth/accept-invitation" in response.text
    assert "/api/v1/auth/me" in response.text
    assert "/api/v1/watches" in response.text
    assert "/api/v1/admin/providers/health" in response.text
    assert "/api/v1/admin/sources/health" in response.text
    assert "/api/v1/admin/workers/health" in response.text
    assert "/api/v1/admin/audit-events" in response.text
    assert "/api/v1/agent/presets" in response.text
    assert "/api/v1/agent/plan" in response.text
    assert "/api/v1/agent/chat/turn" in response.text
    assert "/api/v1/airports/search" in response.text
    assert 'id="watches-heading"' in response.text
    assert 'id="watch-list"' in response.text
    assert 'id="watch-history-list"' in response.text
    assert 'id="create-watch-button"' in response.text
    assert 'id="refresh-watches-button"' in response.text
    assert 'id="admin-health-list"' in response.text
    assert 'id="audit-list"' in response.text
    assert 'id="airport-choice-list"' in response.text
    assert 'id="agent-action-list"' in response.text
    assert 'id="confirmation-list"' in response.text
    assert "function authHeaders" in response.text
    assert "function acceptInvitation" in response.text
    assert "function recordManualConfirmation" in response.text
    assert "function renderManualConfirmations" in response.text
    assert "function renderWatches" in response.text
    assert "function loadWatches" in response.text
    assert "function createWatchFromSearch" in response.text
    assert "function pauseWatch" in response.text
    assert "function resumeWatch" in response.text
    assert "function loadWatchHistory" in response.text
    assert "function renderAdminHealth" in response.text
    assert "function loadAdminHealth" in response.text
    assert "function renderAuditEvents" in response.text
    assert "function loadAuditEvents" in response.text
    assert "function providerHelp" in response.text
    assert "function syncExtractedRoute" in response.text
    assert "ranking_reasons" in response.text
    assert "offer.risk" in response.text
    assert "riskLevelLabel" in response.text
    assert "priced_offers" in response.text
    assert "external_links" in response.text
    assert "browser_observed_offers" in response.text
    assert "deal_candidates" in response.text
    assert "freshness_summary" in response.text
    assert 'join("\\n\\n")' in response.text
    assert 'join("\n\n")' not in response.text

    assert 'name="min_price_minor"' not in response.text
    assert 'name="max_price_minor"' not in response.text
    assert "grant_token" not in response.text
    assert "secret" not in response.text.lower()
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        response.text,
        flags=re.IGNORECASE,
    )


def test_pwa_manifest_and_service_worker_do_not_cache_api_prices() -> None:
    client = TestClient(create_app())

    manifest_response = client.get("/manifest.webmanifest")
    icon_response = client.get("/pwa-icon.svg")
    worker_response = client.get("/service-worker.js")

    assert manifest_response.status_code == 200
    assert "application/manifest+json" in manifest_response.headers["content-type"]
    manifest = manifest_response.json()
    assert manifest["name"] == "Flight Hunter"
    assert manifest["start_url"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#126d7a"
    assert manifest["icons"][0]["src"] == "/pwa-icon.svg"
    assert icon_response.status_code == 200
    assert "image/svg+xml" in icon_response.headers["content-type"]
    assert worker_response.status_code == 200
    assert "application/javascript" in worker_response.headers["content-type"]
    assert 'const SHELL_URLS = ["/", "/manifest.webmanifest", "/pwa-icon.svg"];' in (
        worker_response.text
    )
    assert 'url.pathname.startsWith("/api/")' in worker_response.text
    assert "fetch(event.request)" in worker_response.text
