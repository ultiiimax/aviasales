from __future__ import annotations

import json
from dataclasses import replace
from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.agent.chat import AgentChatService, IntentDraft
from flight_hunter.api.app import create_app
from flight_hunter.application.agent_lifecycle import AgentLifecycleError
from flight_hunter.config import AppSettings
from flight_hunter.persistence.models import agent_search_plan_revisions_table


class _ProviderCounter(Protocol):
    calls: int


class _Harness(Protocol):
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    household_id: str
    user_id: str
    provider: _ProviderCounter

    @property
    def auth_headers(self) -> dict[str, str]: ...


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("preset_id", "slots"),
    (
        (
            "buy_timing",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
        ),
        (
            "flexible_dates",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
        ),
        ("nearby_airports", {"origin": "LED", "destination": "CDG"}),
        (
            "hidden_city",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
        ),
        (
            "split_ticket",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
        ),
        ("error_fare_sources", {"region": "southern_europe"}),
        ("geo_currency", {"flight": "SU 100"}),
    ),
)
async def test_all_compatibility_presets_return_the_durable_revision_schema(
    agent_api_harness: _Harness,
    preset_id: str,
    slots: dict[str, object],
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={"preset_id": preset_id, "slots": slots},
    )

    assert response.status_code == 200
    body = response.json()
    assert {
        "plan_id",
        "revision_id",
        "revision",
        "state",
        "content_hash",
        "coverage",
        "executable",
        "enabled_strategies",
        "estimate",
        "clarifications",
        "summary",
        "created_at",
        "expires_at",
    } == set(body)
    assert body["revision"] == 1
    assert "steps" not in body
    assert "canonical_plan" not in response.text
    assert "scope_snapshot" not in response.text
    assert "provider_ref" not in response.text
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_compatibility_agent_endpoints_require_auth(agent_api_harness: _Harness) -> None:
    plan = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        json={"preset_id": "flexible_dates", "slots": {}},
    )
    chat = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        json={"message": "LED → CDG"},
    )

    assert plan.status_code == 401
    assert chat.status_code == 401
    assert plan.json()["code"] == "auth_context_missing"
    assert chat.json()["code"] == "auth_context_missing"


@pytest.mark.anyio
async def test_compatibility_plan_is_committed_and_reloadable_from_canonical_api(
    agent_api_harness: _Harness,
) -> None:
    created = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={
            "preset_id": "buy_timing",
            "slots": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-10-12",
            },
        },
    )

    assert created.status_code == 200
    plan = created.json()
    reloaded = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}",
        headers=agent_api_harness.auth_headers,
    )
    assert reloaded.status_code == 200
    assert reloaded.json()["revision_id"] == plan["revision_id"]


