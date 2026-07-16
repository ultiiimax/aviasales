from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.api.agent_routes import ERROR_STATUS, _status_for_error
from flight_hunter.api.agent_schemas import (
    AgentPlanSelections,
    AgentRunResultsResponse,
)
from flight_hunter.application import agent_lifecycle as agent_lifecycle_module
from flight_hunter.application.agent_hidden_city import (
    HiddenCityContext,
    classify_hidden_city,
)
from flight_hunter.application.agent_lifecycle import RunResultsView, _public_run_error
from flight_hunter.application.agent_reporting import CandidateRanker, FactReportBuilder
from flight_hunter.application.booking_actions import (
    sign_agent_booking_action_token,
)
from flight_hunter.domain.agent_evidence import ConfirmedOfferEvidence, ProtectionStatus
from flight_hunter.domain.money import Money
from flight_hunter.domain.offers import FlightSegmentSummary, Freshness, PriceBasis
from flight_hunter.persistence.agent_repositories import (
    AgentEvidenceRepository,
    AgentOperationRepository,
    AgentPlanRepository,
    AgentPlanRunRecord,
    AgentPlanStageKind,
    AgentRunRepository,
    AgentStageStatus,
    NewAgentBookingActionDescriptor,
    NewAgentConfirmedOfferEvidence,
    NewAgentPlanStage,
)
from flight_hunter.persistence.models import (
    agent_plan_runs_table,
    agent_plan_stages_table,
    agent_run_operations_table,
    agent_search_plan_revisions_table,
)


class _ProviderCounter(Protocol):
    calls: int
    booking_calls: int


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
async def test_same_only_route_returns_typed_draft_instead_of_internal_error(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "CDG → CDG",
            "coverage": "quick",
            "selections": {"departure_date": "2026-09-10"},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["state"] == "draft"
    assert payload["executable"] is False
    assert tuple(item["code"] for item in payload["clarifications"]) == ("same_origin_destination",)


@pytest.mark.anyio
async def test_every_public_clarification_action_has_patchable_typed_selections(
    agent_api_harness: _Harness,
) -> None:
    missing_date = _create_plan(agent_api_harness, with_date=False)
    oversized_quick = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "LED → CDG",
            "coverage": "quick",
            "selections": {
                "date_mode": "flexible",
                "departure_date": "2026-09-10",
                "flex_days": 30,
            },
        },
    )
    assert missing_date.status_code == oversized_quick.status_code == 201
    actions = tuple(
        action
        for response in (missing_date, oversized_quick)
        for clarification in response.json()["clarifications"]
        for action in clarification["actions"]
    )

    assert {action["action_id"] for action in actions} == {
        "use_rolling_90_days",
        "narrow_scope_or_dates",
    }
    for action in actions:
        AgentPlanSelections.model_validate(action["selections"])


@pytest.mark.anyio
async def test_immutable_scope_snapshot_binds_candidate_ordering_and_nearby_metadata(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "Проверь аэропорты рядом",
            "coverage": "full",
            "preset_id": "nearby_airports",
            "selections": {
                "origin": "LED",
                "destination": "CDG",
                "departure_date": "2026-09-10",
                "nearby_radius_km": 80,
            },
        },
    )
    assert response.status_code == 201
    assert response.json()["summary"]["scope"][0]["nearby_radius_km"] == 80

    async with agent_api_harness.session_factory() as session:
        revision = await AgentPlanRepository(session).get_revision(
            UUID(agent_api_harness.household_id),
            UUID(response.json()["revision_id"]),
        )

    assert revision is not None
    scope = json.loads(revision.scope_snapshot_json)
    for role in ("origin", "destination"):
        frozen = scope["legs"][0][role]
        candidates = frozen["airport_candidates"]
        assert [candidate["code"] for candidate in candidates] == frozen["airport_codes"]
        assert all(
            set(candidate)
            == {
                "code",
                "discovery_evidence_count",
                "commercial_relevance",
                "nearby_distance_km",
                "ground_transfer_cost_minor",
                "ground_transfer_currency",
                "ground_cost_uncertain",
            }
            for candidate in candidates
        )
        assert all(candidate["ground_transfer_cost_minor"] is None for candidate in candidates)
        assert all(candidate["ground_transfer_currency"] is None for candidate in candidates)


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
async def test_run_list_limit_is_publicly_bounded_to_one_hundred(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "list-limit-run")
    assert run.status_code == 202

    bounded = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs?limit=1",
        headers=agent_api_harness.auth_headers,
    )
    invalid = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs?limit=101",
        headers=agent_api_harness.auth_headers,
    )

    assert bounded.status_code == 200
    assert len(bounded.json()["runs"]) == 1
    assert invalid.status_code == 422


