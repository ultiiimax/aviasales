from __future__ import annotations

import re

from fastapi.testclient import TestClient

from flight_hunter.api.app import create_app


def test_web_ui_uses_search_first_russian_hierarchy() -> None:
    html = TestClient(create_app()).get("/").text

    for class_name in (
        "hero-search",
        "account-menu",
        "exact-search",
        "technical-details",
    ):
        assert re.search(rf'class="[^"]*\b{class_name}\b[^"]*"', html)
    for text in (
        "Куда летим?",
        "Собрать план",
        "Задать точный маршрут",
        "Как работает поиск",
    ):
        assert text in html
    for old_heading in (">Agent cockpit<", ">Session<"):
        assert old_heading not in html


def test_exact_search_uses_accessible_typed_place_comboboxes_and_payloads() -> None:
    html = TestClient(create_app()).get("/").text

    for field in ("origin", "destination"):
        place_input = re.search(
            rf'<input[^>]+id="{field}-place-input"[^>]+'
            rf'role="combobox"[^>]+aria-autocomplete="list"[^>]+'
            rf'aria-controls="{field}-place-listbox"[^>]*>',
            html,
        )
        assert place_input is not None
        assert " required" not in place_input.group(0)
        assert f'<div class="place-field" data-place-role="{field}">' in html
        assert f'<label for="{field}-place-input">' in html
        assert f'name="{field}" type="hidden"' in html
        assert f'name="{field}_kind" type="hidden"' in html
        assert f'id="{field}-place-listbox" role="listbox"' in html
        assert f'id="{field}-place-status"' in html
        assert 'aria-live="polite"' in html

    combobox = _javascript_sync_function(html, "setupPlaceCombobox")
    payload = _javascript_sync_function(html, "buildSearchPayload")
    create_watch = _javascript_function(html, "createWatchFromSearch")

    assert "/api/v1/places/suggest?q=" in combobox
    assert "locale=ru&limit=10" in combobox
    assert "AbortController" in combobox
    assert "180" in combobox
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert key in combobox
    assert "aria-activedescendant" in combobox
    assert "getBoundingClientRect" in combobox
    assert "window.visualViewport?.height" in combobox
    assert "window.innerHeight" in combobox
    assert 'listbox.dataset.placement = "above"' in combobox
    assert '.place-listbox[data-placement="above"]' in html
    assert "textContent" in combobox
    assert "innerHTML" not in combobox
    assert "origin_kind" in payload
    assert "destination_kind" in payload
    assert "payload.origin_kind" in create_watch
    assert "payload.destination_kind" in create_watch
    assert "Сначала выберите города или аэропорты из списка" in html


def test_routes_use_shared_typed_place_lookup_and_honest_human_labels() -> None:
    html = TestClient(create_app()).get("/").text

    cache_key = _javascript_sync_function(html, "placeCacheKey")
    lookup = _javascript_function(html, "lookupPlaceRefs")
    label = _javascript_sync_function(html, "formatPlaceLabel")
    cached_route = _javascript_sync_function(html, "formatPlaceRouteFromCache")
    combobox = _javascript_sync_function(html, "setupPlaceCombobox")
    watch_lookup = _javascript_function(html, "lookupWatchPlaces")
    results = _javascript_sync_function(html, "renderResults")
    watches = _javascript_sync_function(html, "renderWatches")
    watch_history = _javascript_sync_function(html, "renderWatchHistory")
    external_route = _javascript_sync_function(html, "formatExternalRoute")
    search_lookup = _javascript_function(html, "lookupSearchResultPlaces")
    confirmed = _javascript_sync_function(html, "renderAgentConfirmedResults")

    assert "kind|code|locale|directory_version" in html
    assert "`${kind}|${code}|${locale}|${directoryVersion}`" in cache_key
    assert 'fetch("/api/v1/places/lookup"' in lookup
    assert "placeLookupBatchLimit = 64" in html
    assert "slice(offset, offset + placeLookupBatchLimit)" in lookup
    assert "!cachedPlaceOption(ref, directoryVersion)" in lookup
    assert "|| cachedPlaceOption(ref)" not in lookup
    assert "cachedPlaceOption(originRef, directoryVersion)" in cached_route
    assert "cachedPlaceOption(destinationRef, directoryVersion)" in cached_route
    assert "cachePlaceOption(option)" in combobox
    assert "Название не найдено" in label
    assert "watch.directory_version" in watch_lookup
    assert "lookupPlaceRefs(refs, directoryVersion)" in watch_lookup
    assert "body.requested_route" in results
    assert "offer.segments" in results
    assert "watch.origin_kind" in watches
    assert "watch.destination_kind" in watches
    assert "watch.directory_version" in watches
    assert "watch.directory_version" in watch_history
    assert "body?.external_links" in search_lookup
    assert '{kind: "airport", code}' in search_lookup
    assert '{kind: "city", code}' in search_lookup
    assert "lookupPlaceRefs(lookupRefs, directoryVersion)" in search_lookup
    assert "cachedPlaceOption" in external_route
    assert "resolved.length === 1" in external_route
    assert "candidate.ordered_legs" in confirmed
    for renderer in (results, watches, confirmed):
        assert "formatPlace" in renderer
        assert "textContent" in renderer


