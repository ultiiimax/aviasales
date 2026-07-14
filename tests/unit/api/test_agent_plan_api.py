from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.persistence.models import agent_search_plan_revisions_table


class _ProviderCounter(Protocol):
    calls: int


class _Harness(Protocol):
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]
    session_token: str
    household_id: str
    user_id: str
    provider: _ProviderCounter

    @property
    def auth_headers(self) -> dict[str, str]: ...

    def create_second_session(self) -> dict[str, str]: ...


@pytest.mark.anyio
async def test_complete_and_incomplete_posts_return_typed_plan_cards_without_provider_calls(
    agent_api_harness: _Harness,
) -> None:
    complete = _create_plan(agent_api_harness)
    incomplete = _create_plan(agent_api_harness, with_date=False)

    assert complete.status_code == 201
    assert complete.json()["state"] == "awaiting_approval"
    assert complete.json()["revision"] == 1
    assert complete.json()["executable"] is True
    assert complete.json()["estimate"] == {
        "calendar_searches": 0,
        "exact_searches": 1,
        "logical_operations": 1,
        "http_attempts": 27,
        "deadline_seconds": 600,
    }
    assert "canonical_plan" not in complete.json()
    assert "scope_snapshot" not in complete.json()
    assert "provider_ref" not in complete.text

    assert incomplete.status_code == 201
    assert incomplete.json()["state"] == "draft"
    assert incomplete.json()["executable"] is False
    (clarification,) = incomplete.json()["clarifications"]
    assert clarification["field"] == "date_constraint"
    assert clarification["code"] == "date_required"
    assert clarification["actions"][0]["action_id"] == "use_rolling_90_days"
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_patch_creates_an_immutable_successor_and_get_returns_latest(
    agent_api_harness: _Harness,
) -> None:
    first = _create_plan(agent_api_harness).json()

    patched = agent_api_harness.client.patch(
        f"/api/v1/agent/search-plans/{first['plan_id']}",
        headers=agent_api_harness.auth_headers,
        json={
            "source_revision_id": first["revision_id"],
            "expected_revision": 1,
            "selections": {"departure_date": "2026-09-11"},
        },
    )
    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{first['plan_id']}",
        headers=agent_api_harness.auth_headers,
    )

    assert patched.status_code == 200
    assert patched.json()["revision"] == 2
    assert patched.json()["revision_id"] != first["revision_id"]
    assert patched.json()["content_hash"] != first["content_hash"]
    assert fetched.status_code == 200
    assert fetched.json()["revision_id"] == patched.json()["revision_id"]
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_execute_requires_real_bearer_and_never_trusts_legacy_household_headers(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    body = _execute_body(plan)

    missing = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={
            "Idempotency-Key": "execute-no-auth",
            "X-Flight-Hunter-Household-Id": agent_api_harness.household_id,
            "X-Flight-Hunter-User-Id": agent_api_harness.user_id,
        },
        json=body,
    )
    accepted = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "execute-plan-001"},
        json=body,
    )

    assert missing.status_code == 401
    assert missing.json()["code"] == "auth_context_missing"
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "queued"
    assert accepted.json()["revision_id"] == plan["revision_id"]
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("body_patch", "expected_code"),
    (
        ({"expected_revision": 2}, "agent_plan_stale"),
        ({"content_hash": "sha256:" + "0" * 64}, "agent_plan_stale"),
        ({"content_hash": None}, "agent_plan_approval_required"),
    ),
)
async def test_execute_rejects_stale_or_missing_approval_binding(
    agent_api_harness: _Harness,
    body_patch: dict[str, object],
    expected_code: str,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    body = {**_execute_body(plan), **body_patch}

    response = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "invalid-approval"},
        json=body,
    )

    assert response.status_code in {403, 409}
    assert response.json()["code"] == expected_code


@pytest.mark.anyio
async def test_execute_rejects_draft_expired_consumed_and_cross_household_revisions(
    agent_api_harness: _Harness,
) -> None:
    draft = _create_plan(agent_api_harness, with_date=False).json()
    draft_response = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{draft['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "draft-execute"},
        json=_execute_body(draft),
    )
    assert draft_response.status_code == 409
    assert draft_response.json()["code"] == "agent_plan_incomplete"

    expired = _create_plan(agent_api_harness).json()
    async with agent_api_harness.session_factory() as session:
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == expired["revision_id"])
            .values(expires_at=datetime(2020, 1, 1, tzinfo=UTC))
        )
        await session.commit()
    expired_response = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{expired['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "expired-execute"},
        json=_execute_body(expired),
    )
    assert expired_response.status_code == 410
    assert expired_response.json()["code"] == "agent_plan_expired"

    consumed = _create_plan(agent_api_harness).json()
    first_execute = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{consumed['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "consume-once"},
        json=_execute_body(consumed),
    )
    assert first_execute.status_code == 202
    consumed_response = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{consumed['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "consume-twice"},
        json=_execute_body(consumed),
    )
    assert consumed_response.status_code == 409
    assert consumed_response.json()["code"] == "agent_plan_consumed"

    other = agent_api_harness.create_second_session()
    cross_household = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{consumed['plan_id']}/execute",
        headers={
            "Authorization": f"Bearer {other['session_token']}",
            "Idempotency-Key": "cross-household",
        },
        json=_execute_body(consumed),
    )
    assert cross_household.status_code == 404
    assert cross_household.json()["code"] == "agent_plan_not_found"


@pytest.mark.anyio
async def test_hidden_city_requires_the_exact_warning_version(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness, hidden_city=True).json()
    missing = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "hidden-missing"},
        json=_execute_body(plan),
    )
    wrong = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "hidden-wrong"},
        json={**_execute_body(plan), "hidden_city_warning_version": "old-warning"},
    )
    accepted = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**agent_api_harness.auth_headers, "Idempotency-Key": "hidden-valid"},
        json={**_execute_body(plan), "hidden_city_warning_version": "hidden-city-v1"},
    )

    assert missing.status_code == 403
    assert missing.json()["code"] == "agent_hidden_city_ack_required"
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "agent_hidden_city_ack_required"
    assert accepted.status_code == 202