@pytest.mark.anyio
async def test_patch_new_text_replaces_old_text_derived_route_and_date(
    agent_api_harness: _Harness,
) -> None:
    first = _create_plan(agent_api_harness).json()
    patched = agent_api_harness.client.patch(
        f"/api/v1/agent/search-plans/{first['plan_id']}",
        headers=agent_api_harness.auth_headers,
        json={
            "source_revision_id": first["revision_id"],
            "expected_revision": first["revision"],
            "text": "SVO → JFK 2026-10-20",
        },
    )
    assert patched.status_code == 200

    async with agent_api_harness.session_factory() as session:
        repository = AgentPlanRepository(session)
        old = await repository.get_revision(
            UUID(agent_api_harness.household_id),
            UUID(first["revision_id"]),
        )
        new = await repository.get_revision(
            UUID(agent_api_harness.household_id),
            UUID(patched.json()["revision_id"]),
        )

    assert old is not None and new is not None
    old_intent = json.loads(old.plan_json)["intent"]
    new_intent = json.loads(new.plan_json)["intent"]
    assert old_intent["origin_text"] == "LED"
    assert old_intent["destination_text"] == "CDG"
    assert old_intent["legs"][0]["date_constraint"]["start_date"] == "2026-09-10"
    assert new_intent["origin_text"] == "SVO"
    assert new_intent["destination_text"] == "JFK"
    assert new_intent["legs"][0]["date_constraint"]["start_date"] == "2026-10-20"


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
    accepted_body = accepted.json()
    assert accepted_body["status"] == "queued"
    assert accepted_body["revision_id"] == plan["revision_id"]
    assert accepted_body["stage_counts"] == {
        "total": 0,
        "pending": 0,
        "running": 0,
        "completed": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "cancelled": 0,
    }
    assert accepted_body["operation_counts"] == {
        "total": 0,
        "attempted": 0,
        "pending": 0,
        "leased": 0,
        "retry_wait": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
    }
    assert accepted_body["logical_operation_budget"] == 1
    assert accepted_body["logical_operations_consumed"] == 0
    assert accepted_body["http_attempt_budget"] == 27
    assert accepted_body["http_attempts_consumed"] == 0
    assert accepted_body["cancellation_requested"] is False
    assert agent_api_harness.provider.calls == 0


@pytest.mark.anyio
async def test_queued_run_exposes_frozen_pair_coverage_without_private_ids(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    response = _execute(agent_api_harness, plan, "coverage-queued")

    assert response.status_code == 202
    coverage = response.json()["coverage_report"]
    assert coverage["coverage"] == "quick"
    assert coverage["completion"] == "pending"
    assert coverage["frozen_input"]["origins"] == ["LED"]
    assert coverage["frozen_input"]["destinations"] == ["CDG"]
    assert coverage["frozen_input"]["date_start"] == "2026-09-10"
    assert coverage["frozen_input"]["date_end"] == "2026-09-10"
    assert coverage["planned"] == 1
    assert coverage["attempted"] == 0
    assert coverage["succeeded"] == 0
    assert coverage["failed"] == 0
    assert coverage["skipped"] == 0
    assert coverage["pairs"] == [
        {
            "origin": "LED",
            "destination": "CDG",
            "departure_date": "2026-09-10",
            "return_date": None,
            "status": "planned",
            "reason": "agent_pair_not_attempted",
        }
    ]
    serialized = json.dumps(coverage, sort_keys=True)
    assert "operation_id" not in serialized
    assert "signal_id" not in serialized
    assert "snapshot_id" not in serialized


@pytest.mark.anyio
async def test_queued_anywhere_run_exposes_pending_discovery_coverage(
    agent_api_harness: _Harness,
) -> None:
    created = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "LED → anywhere",
            "coverage": "quick",
            "selections": {"departure_date": "2026-09-10"},
        },
    )
    assert created.status_code == 201
    plan = created.json()
    assert plan["state"] == "awaiting_approval"

    response = _execute(agent_api_harness, plan, "coverage-anywhere-queued")

    assert response.status_code == 202
    body = response.json()
    assert body["coverage_error_code"] is None
    coverage = body["coverage_report"]
    assert coverage["completion"] == "pending"
    assert coverage["frozen_input"]["origins"] == ["LED"]
    assert coverage["frozen_input"]["destinations"] == []
    assert coverage["planned"] == 0
    assert coverage["pairs"] == []
    assert coverage["reason_counts"] == {}
    assert coverage["discovery_phase"] == {
        "status": "pending",
        "terminal_reason": None,
        "source_ids": ["aviasales_hot_offers"],
        "max_destination_seeds": 40,
        "exact_verification_limit": 20,
    }


