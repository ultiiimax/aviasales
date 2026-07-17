from __future__ import annotations

from re import compile as regex

import pytest
from playwright.sync_api import Page, expect

from .conftest import AgentLocalServer

pytestmark = pytest.mark.browser_e2e


def test_missing_date_offers_rolling_window_without_provider_calls(
    agent_page: Page,
    agent_server: AgentLocalServer,
) -> None:
    session = _create_owner_session(agent_page, agent_server)
    _open_authenticated_agent(agent_page, agent_server, session["session_token"])

    prompt = agent_page.locator("#assistant-form textarea")
    prompt.fill("Хочу самый дешёвый вариант полететь из СПб во Францию")
    agent_page.get_by_role("button", name="Собрать план").click()

    expect(agent_page.locator("#agent-plan-card")).to_be_visible()
    expect(agent_page.locator("#agent-plan-status")).to_contain_text(
        "Укажите дату или период поиска."
    )
    rolling = agent_page.get_by_role(
        "button",
        name=regex("Искать в ближайшие 90 дней"),
    )
    expect(rolling).to_be_visible()
    assert agent_server.gateway.calls == 0

    rolling.click()

    expect(agent_page.locator("#agent-plan-date-mode")).to_contain_text("rolling_90_days")
    estimate_text = agent_page.locator("#agent-plan-estimate").text_content()
    assert estimate_text is not None and "60" in estimate_text
    expect(agent_page.locator("#agent-plan-execute")).to_be_disabled()
    assert agent_server.gateway.calls == 0


