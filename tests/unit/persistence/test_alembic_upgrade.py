from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql, sqlite

from flight_hunter.ops.structured_logging import LOGGER_NAME
from flight_hunter.persistence.models import (
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
    agent_search_plan_revisions_table,
    airports_table,
)


def test_airport_core_metadata_does_not_invent_commercial_defaults() -> None:
    assert airports_table.c.scheduled_service.default is None
    assert airports_table.c.commercial_provenance.default is None


def test_agent_run_core_partial_index_has_only_active_statuses() -> None:
    active_index = next(
        index
        for index in agent_plan_runs_table.indexes
        if index.name == "ix_agent_plan_one_active_run"
    )
    sqlite_predicate = active_index.dialect_options["sqlite"]["where"]
    postgres_predicate = active_index.dialect_options["postgresql"]["where"]

    assert str(sqlite_predicate.compile(dialect=sqlite.dialect())) == (
        "status IN ('queued', 'running', 'cancel_requested')"
    )
    assert str(postgres_predicate.compile(dialect=postgresql.dialect())) == (
        "status IN ('queued', 'running', 'cancel_requested')"
    )


def test_agent_core_metadata_has_reviewed_checks_and_approval_snapshot() -> None:
    revision_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in agent_search_plan_revisions_table.constraints
        if constraint.name is not None and hasattr(constraint, "sqltext")
    }
    run_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in agent_plan_runs_table.constraints
        if constraint.name is not None and hasattr(constraint, "sqltext")
    }

    assert "ck_agent_plan_revision_estimates" in revision_checks
    assert "estimated_logical_operations = " in revision_checks["ck_agent_plan_revision_estimates"]
    assert (
        "estimated_calendar_searches + estimated_exact_searches"
        in revision_checks["ck_agent_plan_revision_estimates"]
    )
    assert run_checks["ck_agent_plan_run_status"] == (
        "status IN ('queued', 'running', 'cancel_requested', "
        "'completed', 'partial', 'failed', 'cancelled')"
    )
    assert run_checks["ck_agent_plan_run_chronology"] == (
        "(started_at IS NULL OR started_at >= created_at) AND "
        "(cancel_requested_at IS NULL OR cancel_requested_at >= created_at) AND "
        "(cancel_requested_at IS NULL OR started_at IS NULL OR "
        "cancel_requested_at >= started_at) AND "
        "(finished_at IS NULL OR finished_at >= created_at) AND "
        "(finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at) AND "
        "(finished_at IS NULL OR cancel_requested_at IS NULL OR "
        "finished_at >= cancel_requested_at)"
    )
    for column_name in (
        "revision_content_hash",
        "approved_by_session_id",
        "approved_budget_json",
        "approved_strategies_json",
        "risk_warning_versions_json",
    ):
        assert not agent_plan_execution_approvals_table.c[column_name].nullable


def test_alembic_upgrade_does_not_disable_application_loggers(tmp_path: Path) -> None:
    db_path = tmp_path / "logger-safe.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = False

    command.upgrade(config, "head")

    assert not logger.disabled