@pytest.mark.anyio
async def test_flexible_anywhere_dates_do_not_multiply_single_seed_query_work(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={
            "text": "LED → anywhere",
            "coverage": "quick",
            "selections": {
                "date_mode": "flexible",
                "departure_date": "2026-09-10",
                "flex_days": 30,
            },
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "awaiting_approval"
    assert body["estimate"]["calendar_searches"] == 40
    assert body["estimate"]["exact_searches"] == 20
    assert body["estimate"]["logical_operations"] == 60


@pytest.mark.anyio
async def test_tampered_scope_projection_is_sanitized_and_never_breaks_run_endpoints(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "tampered-coverage").json()
    canary = "provider_ref=private-diagnostic"
    async with agent_api_harness.session_factory() as session:
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == plan["revision_id"])
            .values(
                scope_snapshot_json=json.dumps(
                    {
                        "coverage": "quick",
                        "legs": [{"origin": {"airport_codes": ["LED"]}}],
                        "diagnostic": canary,
                    }
                )
            )
        )
        await session.commit()

    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}",
        headers=agent_api_harness.auth_headers,
    )
    listed = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs",
        headers=agent_api_harness.auth_headers,
    )

    assert fetched.status_code == listed.status_code == 200
    assert fetched.json()["coverage_report"] is None
    assert listed.json()["runs"][0]["coverage_report"] is None
    assert fetched.json()["coverage_error_code"] == "agent_coverage_projection_invalid"
    assert listed.json()["runs"][0]["coverage_error_code"] == ("agent_coverage_projection_invalid")
    assert canary not in fetched.text
    assert canary not in listed.text


@pytest.mark.anyio
async def test_oversized_date_projection_is_bounded_and_sanitized(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "oversized-date-coverage").json()
    async with agent_api_harness.session_factory() as session:
        revision = await AgentPlanRepository(session).get_revision(
            UUID(agent_api_harness.household_id),
            UUID(plan["revision_id"]),
        )
        assert revision is not None
        scope = json.loads(revision.scope_snapshot_json)
        scope["legs"][0]["date_constraint"] = {
            "mode": "range",
            "start_date": "0001-01-01",
            "end_date": "9999-12-31",
            "flex_days": 0,
        }
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == plan["revision_id"])
            .values(scope_snapshot_json=json.dumps(scope))
        )
        await session.commit()

    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}",
        headers=agent_api_harness.auth_headers,
    )

    assert fetched.status_code == 200
    assert fetched.json()["coverage_report"] is None
    assert fetched.json()["coverage_error_code"] == "agent_coverage_projection_invalid"


@pytest.mark.anyio
async def test_oversized_cartesian_projection_is_rejected_before_pair_allocation(
    agent_api_harness: _Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "oversized-cartesian-coverage").json()
    codes = [
        f"{first}{second}{third}"
        for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for third in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    ]
    async with agent_api_harness.session_factory() as session:
        revision = await AgentPlanRepository(session).get_revision(
            UUID(agent_api_harness.household_id),
            UUID(plan["revision_id"]),
        )
        assert revision is not None
        scope = json.loads(revision.scope_snapshot_json)
        origin = scope["legs"][0]["origin"]
        destination = scope["legs"][0]["destination"]
        origin["airport_codes"] = codes[:200]
        destination["airport_codes"] = codes[200:400]
        origin.pop("airport_candidates", None)
        destination.pop("airport_candidates", None)
        await session.execute(
            update(agent_search_plan_revisions_table)
            .where(agent_search_plan_revisions_table.c.id == plan["revision_id"])
            .values(scope_snapshot_json=json.dumps(scope))
        )
        await session.commit()

    def unexpected_pair_allocation(*_args: object, **_kwargs: object) -> tuple[()]:
        raise AssertionError("finite route pairs must not allocate above the approved budget")

    monkeypatch.setattr(
        agent_lifecycle_module,
        "finite_route_pairs",
        unexpected_pair_allocation,
    )
    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}",
        headers=agent_api_harness.auth_headers,
    )

    assert fetched.status_code == 200
    assert fetched.json()["coverage_report"] is None
    assert fetched.json()["coverage_error_code"] == "agent_coverage_projection_invalid"