def test_carrier_logo_uses_fixed_origin_and_one_shot_fallback() -> None:
    html = TestClient(create_app()).get("/").text

    carrier_strip = _javascript_sync_function(html, "appendCarrierStrip")
    priced_offers = _javascript_sync_function(html, "renderResults")
    confirmed = _javascript_sync_function(html, "renderAgentConfirmedResults")
    agent_results = _javascript_sync_function(html, "renderAgentRunResults")

    assert "const carrierCodePattern = /^[A-Z0-9]{2}$/;" in html
    assert 'const carrierLogoOrigin = "https://pics.avs.io/80/80/";' in html
    assert "carrierCodePattern.test(code)" in carrier_strip
    assert "const identity = safeCode" in carrier_strip
    assert "identityKeys" not in carrier_strip
    assert "`${carrierLogoOrigin}${encodeURIComponent(carrier.code)}.png`" in carrier_strip
    assert "slice(0, 3)" in carrier_strip
    assert "carrier-logo-failed" in carrier_strip
    assert 'image.removeAttribute("src")' in carrier_strip
    assert "image.hidden = true" in carrier_strip
    assert "{once: true}" in carrier_strip
    assert 'image.loading = "lazy"' in carrier_strip
    assert "monogram" in carrier_strip
    assert "Авиакомпания не указана" in carrier_strip
    assert "airline_name" in carrier_strip
    assert "label.textContent" in carrier_strip
    assert "innerHTML" not in carrier_strip
    assert "appendCarrierStrip(row, offer.segments)" in priced_offers
    assert "appendCarrierStrip(card, candidate.segments)" in confirmed
    assert "candidate.flown_segments" in agent_results
    assert "candidate.skipped_segments" in agent_results
    assert "appendCarrierStrip(card, hiddenCitySegments)" in agent_results


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
    assert '<meta name="theme-color" content="#155eef">' in response.text
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
    assert manifest["theme_color"] == "#155eef"
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
        'id="agent-fare-analysis"',
        'aria-labelledby="agent-fare-analysis-heading"',
        'id="agent-fare-analysis-list"',
        'id="agent-confirmed-results"',
        'aria-labelledby="agent-confirmed-results-heading"',
        'id="agent-confirmed-results-list"',
        'id="agent-risky-results"',
        'aria-labelledby="agent-risky-results-heading"',
        'id="agent-partial-errors" role="alert"',
    )
    for fragment in required_fragments:
        assert fragment in html

    render_results = _javascript_sync_function(html, "renderAgentRunResults")
    assert "renderAgentConfirmedResults(results)" in render_results
    assert "results.hidden_city_candidates" in render_results


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
    assert "currentAgentPlan.summary.hidden_city_enabled === true" not in execute
    assert "hidden_city_warning_version" in execute
    assert "summary.hidden_city_warning_version" in execute
    assert "agent-hidden-city-ack" in execute
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
    assert "summary.hidden_city_warnings" in render
    assert "agent-hidden-city-warning" in render
    assert "agent-hidden-city-ack" in render
    assert "checked = false" in render
    assert "!hiddenCityEnabled" in render
    assert "нужно отдельное подтверждение риска" in render
    for budget_field in ("logical_operations", "calendar_searches", "exact_searches", "limit"):
        assert budget_field in estimate
    assert "crypto.getRandomValues" in idempotency
    assert "Math.random" not in idempotency
    assert "}/runs`" in reload
    assert "runList.runs" in reload
    assert "renderAgentPlan" in reload
    assert "window.localStorage.getItem(agentPlanStorageKey)" in reload
    assert "response.status === 404" in reload
    assert "window.localStorage.removeItem(agentPlanStorageKey)" in reload
    assert "reloadAgentPlan()" in session_load
    assert "setTimeout" in poll
    assert "Math.min" in poll
    assert "pollAgentRun(latest, nextDelay, sessionGeneration)" in poll
    assert "nextDelay" in poll
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


def test_web_hidden_city_results_are_fetched_into_a_separate_actionless_section() -> None:
    html = TestClient(create_app()).get("/").text

    render = _javascript_sync_function(html, "renderAgentRunResults")
    load = _javascript_function(html, "loadAgentRunResults")
    poll = _javascript_function(html, "pollAgentRun")
    reload = _javascript_function(html, "reloadAgentPlan")

    assert "hidden_city_candidates" in render
    assert "booking_action_available" in render
    assert "watch_available" in render
    assert "candidate.source_id" in render
    assert "candidate.observed_at" in render
    assert "LIVE" in render
    assert "Покупка и отслеживание отключены" in render
    assert "createWatchFromSearch" not in render
    assert "/results" in load
    assert "renderAgentRunResults" in load
    assert "loadAgentRunResults" in poll
    assert "loadAgentRunResults" in reload


