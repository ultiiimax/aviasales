# ruff: noqa: RUF001

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_root_serves_beginner_friendly_search_screen_without_secrets() -> None:
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
    assert "/api/v1/searches/cached-radar" in response.text
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
    assert "/history`" in response.text
    assert "/pause`" in response.text
    assert "/resume`" in response.text
    assert "/archive`" in response.text
    assert "/api/v1/admin/providers/health" in response.text
    assert "/api/v1/admin/sources/health" in response.text
    assert "/api/v1/admin/workers/health" in response.text
    assert "/api/v1/admin/workers/control" in response.text
    assert "function setWorkerDrain" in response.text
    assert "drain_requested" in response.text
    assert "Pause claims" in response.text
    assert "Resume claims" in response.text
    assert "current_job_kind" in response.text
    assert "current_job_id" in response.text
    assert "deal_jobs_processed" in response.text
    assert "telegram_notifications_seen" in response.text
    assert "Worker queues" in response.text
    assert "Worker alerts" in response.text
    assert "Stale lock monitor" in response.text
    assert "oldest_locked_age" in response.text
    assert "alert.code" in response.text
    assert "oldest_queued_age" in response.text
    assert "deadline_risk" in response.text
    assert "/api/v1/admin/audit-events" in response.text
    assert "/api/v1/agent/presets" in response.text
    assert "/api/v1/agent/plan" in response.text
    assert "/api/v1/agent/chat/turn" in response.text
    assert "/api/v1/airports/search" in response.text
    assert "agent-cockpit" in response.text
    assert 'id="runtime-strip"' in response.text
    assert 'id="agent-runtime"' in response.text
    assert 'id="agent-live-policy"' in response.text
    assert 'id="decision-rail"' in response.text
    assert "Human-in-the-loop" in response.text
    assert "Agent cockpit" in response.text
    assert "function renderAgentRuntime" in response.text
    assert 'document.createTextNode("\\n")' in response.text
    assert "flight_hunter_demo_household_id" in response.text
    assert "flight_hunter_session_token" in response.text
    assert "function authHeaders" in response.text
    assert "function acceptInvitation" in response.text
    assert 'id="auth-form"' in response.text
    assert 'id="auth-state"' in response.text
    assert '"Authorization": `Bearer ${token}`' in response.text
    assert 'id="watches-heading"' in response.text
    assert 'id="watch-list"' in response.text
    assert 'id="watch-history-list"' in response.text
    assert 'id="cached-radar-button"' in response.text
    assert 'id="cached-radar-list"' in response.text
    assert 'name="min_price_minor"' in response.text
    assert 'name="max_price_minor"' in response.text
    assert 'id="create-watch-button"' in response.text
    assert 'id="refresh-watches-button"' in response.text
    assert 'id="admin-health-heading"' in response.text
    assert 'id="admin-health-list"' in response.text
    assert 'id="refresh-admin-health-button"' in response.text
    assert 'id="audit-heading"' in response.text
    assert 'id="audit-list"' in response.text
    assert 'id="refresh-audit-button"' in response.text
    assert "X-Flight-Hunter-Household-Id" in response.text
    assert "X-Flight-Hunter-User-Id" in response.text
    assert 'id="airport-choice-list"' in response.text
    assert 'id="agent-action-list"' in response.text
    assert "Взрослые" in response.text
    assert "Проверить live" in response.text
    assert "Считать из браузера" in response.text
    assert "Найти акции" in response.text
    assert "flight-hunter-run-personal-observation" in response.text
    assert "ranking_reasons" in response.text
    assert "offer.risk" in response.text
    assert "riskLevelLabel" in response.text
    assert "provider_single_adult_ticket" in response.text
    assert "priced_offers" in response.text
    assert "external_links" in response.text
    assert "browser_observed_offers" in response.text
    assert "deal_candidates" in response.text
    assert "function dealCandidateExpiryLabel" in response.text
    assert "candidate.expires_at" in response.text
    assert "function buildCachedRadarPayload" in response.text
    assert "function renderCachedRadarResults" in response.text
    assert "function runCachedRadar" in response.text
    assert "price_range" in response.text
    assert "grouped_prices" in response.text
    assert "latest_prices" in response.text
    assert "month_matrix" in response.text
    assert "nearest_places_matrix" in response.text
    assert "popular_directions" in response.text
    assert "special_offers" in response.text
    assert "freshness_summary" in response.text
    assert 'id="confirmation-list"' in response.text
    assert "Цены из кэша" in response.text
    assert "Ссылки для проверки" in response.text
    assert "Свежие наблюдения из браузера" in response.text
    assert "Ручные подтверждения" in response.text
    assert "Совпала" in response.text
    assert "Нет мест" in response.text
    assert "function recordManualConfirmation" in response.text
    assert "function renderManualConfirmations" in response.text
    assert "function renderWatches" in response.text
    assert "function loadWatches" in response.text
    assert "function createWatchFromSearch" in response.text
    assert "function pauseWatch" in response.text
    assert "function resumeWatch" in response.text
    assert "function loadWatchHistory" in response.text
    assert "expected_version: watch.version" in response.text
    assert '"DELETE"' in response.text
    assert "Следить за маршрутом" in response.text
    assert "История watch" in response.text
    assert "function renderAdminHealth" in response.text
    assert "function loadAdminHealth" in response.text
    assert "function renderAuditEvents" in response.text
    assert "function loadAuditEvents" in response.text
    assert "Provider health" in response.text
    assert "Source health" in response.text
    assert "Worker health" in response.text
    assert "Household-scoped lifecycle log" in response.text
    assert "credentials present" in response.text
    assert "function providerHelp" in response.text
    assert "function syncExtractedRoute" in response.text
    assert "Не подключен" in response.text
    assert "API key" in response.text
    assert 'join("\\n\\n")' in response.text
    assert 'join("\n\n")' not in response.text
    assert "grant_token" not in response.text
    assert "TRAVELPAYOUTS_API_TOKEN" not in response.text
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
