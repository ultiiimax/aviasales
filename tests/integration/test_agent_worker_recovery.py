from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from flight_hunter.api.app import create_app
from flight_hunter.application.agent_execution import (
    AgentExecutionPolicy,
    AgentExecutionService,
)
from flight_hunter.config import AppSettings
from flight_hunter.ops.application_metrics import reset_application_metrics
from flight_hunter.ops.worker import run_once
from flight_hunter.persistence.agent_repositories import (
    AgentEvidenceRepository,
    AgentOperationalHealthRepository,
    AgentRunRepository,
)
from flight_hunter.persistence.database import create_database_engine
from flight_hunter.persistence.models import agent_run_operations_table
from tests.support.agent_gateway import (
    DeterministicAgentGateway,
    seed_agent_airports,
)


def test_new_worker_resumes_persisted_exact_poll_without_duplicate_evidence(
    tmp_path: Path,
) -> None:
    reset_application_metrics()
    database_url = _migrated_database_url(tmp_path / "agent-recovery.db")
    asyncio.run(_seed_agent_airports(database_url))

    gateway = DeterministicAgentGateway()
    settings = _settings(database_url)
    with TestClient(
        create_app(
            settings=settings,
            agent_provider_gateway=gateway,
        ),
        raise_server_exceptions=False,
    ) as client:
        session = _create_owner_session(client, settings.auth_bootstrap_token or "")
        headers = {"Authorization": f"Bearer {session['session_token']}"}
        plan_response = client.post(
            "/api/v1/agent/search-plans",
            headers=headers,
            json={
                "text": "LED → CDG",
                "coverage": "quick",
                "selections": {"departure_date": "2026-09-10"},
            },
        )
        assert plan_response.status_code == 201
        plan = plan_response.json()
        execute_response = client.post(
            f"/api/v1/agent/search-plans/{plan['plan_id']}/execute",
            headers={**headers, "Idempotency-Key": "task14-recovery-run"},
            json={
                "revision_id": plan["revision_id"],
                "expected_revision": plan["revision"],
                "content_hash": plan["content_hash"],
                "hidden_city_warning_version": None,
            },
        )
        assert execute_response.status_code == 202
        run_id = UUID(execute_response.json()["run_id"])
        household_id = UUID(session["household_id"])

        first_summary = asyncio.run(
            run_once(
                database_url=database_url,
                settings=settings,
                worker_id="agent-worker-before-restart",
                worker_roles=("agent",),
                agent_executor_factory=_executor_factory(gateway),
            )
        )
        continuation_count, evidence_count = asyncio.run(
            _continuation_and_evidence_count(
                database_url,
                household_id=household_id,
                run_id=run_id,
            )
        )
        assert first_summary.agent_operations_succeeded == 1
        assert len(gateway.start_calls) == 1
        assert gateway.poll_calls == []
        assert continuation_count == 1
        assert evidence_count == 0

        second_summary = asyncio.run(
            run_once(
                database_url=database_url,
                settings=settings,
                worker_id="agent-worker-after-restart",
                worker_roles=("agent",),
                agent_executor_factory=_executor_factory(gateway),
            )
        )
        assert second_summary.agent_operations_succeeded == 1
        assert len(gateway.start_calls) == 1
        assert len(gateway.poll_calls) == 1
        assert gateway.poll_calls[0].search_id == "fixture-search-1"
        assert (
            asyncio.run(
                _evidence_count(
                    database_url,
                    household_id=household_id,
                    run_id=run_id,
                )
            )
            == 1
        )

        terminal_status = asyncio.run(
            _run_until_terminal(
                database_url=database_url,
                settings=settings,
                gateway=gateway,
                household_id=household_id,
                run_id=run_id,
            )
        )
        assert terminal_status == "completed"
        assert len(gateway.start_calls) == 1
        assert len(gateway.poll_calls) == 1
        assert (
            asyncio.run(
                _evidence_count(
                    database_url,
                    household_id=household_id,
                    run_id=run_id,
                )
            )
            == 1
        )

        results = client.get(
            f"/api/v1/agent/search-plans/{plan['plan_id']}/runs/{run_id}/results",
            headers=headers,
        )
        assert results.status_code == 200
        payload = results.json()
        assert payload["state"] == "ready"
        assert len(payload["candidates"]) == 1
        assert payload["candidates"][0]["total_amount"] == {
            "minor_units": 20_000,
            "currency": "RUB",
        }

        health = asyncio.run(_agent_health(database_url))
        assert health.operation_status_counts["succeeded"] >= 2
        assert health.run_status_counts["completed"] == 1
        assert health.estimated_logical_operations >= health.actual_logical_operations > 0
        assert health.estimated_http_attempts >= health.actual_http_attempts == 2
        assert health.confirmed_candidates == 1
        assert health.terminal_run_count == 1
        assert health.provider_denials == 0
        assert health.recovered_operations == 0

        reset_application_metrics()
        metrics = client.get("/api/v1/metrics")
        assert metrics.status_code == 200
        assert "flight_hunter_agent_confirmed_candidates 1" in metrics.text
        assert 'flight_hunter_agent_http_attempts{kind="actual"} 2' in metrics.text
        assert "flight_hunter_agent_provider_denials 0" in metrics.text
        assert "flight_hunter_agent_recovered_operations 0" in metrics.text
        assert "PRIVATE" not in metrics.text