def test_web_fare_analysis_uses_honest_evidence_gated_wording() -> None:
    html = TestClient(create_app()).get("/").text

    render = _javascript_sync_function(html, "renderAgentFareAnalysis")
    create_watch = _javascript_function(html, "createWatchFromAgentAnalysis")
    run_results = _javascript_sync_function(html, "renderAgentRunResults")

    assert "buy_timing" in render
    assert "Недостаточно данных" in render
    assert "полного маршрута" in render
    assert "исторически низкая" in render
    assert "recommended_weekday" in render
    assert "weekday_savings_percent" in render
    assert "recommended_four_hour_bucket" in render
    assert "four_hour_savings_percent" in render
    assert "Подозрение на аномально низкую цену" in render
    assert "не гарантия ошибочного тарифа" in render
    assert "FX-провайдер не настроен" in render
    assert "Экономия не рассчитана" in render
    assert "watch_action_available" in render
    assert "Создать отдельный мониторинг цены" in render
    assert "не увеличивает выборку этого анализа" in render
    assert "для накопления истории" not in render
    assert "createWatchFromAgentAnalysis" in render
    assert "положительная экономия не подтверждена" in render
    assert "savings_minor_units ?? 0" not in render
    assert "formatMinorAmount" in render
    assert "currency.reference_amount.minor_units" in render
    assert "currency.candidate_amount.minor_units" in render
    assert "analysis.provider_id" in render
    assert "analysis.freshness" in render
    assert "analysis.passengers" in render
    assert "analysis.observed_at" in render
    assert 'fetch("/api/v1/watches"' in create_watch
    assert "action.origin" in create_watch
    assert "action.destination" in create_watch
    assert "action.departure_date" in create_watch
    assert "action.return_date" in create_watch
    assert "action.passengers" in create_watch
    assert "action.currency" in create_watch
    assert "renderAgentFareAnalysis(results.analysis)" in run_results


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


def test_web_empty_clarification_action_enters_current_plan_edit_mode() -> None:
    html = TestClient(create_app()).get("/").text
    revise = _javascript_function(html, "reviseAgentPlan")

    assert "beginAgentPlanEdit()" in revise
    assert "return" in revise
    assert "agentEditMode ? editAgentPlan(prompt) : requestAgentChat(prompt)" in html


def test_web_signed_out_state_clears_agent_card_and_invalidates_polling() -> None:
    html = TestClient(create_app()).get("/").text
    clear_agent = _javascript_sync_function(html, "clearAgentSessionState")
    clear_session = _javascript_sync_function(html, "clearSession")
    signed_out = _javascript_sync_function(html, "renderSignedOutState")
    refresh = _javascript_function(html, "refreshSessionState")
    poll = _javascript_function(html, "pollAgentRun")

    assert "agentSessionGeneration += 1" in clear_agent
    assert "currentAgentPlan = null" in clear_agent
    assert "currentAgentRun = null" in clear_agent
    assert "agentEditMode = false" in clear_agent
    assert 'getElementById("agent-plan-card").hidden = true' in clear_agent
    for control in ("agent-plan-execute", "agent-plan-full", "agent-plan-edit", "agent-run-cancel"):
        assert f'getElementById("{control}").disabled = true' in clear_agent
    for sensitive_region in ("agent-plan-status", "agent-run-progress", "agent-partial-errors"):
        assert sensitive_region in clear_agent
    assert "renderSignedOutState()" in clear_session
    assert "clearAgentSessionState()" in signed_out
    assert "clearSession()" in refresh
    assert "sessionGeneration !== agentSessionGeneration" in poll
    assert "!sessionToken()" in poll


def test_web_auth_refresh_is_bound_to_exact_session_identity() -> None:
    html = TestClient(create_app()).get("/").text
    identity = _javascript_sync_function(html, "sessionIdentityIsCurrent")
    store = _javascript_sync_function(html, "storeSession")
    refresh = _javascript_function(html, "refreshSessionState")

    assert "clearAgentSessionState()" in store
    assert "token === sessionToken()" in identity
    assert "sessionGeneration === agentSessionGeneration" in identity
    assert "const sessionGeneration = agentSessionGeneration" in refresh

    guard = "if (!sessionIdentityIsCurrent(token, sessionGeneration)) return;"
    assert refresh.count(guard) == 3
    fetch_position = refresh.index('await fetch("/api/v1/auth/me"')
    response_guard_position = refresh.index(guard, fetch_position)
    response_status_position = refresh.index("if (!response.ok)")
    json_position = refresh.index("await response.json()")
    success_guard_position = refresh.index(guard, json_position)
    auth_ui_position = refresh.index("authState.textContent", success_guard_position)
    catch_position = refresh.index("} catch (error) {")
    error_guard_position = refresh.index(guard, catch_position)
    clear_position = refresh.index("clearSession()", error_guard_position)

    assert fetch_position < response_guard_position < response_status_position
    assert json_position < success_guard_position < auth_ui_position
    assert catch_position < error_guard_position < clear_position