@pytest.mark.anyio
async def test_terminal_run_reports_unmaterialized_frozen_pair_as_skipped(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "terminal-missing-pair").json()
    async with agent_api_harness.session_factory() as session:
        stored = await AgentRunRepository(session).get_run(
            UUID(agent_api_harness.household_id),
            UUID(run["run_id"]),
        )
        assert stored is not None
        await session.execute(
            update(agent_plan_runs_table)
            .where(agent_plan_runs_table.c.id == run["run_id"])
            .values(
                status="failed",
                started_at=stored.created_at + timedelta(seconds=1),
                finished_at=stored.created_at + timedelta(seconds=2),
                error_code="agent_no_confirmed_offer",
            )
        )
        await session.commit()

    fetched = agent_api_harness.client.get(
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}",
        headers=agent_api_harness.auth_headers,
    )

    assert fetched.status_code == 200
    coverage = fetched.json()["coverage_report"]
    assert coverage["completion"] == "partial"
    assert (coverage["planned"], coverage["attempted"], coverage["skipped"]) == (1, 0, 1)
    assert coverage["pairs"] == [
        {
            "origin": "LED",
            "destination": "CDG",
            "departure_date": "2026-09-10",
            "return_date": None,
            "status": "skipped",
            "reason": "agent_pair_not_materialized",
        }
    ]


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
    assert plan["summary"]["hidden_city_warning_version"] == "hidden-city-v1"
    assert {warning["code"] for warning in plan["summary"]["hidden_city_warnings"]} == {
        "checked_baggage_continues",
        "later_segments_may_be_cancelled",
        "carrier_contract_risk",
    }
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
async def test_execute_idempotency_key_cannot_cross_plan_or_revision_binding(
    agent_api_harness: _Harness,
) -> None:
    first = _create_plan(agent_api_harness).json()
    second = _create_plan(agent_api_harness).json()
    accepted = _execute(agent_api_harness, first, "household-shared-key")
    conflict = _execute(agent_api_harness, second, "household-shared-key")

    assert accepted.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "agent_run_idempotency_conflict"


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
    }


@pytest.mark.anyio
async def test_run_endpoints_never_expose_internal_error_diagnostics(
    agent_api_harness: _Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "secret-safe-run").json()
    secret_canaries = (
        "provider_ref=secret-provider-ref",
        "continuation=secret-continuation",
        "X-Signature=secret-signature",
        "token=secret-token",
    )
    async with agent_api_harness.session_factory() as session:
        repository = AgentRunRepository(session)
        stored = await repository.get_run(
            UUID(agent_api_harness.household_id),
            UUID(run["run_id"]),
        )
        assert stored is not None
        await _seed_progressed_run_ledger(session, stored, secret_canaries)
        await session.commit()

    responses = (
        agent_api_harness.client.get(
            f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}",
            headers=agent_api_harness.auth_headers,
        ),
        agent_api_harness.client.get(
            f"/api/v1/agent/search-plans/{plan['plan_id']}/runs",
            headers=agent_api_harness.auth_headers,
        ),
        agent_api_harness.client.get(
            f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/latest",
            headers=agent_api_harness.auth_headers,
        ),
    )
    output = " ".join(response.text for response in responses)

    assert all(response.status_code == 200 for response in responses)
    assert all("error_message" not in response.text for response in responses)
    assert all("public_message" in response.text for response in responses)
    assert all(
        response.json().get("error_code") == "agent_run_failed" for response in responses[:1]
    )
    projected = responses[0].json()
    assert projected["stage_counts"] == {
        "total": 1,
        "pending": 0,
        "running": 1,
        "completed": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "cancelled": 0,
    }
    assert projected["operation_counts"] == {
        "total": 4,
        "attempted": 3,
        "pending": 0,
        "leased": 0,
        "retry_wait": 1,
        "succeeded": 1,
        "failed": 1,
        "skipped": 1,
    }
    assert projected["logical_operations_consumed"] == 1
    assert projected["http_attempts_consumed"] == 4
    assert projected["cancellation_requested"] is True
    assert not any(secret in output or secret in caplog.text for secret in secret_canaries)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "selections",
    (
        {"adults": "2"},
        {"legs": "LED-CDG"},
        {"unexpected": "field"},
    ),
)
async def test_agent_selection_validation_returns_stable_422(
    agent_api_harness: _Harness,
    selections: dict[str, object],
) -> None:
    response = agent_api_harness.client.post(
        "/api/v1/agent/search-plans",
        headers=agent_api_harness.auth_headers,
        json={"text": "LED → CDG", "selections": selections},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "agent_plan_invalid_input",
        "message": "agent plan input is invalid",
    }


@pytest.mark.anyio
async def test_agent_validation_handler_preserves_unrelated_fastapi_errors(
    agent_api_harness: _Harness,
) -> None:
    response = agent_api_harness.client.post("/api/v1/auth/accept-invitation", json={})

    assert response.status_code == 422
    assert "detail" in response.json()
    assert "code" not in response.json()


