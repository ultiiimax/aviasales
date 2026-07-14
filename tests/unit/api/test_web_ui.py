from __future__ import annotations

import re

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_web_ui_contains_readable_russian_without_mojibake() -> None:
    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert response.encoding.lower() == "utf-8"
    for text in ("Найти билеты", "Отслеживания", "Источник", "Недостаточно данных"):
        assert text in response.text
    for marker in (
        "\u0420\u045c",
        "\u0420\u040e",
        "\u0432\u0402",
        "\u0440\u045f",
        "\u0420\u00a0\u0420",
    ):
        assert marker not in response.text


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
    assert "function renderAgentPlan" in response.text
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


def test_web_ui_contains_accessible_durable_agent_plan_and_run_regions() -> None:
    html = TestClient(create_app()).get("/").text

    required_fragments = (
        'id="agent-plan-card"',
        'aria-labelledby="agent-plan-heading"',
        'id="agent-plan-status" role="status" aria-live="polite"',
        'id="agent-plan-scope"',
        'id="agent-plan-date-mode"',
        'id="agent-plan-passengers"',
        'id="agent-plan-coverage"',
        'id="agent-plan-strategies"',
        'id="agent-plan-hidden-city"',
        'id="agent-plan-estimate"',
        'id="agent-plan-rpm"',
        'id="agent-plan-deadline"',
        'id="agent-plan-source"',
        'id="agent-plan-expiry"',
        'id="agent-plan-execute"',
        'id="agent-plan-full"',
        'id="agent-plan-edit"',
        'id="agent-run-progress" role="status" aria-live="polite"',
        'id="agent-run-cancel"',
        'id="agent-risky-results"',
        'aria-labelledby="agent-risky-results-heading"',
        'id="agent-partial-errors" role="alert"',
    )
    for fragment in required_fragments:
        assert fragment in html


def test_web_agent_plan_javascript_is_approval_gated_reloadable_and_cancellable() -> None:
    html = TestClient(create_app()).get("/").text

    render = _javascript_sync_function(html, "renderAgentPlan")
    estimate = _javascript_sync_function(html, "agentEstimateLabel")
    idempotency = _javascript_sync_function(html, "freshIdempotencyKey")
    execute = _javascript_function(html, "executeAgentPlan")
    clone = _javascript_function(html, "cloneAgentPlanAsFull")
    revise = _javascript_function(html, "reviseAgentPlan")
    edit = _javascript_function(html, "editAgentPlan")
    reload = _javascript_function(html, "reloadAgentPlan")
    poll = _javascript_function(html, "pollAgentRun")
    cancel = _javascript_function(html, "cancelAgentRun")
    session_load = _javascript_function(html, "loadSessionBoundData")

    assert "/execute" in execute
    assert 'currentAgentPlan.state !== "awaiting_approval"' in execute
    assert "!currentAgentPlan.executable" in execute
    assert "currentAgentPlan.summary.hidden_city_enabled === true" in execute
    assert "hidden_city_warning_version" not in execute
    assert '"hidden-city-v1"' not in execute
    assert "revision_id" in execute
    assert "expected_revision" in execute
    assert "content_hash" in execute
    assert "freshIdempotencyKey()" in execute
    assert "/revisions" in clone
    assert 'coverage: "full"' in clone
    assert "freshIdempotencyKey()" in clone
    for terminal_state in ("consumed", "expired", "superseded"):
        assert f'"{terminal_state}"' in clone
    assert "cloneReady" in render
    assert "executeReady" in render
    assert "!hiddenCityEnabled" in render
    assert "нужно отдельное подтверждение риска" in render
    for budget_field in ("logical_operations", "calendar_searches", "exact_searches", "limit"):
        assert budget_field in estimate
    assert "crypto.getRandomValues" in idempotency
    assert "Math.random" not in idempotency
    assert "/runs/latest" in reload
    assert "renderAgentPlan" in reload
    assert "window.localStorage.getItem(agentPlanStorageKey)" in reload
    assert "response.status === 404" in reload
    assert "window.localStorage.removeItem(agentPlanStorageKey)" in reload
    assert "reloadAgentPlan()" in session_load
    assert "setTimeout" in poll
    assert "Math.min" in poll
    assert "pollAgentRun(latest, nextDelay), nextDelay" in poll
    assert 'status === "queued"' in poll
    assert 'status === "running"' in poll
    assert "/cancel" in cancel
    for cancellable_state in ("queued", "running"):
        assert f'"{cancellable_state}"' in cancel
    assert '"cancel_requested"' not in cancel
    assert 'method: "PATCH"' in revise
    assert "source_revision_id" in revise
    assert "expected_revision" in revise
    assert "selections" in revise
    assert 'method: "PATCH"' in edit
    assert "source_revision_id" in edit
    assert "expected_revision" in edit
    assert "text: prompt" in edit
    assert "agentEditMode ? editAgentPlan(prompt) : requestAgentChat(prompt)" in html
    assert (
        'getElementById("agent-plan-execute").addEventListener("click", executeAgentPlan)' in html
    )

    without_execute_function = html.replace(execute, "")
    assert "/execute" not in without_execute_function
    for state in ("partial", "failed", "cancelled"):
        assert f'"{state}"' in html
    for code in (
        "aviasales_search_rate_limited",
        "aviasales_search_blocked",
        "aviasales_search_unavailable",
        "agent_run_deadline_exceeded",
    ):
        assert code in html
    for false_claim in (
        "Багаж: нет",
        "Защита пересадки: нет",
        "Трансфер: 0",
        "Виза не нужна",
    ):
        assert false_claim not in html


def test_web_agent_entry_points_auth_render_and_revision_actions_share_plan_card() -> None:
    html = TestClient(create_app()).get("/").text
    chat = _javascript_function(html, "requestAgentChat")
    preset = _javascript_function(html, "requestAgentPlan")
    actions = _javascript_sync_function(html, "renderAgentActions")

    assert "authHeaders" in chat
    assert "renderAgentPlan(body.proposed_plan)" in chat
    assert "authHeaders" in preset
    assert "renderAgentPlan" in preset
    assert "reviseAgentPlan(action.parameters || {})" in actions
    assert "requestAgentChat" not in actions
    assert "unhandledrejection" in html
    assert "agent-operation-error" in html


def test_web_agent_plan_persists_only_versioned_plan_id_for_reload() -> None:
    html = TestClient(create_app()).get("/").text
    render = _javascript_sync_function(html, "renderAgentPlan")

    assert 'const agentPlanStorageKey = "flight_hunter_agent_plan_id_v1"' in html
    persisted_line = next(
        line for line in render.splitlines() if "localStorage.setItem(agentPlanStorageKey" in line
    )
    assert "String(plan.plan_id)" in persisted_line
    for forbidden in ("content_hash", "token", "booking", "signature"):
        assert forbidden not in persisted_line.lower()


def _javascript_function(html: str, name: str) -> str:
    match = re.search(
        rf"    async function {name}\([^)]*\) \{{.*?"
        rf"(?=\n    (?:async )?function |\n    document\.)",
        html,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing JavaScript function {name}"
    return match.group(0)


def _javascript_sync_function(html: str, name: str) -> str:
    match = re.search(
        rf"    function {name}\([^)]*\) \{{.*?(?=\n    (?:async )?function |\n    document\.)",
        html,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing JavaScript function {name}"
    return match.group(0)