def test_execute_survives_reload_and_renders_confirmed_separately_from_risky(
    agent_page: Page,
    agent_server: AgentLocalServer,
) -> None:
    console_errors: list[str] = []
    agent_page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )
    session = _create_owner_session(agent_page, agent_server)
    plan = _create_plan(
        agent_page,
        agent_server,
        session["session_token"],
        text="LED → CDG",
        selections={"departure_date": "2026-09-10"},
    )
    _open_authenticated_agent(
        agent_page,
        agent_server,
        session["session_token"],
        plan_id=plan["plan_id"],
    )

    execute_requests: list[str] = []
    agent_page.on(
        "request",
        lambda request: execute_requests.append(request.url)
        if request.url.endswith(f"/search-plans/{plan['plan_id']}/execute")
        else None,
    )
    execute = agent_page.locator("#agent-plan-execute")
    expect(execute).to_be_enabled()
    agent_page.evaluate(
        """
        () => {
          const button = document.getElementById("agent-plan-execute");
          button.click();
          button.click();
        }
        """
    )
    expect(agent_page.locator("#agent-run-progress")).to_contain_text("queued")
    agent_page.wait_for_timeout(200)
    assert len(execute_requests) == 1
    stored_run_id = agent_page.evaluate(
        "() => window.localStorage.getItem('flight_hunter_agent_run_id_v1')"
    )
    assert isinstance(stored_run_id, str) and stored_run_id

    agent_page.reload(wait_until="networkidle")

    expect(agent_page.locator("#agent-run-progress")).to_contain_text(stored_run_id[:8])
    terminal = agent_server.run_until_terminal(
        household_id=session["household_id"],
        run_id=stored_run_id,
    )
    assert terminal == "completed"
    expect(agent_page.locator("#agent-run-progress")).to_contain_text(
        "completed",
        timeout=15_000,
    )
    expect(agent_page.locator("#agent-confirmed-results")).to_be_visible()
    expect(agent_page.locator("#agent-confirmed-results-list")).to_contain_text("20")
    expect(agent_page.locator("#agent-confirmed-results-list")).to_contain_text("LED→CDG")
    expect(agent_page.locator("#agent-confirmed-results-list")).to_contain_text("CONFIRMED")
    expect(agent_page.locator("#agent-confirmed-results-list")).to_contain_text("aviasales_search")
    results_response = agent_page.request.get(
        f"{agent_server.url}/api/v1/agent/search-plans/{plan['plan_id']}"
        f"/runs/{stored_run_id}/results",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert results_response.status == 200
    ranking_reason = results_response.json()["candidates"][0]["rankings"][0]["reasons"][0]
    expect(agent_page.locator("#agent-confirmed-results-list")).to_contain_text(ranking_reason)
    expect(agent_page.locator("#agent-risky-results")).to_be_hidden()
    assert len(agent_server.gateway.start_calls) == 1
    assert len(agent_server.gateway.poll_calls) == 1

    health = agent_page.request.get(f"{agent_server.url}/api/v1/admin/workers/health")
    assert health.status == 200
    agent_health = health.json()["agent"]
    assert agent_health["run_status_counts"]["completed"] == 1
    assert agent_health["confirmed_candidates"] == 1
    assert agent_health["actual_http_attempts"] == 2
    assert console_errors == []


def test_hidden_city_ack_mobile_cancel_and_terminal_polling(
    agent_page: Page,
    agent_server: AgentLocalServer,
) -> None:
    session = _create_owner_session(agent_page, agent_server)
    plan = _create_plan(
        agent_page,
        agent_server,
        session["session_token"],
        text="LED → CDG",
        selections={
            "departure_date": "2026-09-10",
            "requested_strategies": ["hidden_city"],
        },
    )
    _open_authenticated_agent(
        agent_page,
        agent_server,
        session["session_token"],
        plan_id=plan["plan_id"],
    )
    agent_page.set_viewport_size({"width": 390, "height": 844})

    warning = agent_page.locator("#agent-hidden-city-warning")
    execute = agent_page.locator("#agent-plan-execute")
    expect(warning).to_be_visible()
    expect(execute).to_be_disabled()
    expect(agent_page.locator("#agent-plan-edit")).to_be_visible()
    expect(agent_page.locator("#agent-plan-full")).to_be_visible()
    expect(agent_page.locator("#agent-run-cancel")).to_be_visible()

    agent_page.locator("#agent-hidden-city-ack").check()
    expect(execute).to_be_enabled()
    execute.click()
    expect(agent_page.locator("#agent-run-progress")).to_contain_text("queued")
    cancel = agent_page.locator("#agent-run-cancel")
    expect(cancel).to_be_enabled()
    cancel.click()
    expect(agent_page.locator("#agent-run-progress")).to_contain_text("cancel_requested")
    run_id = agent_page.evaluate(
        "() => window.localStorage.getItem('flight_hunter_agent_run_id_v1')"
    )
    assert isinstance(run_id, str) and run_id

    terminal = agent_server.run_until_terminal(
        household_id=session["household_id"],
        run_id=run_id,
    )
    assert terminal == "cancelled"
    expect(agent_page.locator("#agent-run-progress")).to_contain_text(
        "cancelled",
        timeout=15_000,
    )
    expect(agent_page.locator("#agent-risky-results")).to_be_visible()
    expect(agent_page.locator("#agent-risky-results-list")).to_contain_text(
        "Hidden-city результаты недоступны"
    )
    assert agent_server.gateway.calls == 0


def _create_owner_session(page: Page, server: AgentLocalServer) -> dict[str, str]:
    invitation = page.request.post(
        f"{server.url}/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": server.bootstrap_token},
        data={"household_name": "Agent E2E household"},
    )
    assert invitation.status == 201
    accepted = page.request.post(
        f"{server.url}/api/v1/auth/accept-invitation",
        data={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "Agent E2E owner",
        },
    )
    assert accepted.status == 201
    return accepted.json()


def _create_plan(
    page: Page,
    server: AgentLocalServer,
    session_token: str,
    *,
    text: str,
    selections: dict[str, object],
) -> dict[str, object]:
    response = page.request.post(
        f"{server.url}/api/v1/agent/search-plans",
        headers={"Authorization": f"Bearer {session_token}"},
        data={"text": text, "coverage": "quick", "selections": selections},
    )
    assert response.status == 201
    return response.json()


def _open_authenticated_agent(
    page: Page,
    server: AgentLocalServer,
    session_token: str,
    *,
    plan_id: object | None = None,
) -> None:
    page.goto(server.url, wait_until="networkidle")
    page.evaluate(
        """
        ([token, storedPlanId]) => {
          window.localStorage.setItem("flight_hunter_session_token", token);
          if (storedPlanId) {
            window.localStorage.setItem("flight_hunter_agent_plan_id_v1", String(storedPlanId));
          }
        }
        """,
        [session_token, plan_id],
    )
    page.reload(wait_until="networkidle")
    expect(page.locator("#auth-state")).to_contain_text("Готово")
    if plan_id is not None:
        expect(page.locator("#agent-plan-card")).to_be_visible()