def test_agent_error_status_mapping_is_exhaustive_and_unknown_is_unhandled() -> None:
    expected = {
        "auth_context_missing": 401,
        "idempotency_key_required": 400,
        "agent_plan_invalid_input": 422,
        "agent_plan_not_found": 404,
        "agent_run_not_found": 404,
        "agent_sqlite_nested_transaction_unsupported": 409,
        "agent_run_idempotency_conflict": 409,
        "agent_run_transition_conflict": 409,
        "agent_run_cancelled": 409,
    }
    assert expected.items() <= ERROR_STATUS.items()
    with pytest.raises(KeyError):
        _status_for_error("unknown_internal_lifecycle_code")


@pytest.mark.parametrize(
    "error_code",
    (
        "agent_run_deadline_exceeded",
        "agent_run_partial",
        "agent_http_budget_exhausted",
        "agent_circuit_open",
        "agent_no_confirmed_offer",
        "agent_plan_snapshot_invalid",
        "agent_operation_input_invalid",
        "agent_private_continuation_invalid",
        "agent_private_continuation_missing",
        "agent_trip_shape_unsupported",
        "agent_scope_unsupported",
        "agent_strategy_unsupported",
        "agent_analysis_unsupported",
        "agent_provider_rate_wait",
        "agent_lease_expired_attempts_exhausted",
        "provider_auth",
        "provider_forbidden",
        "provider_schema",
        "provider_rate_limited",
        "provider_network",
        "provider_server",
        "provider_policy_denied",
        "provider_client_error",
    ),
)
def test_safe_executor_error_codes_keep_stable_public_code_and_message(error_code: str) -> None:
    public_code, public_message = _public_run_error(error_code)

    assert public_code == error_code
    assert public_message is not None


def test_unknown_executor_error_collapses_without_exposing_internal_sentinel() -> None:
    sentinel = "provider_ref_internal_secret_sentinel"
    public_code, public_message = _public_run_error(sentinel)

    assert public_code == "agent_run_failed"
    assert public_message == "Search failed."
    assert sentinel not in repr((public_code, public_message))


def test_ready_results_schema_exposes_typed_facts_without_provider_reference() -> None:
    observed_at = datetime(2026, 7, 16, 12, tzinfo=UTC)
    evidence = ConfirmedOfferEvidence(
        id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        provider_id="aviasales_search",
        provider_offer_id="PRIVATE-provider-reference",
        origin="LED",
        destination="CDG",
        departure_date=date(2026, 9, 10),
        return_date=None,
        total_amount=Money(20_000, "RUB"),
        passengers=1,
        observed_at=observed_at,
        segment_ids=("safe-segment-ref",),
        segments=(
            FlightSegmentSummary(
                airline_code="FV",
                airline_name="Fixture Air",
                flight_number="FV100",
                origin="LED",
                destination="CDG",
                depart_at="2026-09-10 10:00",
                arrive_at="2026-09-10 12:00",
                depart_at_utc=datetime(2026, 9, 10, 7, tzinfo=UTC),
                arrive_at_utc=datetime(2026, 9, 10, 10, tzinfo=UTC),
            ),
        ),
        protection_status=ProtectionStatus.UNKNOWN,
    )
    ranking = CandidateRanker().rank((evidence,), comparison_currency="RUB")
    report = FactReportBuilder().build(ranking, (evidence,))

    response = AgentRunResultsResponse.from_view(
        RunResultsView(
            run_id=UUID("55555555-5555-4555-8555-555555555555"),
            state="ready",
            evidence_available=True,
            report=report,
        )
    )
    payload = response.model_dump(mode="json", exclude_none=True)

    assert payload["state"] == "ready"
    assert payload["ranking"]["comparison_currency"] == "RUB"
    assert payload["candidates"][0]["total_amount"] == {
        "minor_units": 20_000,
        "currency": "RUB",
    }
    assert payload["candidates"][0]["passenger_mix"] == {
        "adults": 1,
        "children": 0,
        "infants": 0,
        "total": 1,
    }
    assert payload["candidates"][0]["trip_shape"] == "one_way"
    assert payload["candidates"][0]["price_basis"] == "total_for_passengers"
    assert payload["candidates"][0]["price_comparison_status"] == "fully_priced"
    assert payload["candidates"][0]["ordered_legs"] == [
        {
            "ordinal": 0,
            "origin": "LED",
            "destination": "CDG",
            "departure_date": "2026-09-10",
            "component_evidence_ids": [str(evidence.id)],
        }
    ]
    assert payload["candidates"][0]["ticket_boundaries"] == [
        {
            "ticket_index": 0,
            "leg_ordinals": [0],
            "confirmed_evidence_id": str(evidence.id),
            "segment_ids": ["safe-segment-ref"],
            "protection_status": "unknown",
        }
    ]
    assert payload["candidates"][0]["connection_assumptions"] == []
    assert payload["candidates"][0]["unknown_costs"] == []
    assert payload["candidates"][0]["booking_action"] == {"available": False}
    rendered = json.dumps(payload)
    assert "PRIVATE-provider-reference" not in rendered
    assert "provider_offer_id" not in rendered


