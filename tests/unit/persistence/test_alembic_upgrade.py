from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.dialects import postgresql, sqlite

from flight_hunter.ops.structured_logging import LOGGER_NAME
from flight_hunter.persistence.models import (
    agent_composed_route_candidates_table,
    agent_confirmed_offer_evidence_table,
    agent_discovery_signals_table,
    agent_plan_execution_approvals_table,
    agent_plan_runs_table,
    agent_plan_stages_table,
    agent_provider_circuit_state_table,
    agent_provider_http_attempts_table,
    agent_provider_rate_locks_table,
    agent_ranking_snapshots_table,
    agent_run_operations_table,
    agent_run_scope_snapshots_table,
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


def test_review_agent_ledger_core_metadata_has_budget_checks_and_indexes() -> None:
    run_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in agent_plan_runs_table.constraints
        if constraint.name is not None and hasattr(constraint, "sqltext")
    }
    operation_indexes = {index.name: index for index in agent_run_operations_table.indexes}
    logical_root = operation_indexes["uq_agent_run_logical_root"]
    operation_checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in agent_run_operations_table.constraints
        if constraint.name is not None and hasattr(constraint, "sqltext")
    }
    attempt_constraints = {
        constraint.name for constraint in agent_provider_http_attempts_table.constraints
    }
    scope_constraints = {
        constraint.name for constraint in agent_run_scope_snapshots_table.constraints
    }

    assert "ck_agent_plan_run_budgets" in run_checks
    assert (
        "logical_operations_consumed <= logical_operation_budget"
        in run_checks["ck_agent_plan_run_budgets"]
    )
    assert (
        "http_attempts_consumed <= http_attempt_budget" in run_checks["ck_agent_plan_run_budgets"]
    )
    assert logical_root.unique
    assert (
        str(logical_root.dialect_options["sqlite"]["where"].compile(dialect=sqlite.dialect()))
        == "consumes_logical_unit = 1"
    )
    assert (
        str(
            logical_root.dialect_options["postgresql"]["where"].compile(
                dialect=postgresql.dialect()
            )
        )
        == "consumes_logical_unit = 1"
    )
    assert "ix_agent_operation_claim" in operation_indexes
    assert "ix_agent_run_operation_logical_root_id" in operation_indexes
    assert {
        "logical_root_operation_id",
        "circuit_permit_token_digest",
        "circuit_permit_generation",
        "circuit_permit_mode",
        "circuit_permit_attempt_number",
        "circuit_permit_expires_at",
        "circuit_permit_consumed_at",
    }.issubset(agent_run_operations_table.c.keys())
    logical_root_fk = next(
        foreign_key
        for foreign_key in agent_run_operations_table.c.logical_root_operation_id.foreign_keys
    )
    assert logical_root_fk.target_fullname == "agent_run_operations.id"
    assert logical_root_fk.ondelete == "CASCADE"
    assert "suggest_discovery" not in operation_checks["ck_agent_run_operation_kind"]
    assert "logical_root_operation_id" in operation_checks["ck_agent_run_operation_logical_shape"]
    assert "circuit_permit_token_digest" in operation_checks["ck_agent_run_operation_permit_shape"]
    assert "operation" in operation_checks["ck_agent_run_operation_result_type"]
    assert {
        "operation_attempt_number",
        "circuit_permit_generation",
        "circuit_permit_token_digest",
    }.issubset(agent_provider_http_attempts_table.c.keys())
    assert "uq_agent_provider_http_operation_attempt" in attempt_constraints
    assert "uq_agent_run_scope" in scope_constraints
    assert "uq_agent_run_scope_fingerprint" not in scope_constraints
    assert {
        "generation",
        "half_open_probe_operation_id",
        "half_open_probe_attempt_number",
        "half_open_probe_token_digest",
    }.issubset(agent_provider_circuit_state_table.c.keys())
    assert "half_open_probe_owner" not in agent_provider_circuit_state_table.c
    assert any(
        index.name == "ix_agent_provider_http_attempt_provider_reserved"
        for index in agent_provider_http_attempts_table.indexes
    )
    assert any(
        constraint.name == "uq_agent_ranking_fingerprint"
        for constraint in agent_ranking_snapshots_table.constraints
    )