def test_web_auth_refresh_clears_missing_or_current_session_only_once() -> None:
    html = TestClient(create_app()).get("/").text
    clear_session = _javascript_sync_function(html, "clearSession")
    signed_out = _javascript_sync_function(html, "renderSignedOutState")
    session_load = _javascript_function(html, "loadSessionBoundData")
    refresh = _javascript_function(html, "refreshSessionState")

    assert "clearAgentSessionState()" not in clear_session
    assert clear_session.count("renderSignedOutState()") == 1
    assert signed_out.count("clearAgentSessionState()") == 1
    assert refresh.count("clearSession()") == 2
    assert "renderSignedOutState()" not in refresh
    assert "if (!sessionToken()) return;" in session_load
    assert "renderSignedOutState()" not in session_load
    assert "if (!token) {\n        clearSession();\n        return;" in refresh
    assert (
        "if (!sessionIdentityIsCurrent(token, sessionGeneration)) return;\n"
        "        clearSession();\n"
        '        statusLine.textContent = "сессия истекла · войдите снова";'
    ) in refresh


def test_web_household_agent_actions_ignore_responses_from_old_session_generation() -> None:
    html = TestClient(create_app()).get("/").text
    action_names = (
        "requestAgentChat",
        "requestAgentPlan",
        "reviseAgentPlan",
        "editAgentPlan",
        "executeAgentPlan",
        "cloneAgentPlanAsFull",
        "cancelAgentRun",
    )

    for name in action_names:
        action = _javascript_function(html, name)
        assert "const sessionGeneration = agentSessionGeneration" in action, name
        assert "agentSessionFetch" in action, name
        assert "agentSessionIsCurrent(sessionGeneration)" in action, name


def test_web_renders_all_seven_agent_presets() -> None:
    html = TestClient(create_app()).get("/").text
    load = _javascript_function(html, "loadAgentPresets")

    assert "agentPresets.forEach" in load
    assert "slice(0, 5)" not in load


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


def test_web_agent_run_persists_only_versioned_id_and_blocks_duplicate_execute() -> None:
    html = TestClient(create_app()).get("/").text
    render_run = _javascript_sync_function(html, "renderAgentRun")
    execute = _javascript_function(html, "executeAgentPlan")
    reload = _javascript_function(html, "reloadAgentPlan")
    clear_agent = _javascript_sync_function(html, "clearAgentSessionState")
    confirmed = _javascript_sync_function(html, "renderAgentConfirmedResults")

    assert 'const agentRunStorageKey = "flight_hunter_agent_run_id_v1"' in html
    persisted_line = next(
        line
        for line in render_run.splitlines()
        if "localStorage.setItem(agentRunStorageKey" in line
    )
    assert "String(run.run_id)" in persisted_line
    for forbidden in ("content_hash", "token", "booking", "signature"):
        assert forbidden not in persisted_line.lower()

    assert "if (agentExecuteInFlight)" in execute
    assert "agentExecuteInFlight = true" in execute
    assert "const executeGeneration = ++agentExecuteGeneration" in execute
    assert "executeButton.disabled = true" in execute
    assert 'executeButton.setAttribute("aria-busy", "true")' in execute
    assert "finally" in execute
    assert "executeGeneration !== agentExecuteGeneration" in execute
    assert "agentExecuteInFlight = false" in execute
    assert 'executeButton.setAttribute("aria-busy", "false")' in execute

    assert "window.localStorage.getItem(agentRunStorageKey)" in reload
    assert "/runs/${encodeURIComponent(storedRunId)}" in reload
    assert "window.localStorage.removeItem(agentRunStorageKey)" in reload
    assert "run.revision_id !== plan.revision_id" in reload
    assert "item.revision_id === plan.revision_id" in reload
    assert ".at(-1)" in reload
    assert "agentExecuteGeneration += 1" in clear_agent

    assert "candidate.sources" in confirmed
    assert "candidate.rankings" in confirmed
    assert "ranking.reasons" in confirmed
    assert "candidate.provider_id" not in confirmed
    assert "candidate.freshness" not in confirmed
    assert "candidate.ranking_reasons" not in confirmed
    assert 'region.hidden = results.state === "not_ready"' in confirmed
    assert "agentExecuteInFlight || !executeReady" in html


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