def test_hidden_city_results_are_separate_research_only_and_force_actions_off() -> None:
    observed_at = datetime(2026, 7, 16, 12, tzinfo=UTC)
    evidence = ConfirmedOfferEvidence(
        id=UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1"),
        provider_id="aviasales_search",
        provider_offer_id="PRIVATE-hidden-city-reference",
        origin="LED",
        destination="FCO",
        departure_date=date(2026, 9, 10),
        return_date=None,
        total_amount=Money(15_000, "RUB"),
        passengers=1,
        observed_at=observed_at,
        segment_ids=("safe-led-cdg", "safe-cdg-fco"),
        segments=(
            FlightSegmentSummary(
                airline_code="FV",
                airline_name="Fixture Air",
                flight_number="FV100",
                origin="LED",
                destination="CDG",
                depart_at="2026-09-10 08:00",
                arrive_at="2026-09-10 10:00",
            ),
            FlightSegmentSummary(
                airline_code="FV",
                airline_name="Fixture Air",
                flight_number="FV101",
                origin="CDG",
                destination="FCO",
                depart_at="2026-09-10 11:00",
                arrive_at="2026-09-10 13:00",
            ),
        ),
        protection_status=ProtectionStatus.UNKNOWN,
        baggage_summary=None,
    )
    decision = classify_hidden_city(
        evidence,
        "CDG",
        HiddenCityContext(plan_leg_index=0, final_plan_leg_index=0),
    )
    assert decision.candidate is not None

    response = AgentRunResultsResponse.from_view(
        RunResultsView(
            run_id=UUID("55555555-5555-4555-8555-555555555556"),
            state="ready",
            evidence_available=True,
            hidden_city_candidates=(decision.candidate,),
        )
    )
    payload = response.model_dump(mode="json", exclude_none=True)

    assert "ranking" not in payload
    assert "candidates" not in payload
    assert payload["hidden_city_candidates"] == [
        {
            "evidence_id": str(evidence.id),
            "desired_airport": "CDG",
            "ticketed_destination": "FCO",
            "actionability": "research_only_not_actionable",
            "total_amount": {"minor_units": 15_000, "currency": "RUB"},
            "passengers": 1,
            "source_id": "aviasales_search",
            "freshness": "live",
            "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
            "flown_segments": [
                {
                    "airline_code": "FV",
                    "airline_name": "Fixture Air",
                    "flight_number": "FV100",
                    "origin": "LED",
                    "destination": "CDG",
                    "depart_at": "2026-09-10 08:00",
                    "arrive_at": "2026-09-10 10:00",
                }
            ],
            "skipped_segments": [
                {
                    "airline_code": "FV",
                    "airline_name": "Fixture Air",
                    "flight_number": "FV101",
                    "origin": "CDG",
                    "destination": "FCO",
                    "depart_at": "2026-09-10 11:00",
                    "arrive_at": "2026-09-10 13:00",
                }
            ],
            "warning_version": "hidden-city-v1",
            "warnings": [
                "checked_baggage_continues",
                "later_segments_may_be_cancelled",
                "carrier_contract_risk",
            ],
            "booking_action_available": False,
            "watch_available": False,
        }
    ]
    assert "PRIVATE-hidden-city-reference" not in json.dumps(payload)