def test_alembic_upgrade_does_not_disable_application_loggers(tmp_path: Path) -> None:
    db_path = tmp_path / "logger-safe.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    logger = logging.getLogger(LOGGER_NAME)
    logger.disabled = False

    command.upgrade(config, "head")

    assert not logger.disabled


def test_review_alembic_upgrade_head_creates_current_tables(tmp_path: Path) -> None:
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
        ledger_table_columns = {
            table_name: {
                row[1]
                for row in connection.execute(f'pragma table_info("{table_name}")').fetchall()
            }
            for table_name in (
                "agent_plan_stages",
                "agent_run_operations",
                "agent_provider_rate_locks",
                "agent_provider_http_attempts",
                "agent_provider_circuit_state",
                "agent_run_scope_snapshots",
                "agent_discovery_signals",
                "agent_confirmed_offer_evidence",
                "agent_composed_route_candidates",
                "agent_ranking_snapshots",
            )
        }
        operation_indexes = {
            row[1]
            for row in connection.execute("pragma index_list(agent_run_operations)").fetchall()
        }
        logical_root_index_sql = connection.execute(
            "select sql from sqlite_master where type = 'index' and name = ?",
            ("uq_agent_run_logical_root",),
        ).fetchone()
        operation_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_run_operations",),
        ).fetchone()
        attempt_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_provider_http_attempts",),
        ).fetchone()
        scope_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_run_scope_snapshots",),
        ).fetchone()
        circuit_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_provider_circuit_state",),
        ).fetchone()
        operation_foreign_keys = connection.execute(
            "pragma foreign_key_list(agent_run_operations)"
        ).fetchall()
        ranking_table_sql = connection.execute(
            "select sql from sqlite_master where type = 'table' and name = ?",
            ("agent_ranking_snapshots",),
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
        "agent_plan_stages",
        "agent_run_operations",
        "agent_provider_rate_locks",
        "agent_provider_http_attempts",
        "agent_provider_circuit_state",
        "agent_run_scope_snapshots",
        "agent_discovery_signals",
        "agent_confirmed_offer_evidence",
        "agent_composed_route_candidates",
        "agent_ranking_snapshots",
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
        "logical_operation_budget",
        "logical_operations_consumed",
        "http_attempt_budget",
        "http_attempts_consumed",
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
    assert {
        "household_id",
        "run_id",
        "stage_id",
        "provider_id",
        "operation_kind",
        "operation_fingerprint",
        "logical_operation_fingerprint",
        "logical_root_operation_id",
        "consumes_logical_unit",
        "immutable_input_json",
        "private_continuation_json",
        "status",
        "lease_owner",
        "lease_expires_at",
        "attempt_count",
        "max_attempts",
        "next_retry_at",
        "http_attempts_consumed",
        "result_type",
        "result_id",
        "error_code",
        "circuit_permit_token_digest",
        "circuit_permit_generation",
        "circuit_permit_mode",
        "circuit_permit_attempt_number",
        "circuit_permit_expires_at",
        "circuit_permit_consumed_at",
    }.issubset(ledger_table_columns["agent_run_operations"])
    assert {
        "operation_attempt_number",
        "circuit_permit_generation",
        "circuit_permit_token_digest",
    }.issubset(ledger_table_columns["agent_provider_http_attempts"])
    assert {
        "generation",
        "half_open_probe_operation_id",
        "half_open_probe_attempt_number",
        "half_open_probe_token_digest",
    }.issubset(ledger_table_columns["agent_provider_circuit_state"])
    assert "half_open_probe_owner" not in ledger_table_columns["agent_provider_circuit_state"]
    assert "uq_agent_run_logical_root" in operation_indexes
    assert "ix_agent_operation_claim" in operation_indexes
    assert logical_root_index_sql is not None
    assert "WHERE consumes_logical_unit = 1" in logical_root_index_sql[0]
    assert operation_table_sql is not None
    assert "ck_agent_run_operation_logical_shape" in operation_table_sql[0]
    assert "ck_agent_run_operation_permit_shape" in operation_table_sql[0]
    assert "'operation'" in operation_table_sql[0]
    assert "'suggest_discovery'" not in operation_table_sql[0]
    assert any(
        row[2] == "agent_run_operations"
        and row[3] == "logical_root_operation_id"
        and row[4] == "id"
        and row[6].upper() == "CASCADE"
        for row in operation_foreign_keys
    )
    assert attempt_table_sql is not None
    assert "uq_agent_provider_http_operation_attempt" in attempt_table_sql[0]
    assert scope_table_sql is not None
    assert "uq_agent_run_scope" in scope_table_sql[0]
    assert "uq_agent_run_scope_fingerprint" not in scope_table_sql[0]
    assert circuit_table_sql is not None
    assert "half_open_probe_operation_id" in circuit_table_sql[0]
    assert ranking_table_sql is not None
    assert "uq_agent_ranking_fingerprint" in ranking_table_sql[0]


def test_review_fresh_core_metadata_matches_migration_head_for_agent_ledger(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "ledger-metadata-parity.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")
    tables = (
        agent_plan_stages_table,
        agent_run_operations_table,
        agent_provider_rate_locks_table,
        agent_provider_http_attempts_table,
        agent_provider_circuit_state_table,
        agent_run_scope_snapshots_table,
        agent_discovery_signals_table,
        agent_confirmed_offer_evidence_table,
        agent_composed_route_candidates_table,
        agent_ranking_snapshots_table,
    )

    with sqlite3.connect(db_path) as connection:
        for table in tables:
            migrated_columns = {
                row[1] for row in connection.execute(f'pragma table_info("{table.name}")')
            }
            assert migrated_columns == set(table.c.keys())
        migrated_run_columns = {
            row[1] for row in connection.execute("pragma table_info(agent_plan_runs)")
        }

    assert set(agent_plan_runs_table.c.keys()) == migrated_run_columns


def test_0023_to_0024_preserves_agent_lifecycle_rows_with_zero_historical_budgets(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "agent-0023-upgrade.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    command.upgrade(config, "0023_agent_plan_lifecycle")
    now = "2026-07-14T10:00:00+00:00"

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "insert into agent_search_plans (id, household_id, created_by_user_id, created_at) "
            "values (?, ?, ?, ?)",
            ("plan", "household", "user", now),
        )
        connection.execute(
            "insert into agent_search_plan_revisions ("
            "id, plan_id, household_id, revision_number, state, plan_json, "
            "scope_snapshot_json, capability_snapshot_json, cost_model_snapshot_json, "
            "parser_version, planner_version, estimated_calendar_searches, "
            "estimated_exact_searches, estimated_logical_operations, "
            "estimated_http_attempts, estimated_deadline_seconds, content_hash, "
            "created_at, expires_at, consumed_at) values "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "revision",
                "plan",
                "household",
                1,
                "consumed",
                "{}",
                "{}",
                "{}",
                "{}",
                "parser-v1",
                "planner-v1",
                1,
                2,
                3,
                7,
                600,
                "sha256:" + "a" * 64,
                now,
                "2026-07-14T11:00:00+00:00",
                now,
            ),
        )
        connection.execute(
            "insert into agent_plan_execution_approvals ("
            "id, household_id, plan_id, revision_id, approved_by_user_id, "
            "revision_content_hash, approved_by_session_id, approved_budget_json, "
            "approved_strategies_json, risk_warning_versions_json, approved_at, expires_at, "
            "consumed_at, run_id) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "approval",
                "household",
                "plan",
                "revision",
                "user",
                "sha256:" + "a" * 64,
                "session",
                '{"logical_operations":3,"http_attempts":7}',
                '["direct"]',
                "{}",
                now,
                "2026-07-14T10:30:00+00:00",
                now,
                "run",
            ),
        )
        connection.execute(
            "insert into agent_plan_runs ("
            "id, household_id, plan_id, revision_id, approval_id, execute_idempotency_key, "
            "status, created_at, deadline_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "run",
                "household",
                "plan",
                "revision",
                "approval",
                "execute:legacy",
                "queued",
                now,
                "2026-07-14T10:10:00+00:00",
            ),
        )
        connection.commit()

    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("select count(*) from agent_search_plans").fetchone() == (1,)
        assert connection.execute(
            "select state, estimated_logical_operations, estimated_http_attempts "
            "from agent_search_plan_revisions"
        ).fetchone() == ("consumed", 3, 7)
        assert connection.execute(
            "select consumed_at, run_id from agent_plan_execution_approvals"
        ).fetchone() == (now, "run")
        assert connection.execute(
            "select status, logical_operation_budget, logical_operations_consumed, "
            "http_attempt_budget, http_attempts_consumed from agent_plan_runs"
        ).fetchone() == ("queued", 0, 0, 0, 0)


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