def _migrated_database_url(path: Path) -> str:
    database_url = f"sqlite+aiosqlite:///{path.resolve().as_posix()}"
    config = Config(str(Path("alembic.ini").resolve()))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return database_url


def _settings(database_url: str) -> AppSettings:
    return AppSettings(
        database_url=database_url,
        aviasales_search_enabled=True,
        aviasales_search_signature="123e4567-e89b-12d3-a456-426614174000",
        aviasales_search_marker="mobile_app.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        aviasales_search_internal_rpm=20,
        telegram_enabled=False,
        telegram_webhook_secret=None,
        app_secret_key=secrets.token_urlsafe(48),
        auth_bootstrap_token=secrets.token_urlsafe(48),
        auth_allow_legacy_headers=False,
        agent_poll_interval_seconds=0,
    )


def _create_owner_session(client: TestClient, bootstrap_token: str) -> dict[str, str]:
    invitation = client.post(
        "/api/v1/auth/bootstrap-invitation",
        headers={"X-Flight-Hunter-Bootstrap-Token": bootstrap_token},
        json={"household_name": "Task 14 household"},
    )
    assert invitation.status_code == 201
    accepted = client.post(
        "/api/v1/auth/accept-invitation",
        json={
            "invitation_code": invitation.json()["invitation_code"],
            "display_name": "Task 14 owner",
        },
    )
    assert accepted.status_code == 201
    return accepted.json()


def _executor_factory(gateway: DeterministicAgentGateway):
    def factory(
        session: AsyncSession,
        settings: AppSettings,
        worker_id: str,
    ) -> AgentExecutionService:
        return AgentExecutionService(
            session=session,
            gateway=gateway,
            worker_id=worker_id,
            policy=AgentExecutionPolicy(
                provider_rpm=settings.aviasales_search_internal_rpm,
                operation_lease_seconds=settings.agent_operation_lease_seconds,
                circuit_failure_threshold=settings.agent_provider_circuit_failure_threshold,
                circuit_cooldown_seconds=settings.agent_provider_circuit_cooldown_seconds,
                circuit_probe_lease_seconds=min(30, settings.agent_operation_lease_seconds),
                poll_interval_seconds=0,
            ),
            durability_checkpoint=session.commit,
        )

    return factory


async def _run_until_terminal(
    *,
    database_url: str,
    settings: AppSettings,
    gateway: DeterministicAgentGateway,
    household_id: UUID,
    run_id: UUID,
) -> str:
    for index in range(12):
        engine = create_database_engine(database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with session_factory() as session:
                run = await AgentRunRepository(session).get_run(household_id, run_id)
                assert run is not None
                if run.status in {"completed", "partial", "failed", "cancelled"}:
                    return run.status
        finally:
            await engine.dispose()
        await run_once(
            database_url=database_url,
            settings=settings,
            worker_id=f"agent-worker-resume-{index}",
            worker_roles=("agent",),
            agent_executor_factory=_executor_factory(gateway),
        )
    raise AssertionError("agent run did not become terminal")


async def _continuation_and_evidence_count(
    database_url: str,
    *,
    household_id: UUID,
    run_id: UUID,
) -> tuple[int, int]:
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            continuation_count = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(agent_run_operations_table)
                        .where(agent_run_operations_table.c.household_id == str(household_id))
                        .where(agent_run_operations_table.c.run_id == str(run_id))
                        .where(agent_run_operations_table.c.operation_kind == "exact_poll")
                        .where(agent_run_operations_table.c.private_continuation_json.is_not(None))
                    )
                ).scalar_one()
            )
            evidence_count = len(
                await AgentEvidenceRepository(session).list_confirmed_evidence(
                    household_id,
                    run_id,
                )
            )
        return continuation_count, evidence_count
    finally:
        await engine.dispose()


async def _evidence_count(
    database_url: str,
    *,
    household_id: UUID,
    run_id: UUID,
) -> int:
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return len(
                await AgentEvidenceRepository(session).list_confirmed_evidence(
                    household_id,
                    run_id,
                )
            )
    finally:
        await engine.dispose()


async def _agent_health(
    database_url: str,
):
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            return await AgentOperationalHealthRepository(session).snapshot(now=datetime.now(UTC))
    finally:
        await engine.dispose()


async def _seed_agent_airports(database_url: str) -> None:
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        await seed_agent_airports(session_factory)
    finally:
        await engine.dispose()
