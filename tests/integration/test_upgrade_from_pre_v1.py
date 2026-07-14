from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

HOUSEHOLD_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_ID = "11111111-1111-1111-1111-111111111111"
WATCH_ID = "22222222-2222-2222-2222-222222222222"
BROWSER_JOB_ID = "33333333-3333-3333-3333-333333333333"
DEAL_JOB_ID = "44444444-4444-4444-4444-444444444444"
NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def test_review_upgrade_from_immediate_pre_v1_preserves_local_data(tmp_path: Path) -> None:
    database_path = tmp_path / "pre-v1.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "0021_worker_drain_control")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO households (id, name, created_at) VALUES (:id, :name, :now)"),
            {"id": HOUSEHOLD_ID, "name": "Pre-v1 family", "now": _db_time(NOW)},
        )
        connection.execute(
            text("INSERT INTO users (id, display_name, created_at) VALUES (:id, :name, :now)"),
            {"id": USER_ID, "name": "Pre-v1 owner", "now": _db_time(NOW)},
        )
        connection.execute(
            text(
                "INSERT INTO household_memberships "
                "(household_id, user_id, role, created_at, disabled_at) "
                "VALUES (:household_id, :user_id, 'owner', :now, NULL)"
            ),
            {"household_id": HOUSEHOLD_ID, "user_id": USER_ID, "now": _db_time(NOW)},
        )
        connection.execute(
            text(
                "INSERT INTO auth_sessions "
                "(id, household_id, user_id, token_hash, created_at, expires_at) "
                "VALUES (:id, :household_id, :user_id, :token_hash, :now, :expires_at)"
            ),
            {
                "id": "55555555-5555-5555-5555-555555555555",
                "household_id": HOUSEHOLD_ID,
                "user_id": USER_ID,
                "token_hash": "a" * 64,
                "now": _db_time(NOW),
                "expires_at": _db_time(NOW + timedelta(days=30)),
            },
        )
        connection.execute(
            text(
                "INSERT INTO watches "
                "(id, household_id, owner_user_id, origin, destination, departure_date, "
                "return_date, enabled, created_at, updated_at, passengers, currency, "
                "scan_interval_seconds, allowed_provider_ids) "
                "VALUES (:id, :household_id, :user_id, 'MOW', 'LED', '2026-09-15', NULL, "
                "1, :now, :now, 1, 'RUB', 3600, 'fake')"
            ),
            {
                "id": WATCH_ID,
                "household_id": HOUSEHOLD_ID,
                "user_id": USER_ID,
                "now": _db_time(NOW),
            },
        )
        connection.execute(
            text(
                "INSERT INTO browser_observation_jobs "
                "(id, household_id, user_id, source_id, search_id, search_intent_hash, "
                "idempotency_key, grant_id, origin, destination, departure_date, return_date, "
                "passengers, adults, children, infants, trip_type, currency, status, created_at, "
                "expires_at, operator_resume_requested_at, operator_abort_requested_at) "
                "VALUES (:id, :household_id, :user_id, 'tutu', 'sha256:pre-v1', "
                "'sha256:intent', 'pre-v1-browser', :grant_id, 'MOW', 'LED', '2026-09-15', "
                "NULL, 1, 1, 0, 0, 'one_way', 'RUB', 'queued', :now, :expires_at, NULL, NULL)"
            ),
            {
                "id": BROWSER_JOB_ID,
                "household_id": HOUSEHOLD_ID,
                "user_id": USER_ID,
                "grant_id": "66666666-6666-6666-6666-666666666666",
                "now": _db_time(NOW),
                "expires_at": _db_time(NOW + timedelta(minutes=5)),
            },
        )
        connection.execute(
            text(
                "INSERT INTO worker_heartbeats "
                "(worker_id, role, status, current_phase, started_at, last_seen_at, "
                "last_summary_json) VALUES "
                "('pre-v1-worker', 'all', 'running', 'idle', :now, :now, :summary)"
            ),
            {"now": _db_time(NOW), "summary": '{"jobs":1}'},
        )
        connection.execute(
            text(
                "INSERT INTO worker_control "
                "(id, drain_requested, reason, requested_by_household_id, "
                "requested_by_user_id, requested_at, updated_at) VALUES "
                "('global', 1, 'pre-v1 drain', :household_id, :user_id, :now, :now)"
            ),
            {"household_id": HOUSEHOLD_ID, "user_id": USER_ID, "now": _db_time(NOW)},
        )
        connection.execute(
            text(
                "INSERT INTO deal_discovery_jobs "
                "(id, household_id, user_id, search_id, idempotency_key, status, deadline_at, "
                'created_at, search_intent_json, "limit") VALUES '
                "(:id, :household_id, :user_id, 'sha256:pre-v1', 'pre-v1-deal', 'queued', "
                ":deadline, :now, :intent, 3)"
            ),
            {
                "id": DEAL_JOB_ID,
                "household_id": HOUSEHOLD_ID,
                "user_id": USER_ID,
                "deadline": _db_time(NOW + timedelta(minutes=10)),
                "now": _db_time(NOW),
                "intent": (
                    '{"origin":"MOW","destination":"LED",'
                    '"departure_date":"2026-09-15","return_date":null,'
                    '"passengers":1,"currency":"RUB"}'
                ),
            },
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM households")).scalar_one() == (
            "Pre-v1 family"
        )
        assert connection.execute(text("SELECT display_name FROM users")).scalar_one() == (
            "Pre-v1 owner"
        )
        assert connection.execute(text("SELECT role FROM household_memberships")).scalar_one() == (
            "owner"
        )
        assert connection.execute(text("SELECT token_hash FROM auth_sessions")).scalar_one() == (
            "a" * 64
        )
        assert connection.execute(text("SELECT destination FROM watches")).scalar_one() == "LED"
        assert (
            connection.execute(text("SELECT status FROM browser_observation_jobs")).scalar_one()
            == "queued"
        )
        assert (
            connection.execute(text("SELECT last_summary_json FROM worker_heartbeats")).scalar_one()
            == '{"jobs":1}'
        )
        assert connection.execute(text("SELECT reason FROM worker_control")).scalar_one() == (
            "pre-v1 drain"
        )
        assert (
            connection.execute(text("SELECT status FROM deal_discovery_jobs")).scalar_one()
            == "queued"
        )
        preserved_counts = {
            table_name: connection.execute(
                text(f'SELECT count(*) FROM "{table_name}"')
            ).scalar_one()
            for table_name in (
                "households",
                "users",
                "household_memberships",
                "auth_sessions",
                "watches",
                "browser_observation_jobs",
                "worker_heartbeats",
                "worker_control",
                "deal_discovery_jobs",
            )
        }
        assert preserved_counts == {
            "households": 1,
            "users": 1,
            "household_memberships": 1,
            "auth_sessions": 1,
            "watches": 1,
            "browser_observation_jobs": 1,
            "worker_heartbeats": 1,
            "worker_control": 1,
            "deal_discovery_jobs": 1,
        }
        new_agent_tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'agent_%'")
            )
        }
        assert {
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
        }.issubset(new_agent_tables)
        operation_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(agent_run_operations)"))
        }
        attempt_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_provider_http_attempts)"))
        }
        circuit_columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(agent_provider_circuit_state)"))
        }
        operation_table_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'agent_run_operations'"
            )
        ).scalar_one()
        scope_table_sql = connection.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'table' AND name = 'agent_run_scope_snapshots'"
            )
        ).scalar_one()
        assert {
            "logical_root_operation_id",
            "circuit_permit_token_digest",
            "circuit_permit_generation",
            "circuit_permit_mode",
            "circuit_permit_attempt_number",
            "circuit_permit_expires_at",
            "circuit_permit_consumed_at",
        }.issubset(operation_columns)
        assert {
            "operation_attempt_number",
            "circuit_permit_generation",
            "circuit_permit_token_digest",
        }.issubset(attempt_columns)
        assert {
            "generation",
            "half_open_probe_operation_id",
            "half_open_probe_attempt_number",
            "half_open_probe_token_digest",
        }.issubset(circuit_columns)
        assert "half_open_probe_owner" not in circuit_columns
        assert "ck_agent_run_operation_logical_shape" in operation_table_sql
        assert "uq_agent_run_scope" in scope_table_sql
        assert "uq_agent_run_scope_fingerprint" not in scope_table_sql
        database_revision = connection.execute(text("SELECT version_num FROM alembic_version"))
        assert (
            database_revision.scalar_one() == ScriptDirectory.from_config(config).get_current_head()
        )

    engine.dispose()


def _alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )
    return config


def _db_time(value: datetime) -> str:
    return value.isoformat()