@pytest.mark.anyio
async def test_execute_and_terminal_clone_retries_return_original_resources(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    execute_headers = {
        **agent_api_harness.auth_headers,
        "Idempotency-Key": "same-execute-key",
    }
    first_run = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers=execute_headers,
        json=_execute_body(plan),
    )
    retried_run = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers=execute_headers,
        json=_execute_body(plan),
    )
    clone_headers = {**agent_api_harness.auth_headers, "Idempotency-Key": "clone-plan-001"}
    first_clone = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/revisions",
        headers=clone_headers,
        json={"source_revision_id": plan["revision_id"], "expected_revision": 1},
    )
    retried_clone = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/revisions",
        headers=clone_headers,
        json={"source_revision_id": plan["revision_id"], "expected_revision": 1},
    )

    assert first_run.status_code == 202
    assert retried_run.status_code == 202
    assert first_run.json()["run_id"] == retried_run.json()["run_id"]
    assert first_clone.status_code == 201
    assert retried_clone.status_code == 201
    assert first_clone.json()["revision_id"] == retried_clone.json()["revision_id"]
    assert first_clone.json()["revision"] == 2
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_clone_requires_idempotency_key(agent_api_harness: _Harness) -> None:
    plan = _create_plan(agent_api_harness).json()

    response = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/revisions",
        headers=agent_api_harness.auth_headers,
        json={"source_revision_id": plan["revision_id"], "expected_revision": 1},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"


@pytest.mark.anyio
async def test_cancel_list_latest_and_results_use_explicit_honest_states(
    agent_api_harness: _Harness,
) -> None:
    first_plan = _create_plan(agent_api_harness).json()
    second_plan = _create_plan(agent_api_harness).json()
    first_run = _execute(agent_api_harness, first_plan, "first-run").json()
    second_run = _execute(agent_api_harness, second_plan, "second-run").json()

    cancelled = agent_api_harness.client.post(
        f"/api/v1/agent/search-plans/{first_plan['plan_id']}/runs/{first_run['run_id']}/cancel",
        headers=agent_api_harness.auth_headers,
    )
    first_runs = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{first_plan['plan_id']}/runs",
        headers=agent_api_harness.auth_headers,
    )
    first_latest = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{first_plan['plan_id']}/runs/latest",
        headers=agent_api_harness.auth_headers,
    )
    second_fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{second_plan['plan_id']}/runs/{second_run['run_id']}",
        headers=agent_api_harness.auth_headers,
    )
    results = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{first_plan['plan_id']}/runs/{first_run['run_id']}/results",
        headers=agent_api_harness.auth_headers,
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["run_id"] == first_run["run_id"]
    assert cancelled.json()["status"] == "cancel_requested"
    assert first_runs.json()["runs"] == [cancelled.json()]
    assert first_latest.json() == cancelled.json()
    assert second_fetched.json()["status"] == "queued"
    assert results.status_code == 200
    assert results.json() == {
        "run_id": first_run["run_id"],
        "state": "not_ready",
        "evidence_available": False,
        "items": [],
    }


@pytest.mark.anyio
async def test_openapi_exposes_the_complete_agent_plan_lifecycle_surface(
    agent_api_harness: _Harness,
) -> None:
    paths = agent_api_harness.client.get("/openapi.json").json()["paths"]

    expected_methods = {
        "/api/v1/agent/search-plans": {"post"},
        "/api/v1/agent/search-plans/{plan_id}": {"get", "patch"},
        "/api/v1/agent/search-plans/{plan_id}/revisions": {"post"},
        "/api/v1/agent/search-plans/{plan_id}/execute": {"post"},
        "/api/v1/agent/search-plans/{plan_id}/runs": {"get"},
        "/api/v1/agent/search-plans/{plan_id}/runs/{run_id}": {"get"},
        "/api/v1/agent/search-plans/{plan_id}/runs/{run_id}/cancel": {"post"},
        "/api/v1/agent/search-plans/{plan_id}/runs/latest": {"get"},
        "/api/v1/agent/search-plans/{plan_id}/runs/{run_id}/results": {"get"},
    }
    for path, methods in expected_methods.items():
        assert methods <= set(paths[path])


def _create_plan(
    harness: _Harness,
    *,
    with_date: bool = True,
    hidden_city: bool = False,
):
    selections: dict[str, object] = {}
    if with_date:
        selections["departure_date"] = "2026-09-10"
    if hidden_city:
        selections["requested_strategies"] = ["hidden_city"]
    return harness.client.post(
        "/api/v1/agent/search-plans",
        headers=harness.auth_headers,
        json={"text": "LED → CDG", "coverage": "quick", "selections": selections},
    )


def _execute_body(plan: dict[str, object]) -> dict[str, object]:
    return {
        "revision_id": plan["revision_id"],
        "expected_revision": plan["revision"],
        "content_hash": plan["content_hash"],
        "hidden_city_warning_version": None,
    }


def _execute(harness: _Harness, plan: dict[str, object], key: str):
    return harness.client.post(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
        headers={**harness.auth_headers, "Idempotency-Key": key},
        json=_execute_body(plan),
    )