@pytest.mark.anyio
async def test_agent_booking_resolver_is_authenticated_and_household_scoped(
    agent_api_harness: _Harness,
) -> None:
    plan = _create_plan(agent_api_harness).json()
    run = _execute(agent_api_harness, plan, "booking-action-run").json()
    now = datetime.now(UTC)
    stage_id = UUID("66666666-6666-4666-8666-666666666660")
    evidence_id = UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee0")
    descriptor_id = UUID("dddddddd-dddd-4ddd-8ddd-ddddddddddd0")
    household_id = UUID(agent_api_harness.household_id)
    run_id = UUID(run["run_id"])

    async with agent_api_harness.session_factory() as session:
        await AgentOperationRepository(session).create_stage(
            NewAgentPlanStage(
                id=stage_id,
                household_id=household_id,
                run_id=run_id,
                kind=AgentPlanStageKind.EXACT_SEARCH,
                status=AgentStageStatus.COMPLETED,
                created_at=now,
            )
        )
        await AgentEvidenceRepository(session).append_confirmed_evidence(
            NewAgentConfirmedOfferEvidence(
                id=evidence_id,
                household_id=household_id,
                run_id=run_id,
                stage_id=stage_id,
                provider_id="aviasales_search",
                source="exact_search",
                observed_at=now,
                freshness=Freshness.LIVE,
                passengers=1,
                passenger_basis=PriceBasis.TOTAL_FOR_PASSENGERS,
                amount_minor=20_000,
                currency="RUB",
                itinerary_evidence={
                    "origin": "LED",
                    "destination": "CDG",
                    "segments": [
                        {
                            "origin": "LED",
                            "destination": "CDG",
                            "depart_at": "2026-09-10 10:00",
                            "arrive_at": "2026-09-10 12:00",
                            "carrier": "FV",
                            "flight_number": "FV100",
                        }
                    ],
                    "ticket_structure": "provider_ticket",
                },
                protection_status=ProtectionStatus.UNKNOWN,
                baggage_status=None,
                transfer_status=None,
                visa_status=None,
                fingerprint="sha256:" + "e" * 64,
                created_at=now,
            )
        )
        await AgentEvidenceRepository(session).append_booking_action_descriptor(
            NewAgentBookingActionDescriptor(
                id=descriptor_id,
                household_id=household_id,
                run_id=run_id,
                confirmed_evidence_id=evidence_id,
                provider_id="aviasales_search",
                private_descriptor={
                    "provider_id": "aviasales_search",
                    "search_id": "PRIVATE-search-id",
                    "proposal_id": "PRIVATE-proposal-id",
                    "results_url": "results.aviasales.ru",
                },
                fingerprint="sha256:" + "d" * 64,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
        )
        await session.commit()

    token = sign_agent_booking_action_token(
        secret_key="agent-test-secret",
        descriptor_id=descriptor_id,
        now=now,
        ttl_seconds=300,
    )
    path = (
        f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run['run_id']}/booking-actions/resolve"
    )
    resolved = agent_api_harness.client.post(
        path,
        headers=agent_api_harness.auth_headers,
        json={"token": token},
    )
    other = agent_api_harness.create_second_session()
    rejected = agent_api_harness.client.post(
        path,
        headers={"Authorization": f"Bearer {other['session_token']}"},
        json={"token": token},
    )

    assert resolved.status_code == 200
    assert resolved.json() == {
        "status": "resolved",
        "url": "https://tickets.example.test/opaque-purchase",
    }
    assert rejected.status_code == 400
    assert rejected.json()["code"] == "agent_booking_token_invalid"
    assert agent_api_harness.provider.booking_calls == 1
    assert "PRIVATE-proposal-id" not in token
    assert "results.aviasales.ru" not in token


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
    schemas = agent_api_harness.client.get("/openapi.json").json()["components"]["schemas"]
    result_schema = schemas["AgentRunResultsResponse"]
    run_schema = schemas["AgentRunResponse"]
    candidate_schema = schemas["AgentCandidateFactResponse"]
    assert set(result_schema["properties"]["state"]["enum"]) == {
        "not_ready",
        "ready",
        "unavailable",
    }
    assert {"ranking", "candidates", "error_code"} <= set(result_schema["properties"])
    assert {
        "passenger_mix",
        "trip_shape",
        "price_basis",
        "ordered_legs",
        "ticket_boundaries",
        "connection_assumptions",
        "price_comparison_status",
        "unknown_costs",
    } <= set(candidate_schema["properties"])
    assert "items" not in result_schema["properties"]
    assert {
        "stage_counts",
        "operation_counts",
        "logical_operation_budget",
        "logical_operations_consumed",
        "http_attempt_budget",
        "http_attempts_consumed",
        "deadline_at",
        "cancellation_requested",
        "error_code",
        "public_message",
    } <= set(run_schema["properties"])
    assert "private_continuation" not in run_schema["properties"]
    assert "error_message" not in run_schema["properties"]


