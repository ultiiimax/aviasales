from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


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