def test_alembic_upgrade_head_creates_current_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "flight_hunter_test.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }
        browser_job_columns = {
            row[1]
            for row in connection.execute("pragma table_info(browser_observation_jobs)").fetchall()
        }
        watch_columns = {
            row[1] for row in connection.execute("pragma table_info(watches)").fetchall()
        }
        audit_event_columns = {
            row[1] for row in connection.execute("pragma table_info(audit_events)").fetchall()
        }
        watch_scan_job_columns = {
            row[1] for row in connection.execute("pragma table_info(watch_scan_jobs)").fetchall()
        }
        telegram_outbox_columns = {
            row[1]
            for row in connection.execute(
                "pragma table_info(telegram_notification_outbox)"
            ).fetchall()
        }
        manual_confirmation_columns = {
            row[1]
            for row in connection.execute(
                "pragma table_info(manual_price_confirmations)"
            ).fetchall()
        }
        auth_invitation_columns = {
            row[1] for row in connection.execute("pragma table_info(auth_invitations)").fetchall()
        }
        auth_session_columns = {
            row[1] for row in connection.execute("pragma table_info(auth_sessions)").fetchall()
        }
        household_membership_columns = {
            row[1]
            for row in connection.execute("pragma table_info(household_memberships)").fetchall()
        }
        worker_heartbeat_columns = {
            row[1] for row in connection.execute("pragma table_info(worker_heartbeats)").fetchall()
        }
        worker_control_columns = {
            row[1] for row in connection.execute("pragma table_info(worker_control)").fetchall()
        }
        deal_discovery_job_columns = {
            row[1]
            for row in connection.execute("pragma table_info(deal_discovery_jobs)").fetchall()
        }
        airport_columns = {
            row[1] for row in connection.execute("pragma table_info(airports)").fetchall()
        }
        agent_revision_columns = {
            row[1]
            for row in connection.execute(
                "pragma table_info(agent_search_plan_revisions)"
            ).fetchall()
        }
        agent_revision_indexes = {
            row[1]
            for row in connection.execute(
                "pragma index_list(agent_search_plan_revisions)"
            ).fetchall()
        }
        agent_run_columns = {
            row[1] for row in connection.execute("pragma table_info(agent_plan_runs)").fetchall()
        }
        agent_approval_info = {
            row[1]: row
            for row in connection.execute(
                "pragma table_info(agent_plan_execution_approvals)"
            ).fetchall()
        }
        agent_run_indexes = {
            row[1] for row in connection.execute("pragma index_list(agent_plan_runs)").fetchall()
        }
        active_run_index_sql = connection.execute(
            "select sql from sqlite_master where type = 'index' and name = ?",
            ("ix_agent_plan_one_active_run",),
        ).fetchone()
        agent_run_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_plan_runs",),
        ).fetchone()
        agent_revision_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_search_plan_revisions",),
        ).fetchone()

    assert {
        "watches",
        "price_snapshots",
        "alert_dedupe_entries",
        "user_action_grants",
        "live_observations",
        "live_observation_offers",
        "live_observation_idempotency",
        "browser_observation_jobs",
        "browser_observed_offers",
        "deal_candidates",
        "source_health_events",
        "watch_scan_jobs",
        "telegram_link_codes",
        "telegram_accounts",
        "telegram_notification_outbox",
        "telegram_update_dedupe",
        "audit_events",
        "manual_price_confirmations",
        "households",
        "users",
        "household_memberships",
        "auth_invitations",
        "auth_sessions",
        "worker_heartbeats",
        "worker_control",
        "deal_discovery_jobs",
        "agent_search_plans",
        "agent_search_plan_revisions",
        "agent_plan_execution_approvals",
        "agent_plan_runs",
    }.issubset(tables)
    assert {
        "attempts",
        "last_attempted_at",
        "next_retry_at",
        "locked_at",
        "locked_by",
        "operator_resume_requested_at",
        "operator_abort_requested_at",
    }.issubset(browser_job_columns)
    assert {
        "passengers",
        "currency",
        "next_eligible_at",
        "scan_interval_seconds",
        "last_scan_status",
        "updated_at",
        "version",
        "archived_at",
        "deleted_at",
    }.issubset(watch_columns)
    assert {"household_id", "actor_user_id", "action", "entity_id", "created_at"}.issubset(
        audit_event_columns
    )
    assert {
        "idempotency_key",
        "attempts",
        "next_retry_at",
        "locked_at",
        "locked_by",
        "deadline_at",
    }.issubset(watch_scan_job_columns)
    assert {"attempts", "next_retry_at", "locked_at", "locked_by"}.issubset(telegram_outbox_columns)
    assert {
        "household_id",
        "user_id",
        "target_kind",
        "target_id",
        "source_id",
        "status",
        "amount_minor",
        "currency",
        "note",
        "confirmed_at",
    }.issubset(manual_confirmation_columns)
    assert {"household_id", "user_id", "role", "disabled_at"}.issubset(household_membership_columns)
    assert {
        "household_id",
        "role",
        "code_hash",
        "expires_at",
        "accepted_at",
        "revoked_at",
    }.issubset(auth_invitation_columns)
    assert {"household_id", "user_id", "token_hash", "expires_at", "revoked_at"}.issubset(
        auth_session_columns
    )
    assert {
        "worker_id",
        "role",
        "status",
        "current_phase",
        "started_at",
        "last_seen_at",
        "last_summary_json",
    }.issubset(worker_heartbeat_columns)
    assert {
        "id",
        "drain_requested",
        "reason",
        "requested_by_household_id",
        "requested_by_user_id",
        "requested_at",
        "cleared_at",
        "updated_at",
    }.issubset(worker_control_columns)
    assert {
        "household_id",
        "user_id",
        "search_id",
        "idempotency_key",
        "status",
        "attempts",
        "next_retry_at",
        "locked_at",
        "locked_by",
        "deadline_at",
        "search_intent_json",
        "result_count",
    }.issubset(deal_discovery_job_columns)
    assert {"scheduled_service", "commercial_provenance"}.issubset(airport_columns)
    assert {
        "household_id",
        "plan_id",
        "revision_number",
        "state",
        "plan_json",
        "scope_snapshot_json",
        "capability_snapshot_json",
        "cost_model_snapshot_json",
        "parser_version",
        "planner_version",
        "estimated_logical_operations",
        "estimated_http_attempts",
        "content_hash",
        "expires_at",
        "superseded_at",
        "consumed_at",
        "clone_idempotency_key",
    }.issubset(agent_revision_columns)
    assert "raw_prompt" not in agent_revision_columns
    assert "ix_agent_plan_revision_clone_idempotency" in agent_revision_indexes
    assert {
        "household_id",
        "plan_id",
        "revision_id",
        "approval_id",
        "execute_idempotency_key",
        "status",
        "created_at",
        "deadline_at",
        "finished_at",
    }.issubset(agent_run_columns)
    assert "completed_at" not in agent_run_columns
    for column_name in (
        "revision_content_hash",
        "approved_by_session_id",
        "approved_budget_json",
        "approved_strategies_json",
        "risk_warning_versions_json",
    ):
        assert agent_approval_info[column_name][3] == 1
    assert "ix_agent_plan_one_active_run" in agent_run_indexes
    assert active_run_index_sql is not None
    assert "WHERE status IN ('queued', 'running', 'cancel_requested')" in active_run_index_sql[0]
    assert agent_run_table_sql is not None
    assert (
        "status IN ('queued', 'running', 'cancel_requested', "
        "'completed', 'partial', 'failed', 'cancelled')"
    ) in " ".join(agent_run_table_sql[0].split())
    assert "ck_agent_plan_run_chronology" in agent_run_table_sql[0]
    assert (
        "(started_at IS NULL OR started_at >= created_at) AND "
        "(cancel_requested_at IS NULL OR cancel_requested_at >= created_at) AND "
        "(cancel_requested_at IS NULL OR started_at IS NULL OR "
        "cancel_requested_at >= started_at) AND "
        "(finished_at IS NULL OR finished_at >= created_at) AND "
        "(finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at) AND "
        "(finished_at IS NULL OR cancel_requested_at IS NULL OR "
        "finished_at >= cancel_requested_at)"
    ) in " ".join(agent_run_table_sql[0].split())
    assert "'succeeded'" not in agent_run_table_sql[0]
    assert agent_revision_table_sql is not None
    assert "ck_agent_plan_revision_estimates" in agent_revision_table_sql[0]


def test_airport_commercial_migration_backfills_legacy_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "airport-commercial-upgrade.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    command.upgrade(config, "0021_worker_drain_control")

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            insert into airports (
                iata_code, name, municipality, country_code, latitude, longitude,
                airport_type, active, keywords, imported_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "WAW",
                "Warsaw Chopin Airport",
                "Warsaw",
                "PL",
                52.1657,
                20.9671,
                "large_airport",
                1,
                "",
                "2026-07-13 12:00:00+00:00",
            ),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "select scheduled_service, commercial_provenance from airports where iata_code = ?",
            ("WAW",),
        ).fetchone()
        columns = {
            item[1]: item for item in connection.execute("pragma table_info(airports)").fetchall()
        }

    assert row == (1, "legacy_import_filter")
    assert columns["scheduled_service"][3] == 1
    assert columns["commercial_provenance"][3] == 1