@pytest.mark.anyio
async def test_legacy_headers_remain_available_only_when_enabled(
    agent_api_harness: _Harness,
) -> None:
    settings = replace(AppSettings.from_env(), auth_allow_legacy_headers=True)
    client = TestClient(
        create_app(
            watch_session_factory=agent_api_harness.session_factory,
            settings=settings,
            agent_provider_gateway=agent_api_harness.provider,
        ),
        raise_server_exceptions=False,
    )
    response = client.post(
        "/api/v1/agent/plan",
        headers={
            "X-Flight-Hunter-Household-Id": agent_api_harness.household_id,
            "X-Flight-Hunter-User-Id": agent_api_harness.user_id,
        },
        json={
            "preset_id": "flexible_dates",
            "slots": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-10-12",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["plan_id"]
    assert agent_api_harness.provider.calls == 0
    client.close()


@pytest.mark.anyio
async def test_free_text_chat_returns_missing_date_plan_reference_without_provider_calls(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "missing-date"},
        json={"message": "Найди самый дешёвый вариант из СПб во Францию"},
    )

    assert response.status_code == 200
    body = response.json()
    plan = body["proposed_plan"]
    assert plan["state"] == "draft"
    assert plan["executable"] is False
    draft_scope = plan["summary"]["scope"][0]
    assert draft_scope["origin_kind"] == "city"
    assert draft_scope["origin_value"] == "LED"
    assert draft_scope["origin_airports"] == []
    assert draft_scope["destination_kind"] == "country"
    assert draft_scope["destination_value"] == "FR"
    assert draft_scope["destination_airports"] == []
    assert draft_scope["frozen"] is False
    assert plan["clarifications"][0]["code"] == "date_required"
    assert plan["clarifications"][0]["actions"][0]["action_id"] == ("use_rolling_90_days")
    assert body["outcome"] == "clarification"
    assert body["run"] is None
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_complete_chat_starts_once_and_same_key_replays_the_run(
    agent_api_harness: _Harness,
) -> None:
    headers = {**agent_api_harness.auth_headers, "Idempotency-Key": "chat-auto-run"}
    payload = {"message": "LED → CDG 2026-10-12"}

    first = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers=headers,
        json=payload,
    )
    replay = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers=headers,
        json=payload,
    )
    conflict = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers=headers,
        json={"message": "LED → CDG 2026-10-13"},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["outcome"] == "run_started"
    assert first.json()["run"]["status"] == "queued"
    assert replay.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    assert replay.json()["idempotent_replay"] is True
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "agent_run_idempotency_conflict"
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_explicit_watch_chat_creates_one_idempotent_watch(
    agent_api_harness: _Harness,
) -> None:
    headers = {**agent_api_harness.auth_headers, "Idempotency-Key": "chat-watch"}
    payload = {"message": "LED → CDG 2026-10-12, следи за ценой"}

    first = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers=headers,
        json=payload,
    )
    replay = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers=headers,
        json=payload,
    )
    watches = agent_api_harness.client.get(
        "/api/v1/watches",
        headers=agent_api_harness.auth_headers,
    )

    assert first.status_code == 200
    assert first.json()["outcome"] == "watch_created"
    assert replay.json()["watch_id"] == first.json()["watch_id"]
    assert len(watches.json()["watches"]) == 1
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_chat_rejects_unknown_date_mode_with_stable_typed_error(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "invalid-mode"},
        json={"message": "LED → CDG", "date_mode": "not_a_mode"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "agent_plan_invalid_input",
        "message": "agent plan input is invalid",
    }
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_chat_rejects_non_iso_departure_date_with_stable_typed_error(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "invalid-date"},
        json={"message": "LED → CDG", "departure_date": "not-a-date"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "agent_plan_invalid_input",
        "message": "agent plan input is invalid",
    }
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_chat_maps_public_lifecycle_error_without_internal_details(
    agent_api_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_turn(*_args: object, **_kwargs: object) -> None:
        raise AgentLifecycleError("agent_plan_invalid_input")

    monkeypatch.setattr(AgentChatService, "handle_turn", reject_turn)
    response = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "mapped-error"},
        json={"message": "LED → CDG"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "agent_plan_invalid_input",
        "message": "agent plan input is invalid",
    }
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_rolling_90_day_quick_plan_is_not_clamped_or_made_executable(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "rolling-window"},
        json={
            "message": "Найди самый дешёвый вариант из СПб во Францию",
            "date_mode": "rolling_90_days",
        },
    )

    assert response.status_code == 200
    plan = response.json()["proposed_plan"]
    assert plan["state"] == "draft"
    assert plan["executable"] is False
    assert plan["estimate"] is None
    budget = next(
        item for item in plan["clarifications"] if item["code"] == "quick_budget_too_large"
    )
    assert budget["details"]["calendar_searches"] == 90
    assert budget["details"]["exact_searches"] == 90
    assert budget["details"]["logical_operations"] == 180
    assert budget["details"]["limit"] == 60
    assert plan["summary"]["date_mode"] == "rolling_90_days"
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_bounded_plan_exposes_sanitized_frozen_plan_card_summary(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={
            "preset_id": "flexible_dates",
            "slots": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-10-12",
            },
        },
    )

    assert response.status_code == 200
    plan = response.json()
    assert plan["state"] == "awaiting_approval"
    assert plan["executable"] is True
    assert plan["coverage"] == "quick"
    assert plan["summary"] == {
        "trip_shape": "one_way",
        "date_mode": "flexible",
        "preset_id": "flexible_dates",
        "analysis_modes": [],
        "passengers": {
            "adults": 1,
            "children": 0,
            "infants": 0,
            "total": 1,
            "currency": "RUB",
        },
        "scope": [
            {
                "origin_kind": "airport",
                "origin_value": "LED",
                "origin_airports": ["LED"],
                "destination_kind": "airport",
                "destination_value": "CDG",
                "destination_airports": ["CDG"],
                "anywhere": False,
                "frozen": True,
                "reciprocal_anywhere_return": False,
                "nearby_radius_km": 0,
                "date_mode": "flexible",
                "date_start": "2026-10-09",
                "date_end": "2026-10-15",
                "flex_days": 3,
            }
        ],
        "provider": {
            "source_id": "aviasales_search",
            "capability_version": "mobile-contract-2026-07-13",
            "cost_model_version": "aviasales-v1",
            "requests_per_minute": 20,
        },
        "hidden_city_enabled": False,
        "hidden_city_warning_version": None,
        "hidden_city_warnings": [],
        "baggage_preference": "unspecified",
        "wants_watch": False,
    }
    assert plan["estimate"] == {
        "calendar_searches": 7,
        "exact_searches": 7,
        "logical_operations": 14,
        "http_attempts": 210,
        "deadline_seconds": 600,
    }
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_pre_task6_revision_reports_unknown_rpm_instead_of_inventing_default(
    agent_api_harness: _Harness,
) -> None:
    created = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "LED → CDG 2026-10-12",
            "coverage": "quick",
        },
    ).json()
    async with agent_api_harness.session_factory() as session:
        statement = update(agent_search_plan_revisions_table).where(
            agent_search_plan_revisions_table.c.id == created["revision_id"]
        )
        current = {
            "version": "aviasales-v1",
            "start_attempts": 3,
            "poll_rounds": 8,
            "attempts_per_poll": 3,
            "worst_case_exact_http_attempts": 27,
        }
        await session.execute(
            statement.values(cost_model_snapshot_json=json.dumps(current, sort_keys=True))
        )
        await session.commit()

    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{created['plan_id']}",
        headers=agent_api_harness.auth_headers,
    )

    assert fetched.status_code == 200
    assert fetched.json()["summary"]["provider"]["requests_per_minute"] is None
    assert UUID(fetched.json()["revision_id"])


