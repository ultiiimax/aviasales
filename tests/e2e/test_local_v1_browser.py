from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import Page, expect

from flight_hunter.application.booking_actions import sign_booking_action_token

from .conftest import LocalServer

pytestmark = pytest.mark.browser_e2e


def test_root_ui_is_readable_and_has_no_mojibake(page: Page, local_server: LocalServer) -> None:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )

    page.goto(local_server.url, wait_until="networkidle")

    assert page.url == f"{local_server.url}/"
    assert page.title() == "Flight Hunter"
    expect(page.get_by_role("button", name="Собрать план")).to_be_visible()
    expect(page.get_by_role("heading", name="Отслеживания")).to_be_visible()
    content = page.content()
    assert not any(
        marker in content
        for marker in (
            "\u0420\u045c",
            "\u0420\u040e",
            "\u0432\u0402",
            "\u0440\u045f",
            "\u0420\u00a0\u0420",
        )
    )
    assert "Next.js Runtime Error" not in content
    assert console_errors == []


def test_owner_bootstrap_accept_and_me(page: Page, local_server: LocalServer) -> None:
    invitation = page.request.post(
        f"{local_server.url}/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": local_server.bootstrap_token},
        data={"household_name": "E2E Family", "recipient_label": "owner"},
    )
    assert invitation.status == 201
    accepted = page.request.post(
        f"{local_server.url}/api/v1/auth/accept-invitation",
        data={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "E2E Owner",
        },
    )
    assert accepted.status == 201
    session = accepted.json()

    me = page.request.get(
        f"{local_server.url}/api/v1/auth/me",
        headers=_auth_headers(session["session_token"]),
    )

    assert me.status == 200
    assert me.json()["role"] == "owner"
    assert me.json()["user_id"] == session["user_id"]
    assert me.json()["household_id"] == session["household_id"]


def test_fake_exact_search_renders_source_freshness_and_passengers(
    page: Page,
    local_server: LocalServer,
) -> None:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type in {"error", "warning"}
        else None,
    )
    page.goto(local_server.url, wait_until="networkidle")
    page.locator(".exact-search > summary").click()
    page.locator('input[name="origin"]').fill("MOW")
    page.locator('input[name="destination"]').fill("LED")
    page.locator('input[name="departure_date"]').fill("2026-09-15")
    page.locator('input[name="return_date"]').fill("")
    page.locator('input[name="adults"]').fill("1")
    page.get_by_role("button", name="Найти билеты").click()

    result = page.locator("#results-list .result-row").first
    expect(result).to_be_visible()
    expect(result).to_contain_text("MOW → LED")
    expect(result).to_contain_text("1 пасс.")
    expect(result).to_contain_text("cached")
    response = page.request.post(
        f"{local_server.url}/api/v1/searches",
        data=_search_payload(provider_ids=["fake"]),
    )
    assert response.status == 201
    assert response.json()["offers"][0]["provider_id"] == "fake"
    assert response.json()["offers"][0]["freshness"] == "cached"
    assert console_errors == []


def test_watch_lifecycle_and_empty_history(page: Page, local_server: LocalServer) -> None:
    session = _create_owner_session(page, local_server)
    headers = _auth_headers(session["session_token"])
    created = page.request.post(
        f"{local_server.url}/api/v1/watches",
        headers=headers,
        data={
            "origin": "MOW",
            "destination": "LED",
            "departure_date": "2026-09-15",
            "return_date": None,
            "passengers": 1,
            "currency": "RUB",
            "allowed_provider_ids": ["fake"],
        },
    )
    assert created.status == 201
    watch = created.json()
    watch_url = f"{local_server.url}/api/v1/watches/{watch['id']}"

    history = page.request.get(f"{watch_url}/history", headers=headers)
    paused = page.request.post(f"{watch_url}/pause", headers=headers, data={})
    resumed = page.request.post(f"{watch_url}/resume", headers=headers)
    archived = page.request.post(
        f"{watch_url}/archive",
        headers=headers,
        data={"expected_version": resumed.json()["version"]},
    )

    assert history.status == 200
    assert history.json()["snapshots"] == []
    assert paused.json()["paused_until"] is not None
    assert resumed.json()["paused_until"] is None
    assert archived.json()["status"] == "archived"


def test_booking_token_success_tamper_and_expiry(page: Page, booking_server: LocalServer) -> None:
    page.goto(booking_server.url, wait_until="networkidle")
    search = page.request.post(
        f"{booking_server.url}/api/v1/searches",
        data=_search_payload(provider_ids=["aviasales_search"]),
    )
    assert search.status == 201
    token = search.json()["offers"][0]["booking_action_token"]
    assert token

    success = page.request.post(
        f"{booking_server.url}/api/v1/booking-actions/resolve",
        data={"token": token},
    )
    tampered = page.request.post(
        f"{booking_server.url}/api/v1/booking-actions/resolve",
        data={"token": token[:-1] + ("A" if token[-1] != "A" else "B")},
    )
    expired_token = sign_booking_action_token(
        secret_key=booking_server.app_secret_key,
        provider_id="aviasales_search",
        ref=json.dumps(
            {
                "provider_id": "aviasales_search",
                "proposal_id": "p1",
                "results_url": "e2e-results.example",
                "search_id": "s1",
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
        now=datetime.now(UTC) - timedelta(minutes=5),
        ttl_seconds=1,
    )
    expired = page.request.post(
        f"{booking_server.url}/api/v1/booking-actions/resolve",
        data={"token": expired_token},
    )

    assert success.status == 200
    assert success.json() == {"status": "resolved", "url": "https://gate.example/e2e-buy"}
    assert tampered.status == 400
    assert tampered.json()["detail"] == "booking_action_token_tampered"
    assert expired.status == 400
    assert expired.json()["detail"] == "booking_action_token_expired"


def test_disabled_aviasales_has_stable_message(page: Page, local_server: LocalServer) -> None:
    response = page.request.get(f"{local_server.url}/api/v1/aviasales/suggest?q=LED")

    assert response.status == 503
    assert response.json() == {
        "code": "aviasales_search_disabled",
        "message": "provider is disabled",
    }


def test_health_and_readiness_are_green(page: Page, local_server: LocalServer) -> None:
    health = page.request.get(f"{local_server.url}/healthz")
    ready = page.request.get(f"{local_server.url}/readyz")

    assert health.status == 200
    assert health.json()["status"] == "ok"
    assert ready.status == 200
    assert ready.json()["status"] == "ready"


def _create_owner_session(page: Page, server: LocalServer) -> dict[str, str]:
    invitation = page.request.post(
        f"{server.url}/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": server.bootstrap_token},
        data={"household_name": "E2E Family", "recipient_label": "owner"},
    )
    assert invitation.status == 201
    accepted = page.request.post(
        f"{server.url}/api/v1/auth/accept-invitation",
        data={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "E2E Owner",
        },
    )
    assert accepted.status == 201
    return accepted.json()


def _auth_headers(session_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {session_token}"}


def _search_payload(*, provider_ids: list[str]) -> dict[str, object]:
    return {
        "origin": "MOW",
        "destination": "LED",
        "departure_date": "2026-09-15",
        "return_date": None,
        "passengers": 1,
        "currency": "RUB",
        "provider_ids": provider_ids,
    }