async def _seed_progressed_run_ledger(
    session: AsyncSession,
    run: AgentPlanRunRecord,
    secret_canaries: tuple[str, ...],
) -> None:
    started = run.created_at + (datetime.resolution * 1_000_000)
    cancelled = started + (datetime.resolution * 1_000_000)
    stage_id = UUID("66666666-6666-6666-6666-666666666666")
    start_id = UUID("77777777-7777-7777-7777-777777777770")
    retry_id = UUID("77777777-7777-7777-7777-777777777771")
    failed_id = UUID("77777777-7777-7777-7777-777777777772")
    skipped_id = UUID("77777777-7777-7777-7777-777777777773")
    await session.execute(
        update(agent_plan_runs_table)
        .where(agent_plan_runs_table.c.id == str(run.id))
        .values(
            status="cancel_requested",
            started_at=started,
            cancel_requested_at=cancelled,
            error_code="provider_ref_secret_failure",
            error_message=" ".join(secret_canaries),
            logical_operations_consumed=1,
            http_attempts_consumed=4,
        )
    )
    await session.execute(
        insert(agent_plan_stages_table).values(
            id=str(stage_id),
            household_id=str(run.household_id),
            run_id=str(run.id),
            stage_kind="exact_search",
            status="running",
            created_at=started,
            updated_at=cancelled,
        )
    )

    def operation_row(
        *,
        operation_id: UUID,
        kind: str,
        status: str,
        fingerprint_char: str,
        attempt_count: int,
        http_attempts: int,
        updated_at: datetime,
        logical_root_id: UUID | None = None,
        private_continuation: dict[str, object] | None = None,
        next_retry_at: datetime | None = None,
        result_type: str | None = None,
        result_id: UUID | None = None,
        error_code: str | None = None,
        completed_at: datetime | None = None,
    ) -> dict[str, object]:
        return {
            "id": str(operation_id),
            "household_id": str(run.household_id),
            "run_id": str(run.id),
            "stage_id": str(stage_id),
            "provider_id": "aviasales_search",
            "operation_kind": kind,
            "operation_fingerprint": "sha256:" + fingerprint_char * 64,
            "logical_operation_fingerprint": "sha256:" + "a" * 64,
            "logical_root_operation_id": (
                str(logical_root_id) if logical_root_id is not None else None
            ),
            "handoff_predecessor_operation_id": None,
            "consumes_logical_unit": kind == "exact_start",
            "immutable_input_json": json.dumps(
                {"origin": "LED", "destination": "CDG"},
                separators=(",", ":"),
                sort_keys=True,
            ),
            "private_continuation_json": (
                json.dumps(private_continuation, separators=(",", ":"), sort_keys=True)
                if private_continuation is not None
                else None
            ),
            "status": status,
            "lease_owner": None,
            "lease_expires_at": None,
            "attempt_count": attempt_count,
            "max_attempts": max(1, attempt_count),
            "next_retry_at": next_retry_at,
            "http_attempts_consumed": http_attempts,
            "circuit_permit_token_digest": None,
            "circuit_permit_generation": None,
            "circuit_permit_mode": None,
            "circuit_permit_attempt_number": None,
            "circuit_permit_expires_at": None,
            "circuit_permit_consumed_at": None,
            "result_type": result_type,
            "result_id": str(result_id) if result_id is not None else None,
            "error_code": error_code,
            "created_at": started,
            "updated_at": updated_at,
            "completed_at": completed_at,
        }

    succeeded_at = started + (datetime.resolution * 100_000)
    retry_at = started + (datetime.resolution * 200_000)
    failed_at = started + (datetime.resolution * 300_000)
    skipped_at = started + (datetime.resolution * 400_000)
    await session.execute(
        insert(agent_run_operations_table),
        [
            operation_row(
                operation_id=start_id,
                kind="exact_start",
                status="succeeded",
                fingerprint_char="1",
                attempt_count=1,
                http_attempts=1,
                updated_at=succeeded_at,
                result_type="operation",
                result_id=retry_id,
                completed_at=succeeded_at,
            ),
            operation_row(
                operation_id=retry_id,
                kind="exact_poll",
                status="retry_wait",
                fingerprint_char="2",
                attempt_count=1,
                http_attempts=1,
                updated_at=retry_at,
                logical_root_id=start_id,
                private_continuation={
                    "search_session": secret_canaries[1],
                    "provider_ref": secret_canaries[0],
                    "token": secret_canaries[3],
                },
                next_retry_at=cancelled + (datetime.resolution * 60_000_000),
                error_code="provider_rate_limited",
            ),
            operation_row(
                operation_id=failed_id,
                kind="exact_poll",
                status="failed",
                fingerprint_char="3",
                attempt_count=2,
                http_attempts=2,
                updated_at=failed_at,
                logical_root_id=start_id,
                error_code="provider_transport",
                completed_at=failed_at,
            ),
            operation_row(
                operation_id=skipped_id,
                kind="exact_poll",
                status="skipped",
                fingerprint_char="4",
                attempt_count=0,
                http_attempts=0,
                updated_at=skipped_at,
                logical_root_id=start_id,
                error_code="agent_run_cancelled",
                completed_at=skipped_at,
            ),
        ],
    )


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