@pytest.mark.anyio
async def test_canonical_compat_and_chat_share_the_same_frozen_runtime_settings(
    agent_api_harness: _Harness,
) -> None:
    settings = replace(
        AppSettings.from_env(),
        aviasales_search_internal_rpm=17,
    )
    client = TestClient(
        create_app(
            watch_session_factory=agent_api_harness.session_factory,
            settings=settings,
            agent_provider_gateway=agent_api_harness.provider,
        ),
        raise_server_exceptions=False,
    )
    canonical = client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={"text": "LED → CDG 2026-10-12", "coverage": "quick"},
    )
    compatibility = client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={
            "preset_id": "buy_timing",
            "slots": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-10-12",
            },
        },
    )
    chat = client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "shared-settings"},
        json={"message": "LED → CDG 2026-10-12"},
    )

    assert canonical.status_code == 201
    assert compatibility.status_code == 200
    assert chat.status_code == 200
    plans = (canonical.json(), compatibility.json(), chat.json()["proposed_plan"])
    assert {plan["summary"]["provider"]["requests_per_minute"] for plan in plans} == {17}
    assert {json.dumps(plan["estimate"], sort_keys=True) for plan in plans} == {
        json.dumps(
            {
                "calendar_searches": 0,
                "exact_searches": 1,
                "logical_operations": 1,
                "http_attempts": 27,
                "deadline_seconds": 600,
            },
            sort_keys=True,
        )
    }
    assert agent_api_harness.provider.calls == 0
    client.close()


@pytest.mark.anyio
async def test_nearby_preset_freezes_the_real_150_km_scope(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={
            "preset_id": "nearby_airports",
            "slots": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-10-12",
            },
        },
    )

    assert response.status_code == 200
    scope = response.json()["summary"]["scope"][0]
    assert scope["frozen"] is True
    assert scope["nearby_radius_km"] == 150
    assert "LED" in scope["origin_airports"]
    assert "CDG" in scope["destination_airports"]
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("preset_id", "slots", "analysis_mode"),
    (
        (
            "buy_timing",
            {"origin": "LED", "destination": "CDG", "departure_date": "2026-10-12"},
            "buy_timing",
        ),
        ("error_fare_sources", {"region": "southern_europe"}, "error_fare"),
        ("geo_currency", {"flight": "SU 100"}, "currency_compare"),
    ),
)
async def test_analysis_presets_keep_typed_mode_without_inventing_analysis(
    agent_api_harness: _Harness,
    preset_id: str,
    slots: dict[str, object],
    analysis_mode: str,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/plan",
        headers=agent_api_harness.auth_headers,
        json={"preset_id": preset_id, "slots": slots},
    )

    assert response.status_code == 200
    summary = response.json()["summary"]
    assert summary["preset_id"] == preset_id
    assert summary["analysis_modes"] == [analysis_mode]
    assert "analysis_result" not in response.text
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_configured_legacy_model_is_not_claimed_when_plan_parser_does_not_use_it(
    agent_api_harness: _Harness,
) -> None:
    settings = replace(
        AppSettings.from_env(),
        agent_openai_enabled=True,
        openai_api_key="sk-test",
        agent_openai_model="gpt-5.5",
    )
    client = TestClient(
        create_app(
            watch_session_factory=agent_api_harness.session_factory,
            settings=settings,
            agent_intent_adapter=NoopIntentAdapter(),
            agent_provider_gateway=agent_api_harness.provider,
        )
    )
    response = client.post(
        "/api/v1/agent/chat/turn",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "legacy-model"},
        json={"message": "LED → CDG 2026-10-12"},
    )

    assert response.status_code == 200
    assert response.json()["runtime"]["backend"] == "deterministic_gateway"
    assert response.json()["runtime"]["model"] is None
    assert "sk-test" not in response.text
    client.close()


class NoopIntentAdapter:
    @property
    def model(self) -> str:
        return "gpt-5.5"

    def extract_intent(self, _message: str) -> IntentDraft | None:
        return None


def test_agent_validation_handler_keeps_non_agent_validation_generic() -> None:
    response = TestClient(create_app()).post("/api/v1/auth/accept-invitation", json={})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert "code" not in response.json()
