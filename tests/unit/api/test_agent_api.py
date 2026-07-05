from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from flight_hunter.agent.chat import IntentDraft
from flight_hunter.api.app import create_app
from flight_hunter.config import AppSettings
from flight_hunter.persistence.models import mapper_registry

HOUSEHOLD_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_A = "aaaaaaaa-0000-0000-0000-000000000001"


def test_agent_presets_endpoint_lists_beginner_presets() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/agent/presets")

    assert response.status_code == 200
    body = response.json()
    preset_ids = {preset["id"] for preset in body["presets"]}
    assert "flexible_dates" in preset_ids
    assert "hidden_city" in preset_ids
    assert "geo_currency" in preset_ids
    assert body["mode"]["provider"] == "deterministic_presets"


def test_agent_plan_endpoint_returns_safe_plan() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/agent/plan",
        json={
            "preset_id": "flexible_dates",
            "slots": {
                "origin": "WAW",
                "destination": "BCN",
                "departure_date": "2026-10-12",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preset_id"] == "flexible_dates"
    assert body["missing_slots"] == []
    assert body["steps"][0]["action"] == "build_date_matrix"
    assert body["steps"][0]["requires_live_refresh"] is False


def test_agent_plan_endpoint_does_not_guess_missing_fields() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/agent/plan",
        json={"preset_id": "buy_timing", "slots": {"origin": "WAW"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_slots"] == ["destination", "departure_date"]
    assert body["steps"] == []


def test_agent_plan_endpoint_rejects_unknown_preset_cleanly() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/agent/plan",
        json={"preset_id": "unknown", "slots": {}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown agent preset"


def test_airport_search_endpoint_accepts_city_names_and_aliases() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/airports/search", params={"q": "Варшава"})

    assert response.status_code == 200
    body = response.json()
    assert [airport["iata_code"] for airport in body["airports"][:2]] == ["WAW", "WMI"]
    assert body["import_status"]["source"] in {"demo", "ourairports"}


def test_airport_search_endpoint_accepts_spb_and_shanghai_aliases() -> None:
    client = TestClient(create_app())

    spb_response = client.get("/api/v1/airports/search", params={"q": "спб"})
    shanghai_response = client.get("/api/v1/airports/search", params={"q": "Шанхай"})

    assert spb_response.status_code == 200
    assert shanghai_response.status_code == 200
    assert [airport["iata_code"] for airport in spb_response.json()["airports"]] == ["LED"]
    assert [airport["iata_code"] for airport in shanghai_response.json()["airports"][:2]] == [
        "PVG",
        "SHA",
    ]


@pytest.mark.anyio
async def test_agent_chat_turn_creates_watch_only_from_explicit_monitoring_request() -> None:
    session_factory = await _session_factory()
    client = TestClient(create_app(watch_session_factory=session_factory))

    response = client.post(
        "/api/v1/agent/chat/turn",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"message": "WAW BCN 2026-10-12 2026-10-19 следи"},
    )
    watches = client.get("/api/v1/watches", headers=_headers(HOUSEHOLD_A, USER_A))

    assert response.status_code == 200
    body = response.json()
    assert [action["kind"] for action in body["actions"]] == [
        "search_cached_offers",
        "build_date_matrix",
        "find_nearby_airports",
        "create_watch",
        "offer_live_check",
    ]
    assert UUID(body["actions"][3]["related_id"])
    assert "grant_token" not in response.text
    assert "WAW BCN 2026-10-12 2026-10-19 следи" not in response.text
    assert [watch["destination"] for watch in watches.json()["watches"]] == ["BCN"]


@pytest.mark.anyio
async def test_agent_chat_turn_returns_airport_choices_without_guessing() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    response = client.post(
        "/api/v1/agent/chat/turn",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"message": "из Варшавы в Барселону на неделю в октябре"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_slots"] == ["origin", "departure_date"]
    assert [item["iata_code"] for item in body["airport_options"]["origin"]] == ["WAW", "WMI"]
    assert [action["kind"] for action in body["actions"]] == [
        "clarify_airport_choice",
        "clarify_travel_dates",
    ]


@pytest.mark.anyio
async def test_agent_chat_turn_understands_spb_shanghai_month_query() -> None:
    client = TestClient(create_app(watch_session_factory=await _session_factory()))

    response = client.post(
        "/api/v1/agent/chat/turn",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"message": "Хочу из спб улететь в Шанхай в октябре"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["extracted"]["origin"] == "LED"
    assert body["extracted"]["destination"] is None
    assert body["extracted"]["date_hint"] == "октябрь"
    assert body["missing_slots"] == ["destination", "departure_date"]
    assert [item["iata_code"] for item in body["airport_options"]["origin"]] == ["LED"]
    assert [item["iata_code"] for item in body["airport_options"]["destination"][:2]] == [
        "PVG",
        "SHA",
    ]
    assert [action["kind"] for action in body["actions"]] == [
        "clarify_airport_choice",
        "clarify_travel_dates",
    ]
    assert "search_cached_offers" not in {action["kind"] for action in body["actions"]}
    assert body["runtime"]["backend"] == "deterministic_harness"
    assert body["runtime"]["agentic_loop"] == "policy_validated_tool_plan"
    assert body["runtime"]["live_calls_allowed"] is False


def test_agent_chat_turn_reports_openai_backend_when_configured_without_leaking_key() -> None:
    settings = _settings(
        agent_openai_enabled=True,
        openai_api_key="sk-test",
        agent_openai_model="gpt-5.5",
    )
    client = TestClient(
        create_app(settings=settings, agent_intent_adapter=NoopIntentAdapter(model="gpt-5.5"))
    )

    response = client.post(
        "/api/v1/agent/chat/turn",
        headers=_headers(HOUSEHOLD_A, USER_A),
        json={"message": "Хочу из спб улететь в Шанхай в октябре"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runtime"]["backend"] == "openai_responses"
    assert body["runtime"]["model"] == "gpt-5.5"
    assert body["runtime"]["fallback_backend"] == "deterministic_harness"
    assert "sk-test" not in response.text


def _headers(household_id: str, user_id: str) -> dict[str, str]:
    return {
        "X-Flight-Hunter-Household-Id": household_id,
        "X-Flight-Hunter-User-Id": user_id,
    }


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(mapper_registry.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


class NoopIntentAdapter:
    def __init__(self, *, model: str) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def extract_intent(self, message: str) -> IntentDraft | None:
        return None


def _settings(**overrides: object) -> AppSettings:
    values = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "aviasales_search_enabled": False,
        "aviasales_search_signature": None,
        "aviasales_search_marker": None,
        "aviasales_search_internal_rpm": 20,
        "telegram_enabled": False,
        "telegram_webhook_secret": None,
    }
    values.update(overrides)
    return AppSettings(**values)
