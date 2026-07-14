"""add durable agent operation and evidence ledger

Revision ID: 0024_agent_execution_ledger
Revises: 0023_agent_plan_lifecycle
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_agent_execution_ledger"
down_revision: str | Sequence[str] | None = "0023_agent_plan_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_plan_runs") as batch:
        batch.add_column(
            sa.Column(
                "logical_operation_budget",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "logical_operations_consumed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "http_attempt_budget",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "http_attempts_consumed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.create_check_constraint(
            "ck_agent_plan_run_budgets",
            "logical_operation_budget >= 0 AND logical_operations_consumed >= 0 AND "
            "logical_operations_consumed <= logical_operation_budget AND "
            "http_attempt_budget >= 0 AND http_attempts_consumed >= 0 AND "
            "http_attempts_consumed <= http_attempt_budget",
        )

    op.create_table(
        "agent_plan_stages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage_kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "stage_kind", name="uq_agent_plan_stage_kind"),
        sa.CheckConstraint(
            "stage_kind IN ('scope', 'calendar_discovery', 'exact_search', "
            "'composition', 'ranking', 'analysis')",
            name="ck_agent_plan_stage_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', "
            "'failed', 'skipped', 'cancelled')",
            name="ck_agent_plan_stage_status",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_agent_plan_stage_chronology",
        ),
    )
    op.create_index(
        "ix_agent_plan_stages_household_id",
        "agent_plan_stages",
        ["household_id"],
    )
    op.create_index("ix_agent_plan_stages_run_id", "agent_plan_stages", ["run_id"])
    op.create_index("ix_agent_plan_stages_status", "agent_plan_stages", ["status"])

    op.create_table(
        "agent_run_operations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=80), nullable=True),
        sa.Column("operation_kind", sa.String(length=40), nullable=False),
        sa.Column("operation_fingerprint", sa.String(length=71), nullable=False),
        sa.Column("logical_operation_fingerprint", sa.String(length=71), nullable=False),
        sa.Column("consumes_logical_unit", sa.Boolean(), nullable=False),
        sa.Column("immutable_input_json", sa.Text(), nullable=False),
        sa.Column("private_continuation_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("http_attempts_consumed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_type", sa.String(length=40), nullable=True),
        sa.Column("result_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "run_id",
            "operation_fingerprint",
            name="uq_agent_run_operation_fingerprint",
        ),
        sa.CheckConstraint(
            "operation_kind IN ('scope_freeze', 'calendar_search', 'exact_start', "
            "'exact_poll', 'suggest_discovery', 'comparison', 'composition', "
            "'ranking', 'analysis')",
            name="ck_agent_run_operation_kind",
        ),
        sa.CheckConstraint(
            "operation_kind NOT IN ('calendar_search', 'exact_start', 'exact_poll', "
            "'suggest_discovery') OR provider_id IS NOT NULL",
            name="ck_agent_run_operation_provider",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'retry_wait', 'succeeded', 'failed', 'skipped')",
            name="ck_agent_run_operation_status",
        ),
        sa.CheckConstraint(
            "result_type IS NULL OR result_type IN ('scope_snapshot', 'discovery_signal', "
            "'confirmed_offer', 'composed_candidate', 'ranking_snapshot')",
            name="ck_agent_run_operation_result_type",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts AND "
            "http_attempts_consumed >= 0",
            name="ck_agent_run_operation_counters",
        ),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND next_retry_at IS NULL AND result_type IS NULL AND result_id IS NULL "
            "AND error_code IS NULL AND completed_at IS NULL) OR "
            "(status = 'retry_wait' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND next_retry_at IS NOT NULL AND result_type IS NULL AND result_id IS NULL "
            "AND error_code IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'pending' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND next_retry_at IS NULL AND result_type IS NULL AND result_id IS NULL "
            "AND error_code IS NULL AND completed_at IS NULL) OR "
            "(status = 'succeeded' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND next_retry_at IS NULL AND completed_at IS NOT NULL "
            "AND result_type IS NOT NULL AND result_id IS NOT NULL AND error_code IS NULL) OR "
            "(status IN ('failed', 'skipped') AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL AND next_retry_at IS NULL "
            "AND result_type IS NULL AND result_id IS NULL "
            "AND completed_at IS NOT NULL AND error_code IS NOT NULL)",
            name="ck_agent_run_operation_shape",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at AND (completed_at IS NULL OR completed_at >= updated_at) "
            "AND (lease_expires_at IS NULL OR lease_expires_at > updated_at) "
            "AND (next_retry_at IS NULL OR next_retry_at > updated_at)",
            name="ck_agent_run_operation_chronology",
        ),
    )
    op.create_index(
        "ix_agent_run_operations_household_id",
        "agent_run_operations",
        ["household_id"],
    )
    op.create_index("ix_agent_run_operations_run_id", "agent_run_operations", ["run_id"])
    op.create_index("ix_agent_run_operations_stage_id", "agent_run_operations", ["stage_id"])
    op.create_index(
        "ix_agent_run_operations_provider_id",
        "agent_run_operations",
        ["provider_id"],
    )
    op.create_index("ix_agent_run_operations_status", "agent_run_operations", ["status"])
    op.create_index(
        "uq_agent_run_logical_root",
        "agent_run_operations",
        ["run_id", "logical_operation_fingerprint"],
        unique=True,
        sqlite_where=sa.text("consumes_logical_unit = 1"),
        postgresql_where=sa.text("consumes_logical_unit = 1"),
    )
    op.create_index(
        "ix_agent_operation_claim",
        "agent_run_operations",
        ["status", "next_retry_at", "lease_expires_at", "created_at"],
    )

    op.create_table(
        "agent_provider_rate_locks",
        sa.Column("provider_id", sa.String(length=80), primary_key=True),
        sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agent_provider_http_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_id",
            sa.String(length=36),
            sa.ForeignKey("agent_run_operations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_kind", sa.String(length=20), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt_kind IN ('start', 'poll', 'retry')",
            name="ck_agent_provider_http_attempt_kind",
        ),
    )
    op.create_index(
        "ix_agent_provider_http_attempts_household_id",
        "agent_provider_http_attempts",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_provider_http_attempts_run_id",
        "agent_provider_http_attempts",
        ["run_id"],
    )
    op.create_index(
        "ix_agent_provider_http_attempts_operation_id",
        "agent_provider_http_attempts",
        ["operation_id"],
    )
    op.create_index(
        "ix_agent_provider_http_attempt_provider_reserved",
        "agent_provider_http_attempts",
        ["provider_id", "reserved_at"],
    )

    op.create_table(
        "agent_provider_circuit_state",
        sa.Column("provider_id", sa.String(length=80), primary_key=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("consecutive_transient_failures", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("half_open_probe_owner", sa.String(length=160), nullable=True),
        sa.Column("half_open_probe_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('closed', 'open', 'half_open')",
            name="ck_agent_provider_circuit_state",
        ),
        sa.CheckConstraint(
            "consecutive_transient_failures >= 0 AND version >= 0",
            name="ck_agent_provider_circuit_counters",
        ),
        sa.CheckConstraint(
            "(state = 'closed' AND opened_at IS NULL AND cooldown_until IS NULL "
            "AND half_open_probe_owner IS NULL AND half_open_probe_expires_at IS NULL) OR "
            "(state = 'open' AND opened_at IS NOT NULL AND cooldown_until IS NOT NULL "
            "AND half_open_probe_owner IS NULL AND half_open_probe_expires_at IS NULL) OR "
            "(state = 'half_open' AND opened_at IS NOT NULL AND cooldown_until IS NOT NULL "
            "AND half_open_probe_owner IS NOT NULL AND half_open_probe_expires_at IS NOT NULL)",
            name="ck_agent_provider_circuit_shape",
        ),
    )

    op.create_table(
        "agent_run_scope_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "fingerprint", name="uq_agent_run_scope_fingerprint"),
    )
    op.create_index(
        "ix_agent_run_scope_snapshots_household_id",
        "agent_run_scope_snapshots",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_run_scope_snapshots_run_id",
        "agent_run_scope_snapshots",
        ["run_id"],
    )

    _create_evidence_tables()


def _create_evidence_tables() -> None:
    op.create_table(
        "agent_discovery_signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("return_date", sa.Date(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("passengers", sa.Integer(), nullable=False),
        sa.Column("passenger_basis", sa.String(length=50), nullable=False),
        sa.Column("source_kind", sa.String(length=30), nullable=False),
        sa.Column("freshness", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_evidence_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "fingerprint", name="uq_agent_discovery_fingerprint"),
        sa.CheckConstraint(
            "(amount_minor IS NULL AND currency IS NULL) OR (amount_minor IS NOT NULL "
            "AND amount_minor >= 0 AND currency IS NOT NULL AND length(currency) = 3 "
            "AND currency = upper(currency))",
            name="ck_agent_discovery_amount",
        ),
        sa.CheckConstraint(
            "length(trim(provider_id)) > 0 AND length(origin) = 3 AND origin = upper(origin) "
            "AND length(destination) = 3 AND destination = upper(destination)",
            name="ck_agent_discovery_identity",
        ),
        sa.CheckConstraint("passengers > 0", name="ck_agent_discovery_passengers"),
        sa.CheckConstraint(
            "passenger_basis IN ('total_for_passengers', 'provider_single_adult_ticket')",
            name="ck_agent_discovery_passenger_basis",
        ),
        sa.CheckConstraint(
            "source_kind IN ('calendar', 'hot_offer', 'reference')",
            name="ck_agent_discovery_source_kind",
        ),
        sa.CheckConstraint(
            "freshness IN ('live_observed', 'user_confirmed', 'browser_observed', "
            "'api_cached', 'live', 'recent', 'cached', 'stale', 'unknown_external')",
            name="ck_agent_discovery_freshness",
        ),
        sa.CheckConstraint(
            "return_date IS NULL OR return_date >= departure_date",
            name="ck_agent_discovery_dates",
        ),
        sa.CheckConstraint(
            "created_at >= observed_at",
            name="ck_agent_discovery_chronology",
        ),
    )
    _create_household_run_stage_indexes("agent_discovery_signals")

    op.create_table(
        "agent_confirmed_offer_evidence",
        *_confirmed_evidence_columns(),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_agent_confirmed_evidence_fingerprint",
        ),
        *_evidence_checks("agent_confirmed_evidence"),
    )
    _create_household_run_stage_indexes("agent_confirmed_offer_evidence")

    op.create_table(
        "agent_composed_route_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("passengers", sa.Integer(), nullable=False),
        sa.Column("passenger_basis", sa.String(length=50), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("itinerary_evidence_json", sa.Text(), nullable=False),
        sa.Column("protection_status", sa.String(length=40), nullable=False),
        sa.Column("baggage_status", sa.String(length=30), nullable=True),
        sa.Column("transfer_status", sa.String(length=30), nullable=True),
        sa.Column("visa_status", sa.String(length=30), nullable=True),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_agent_composed_candidate_fingerprint",
        ),
        *_evidence_checks("agent_composed_candidate"),
    )
    _create_household_run_stage_indexes("agent_composed_route_candidates")

    op.create_table(
        "agent_ranking_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confirmed_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("composed_candidate_ids_json", sa.Text(), nullable=False),
        sa.Column("ranking_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_agent_ranking_fingerprint",
        ),
        sa.CheckConstraint(
            "confirmed_evidence_ids_json <> '[]' OR composed_candidate_ids_json <> '[]'",
            name="ck_agent_ranking_references",
        ),
    )
    op.create_index(
        "ix_agent_ranking_snapshots_household_id",
        "agent_ranking_snapshots",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_ranking_snapshots_run_id",
        "agent_ranking_snapshots",
        ["run_id"],
    )


def _confirmed_evidence_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness", sa.String(length=40), nullable=False),
        sa.Column("passengers", sa.Integer(), nullable=False),
        sa.Column("passenger_basis", sa.String(length=50), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("itinerary_evidence_json", sa.Text(), nullable=False),
        sa.Column("protection_status", sa.String(length=40), nullable=False),
        sa.Column("baggage_status", sa.String(length=30), nullable=True),
        sa.Column("transfer_status", sa.String(length=30), nullable=True),
        sa.Column("visa_status", sa.String(length=30), nullable=True),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def _evidence_checks(prefix: str) -> tuple[sa.CheckConstraint, ...]:
    checks = (
        sa.CheckConstraint(
            "passengers > 0 AND (amount_minor IS NULL OR amount_minor >= 0) AND "
            "((amount_minor IS NULL AND currency IS NULL) OR "
            "(amount_minor IS NOT NULL AND currency IS NOT NULL AND length(currency) = 3 "
            "AND currency = upper(currency)))",
            name=f"ck_{prefix}_money",
        ),
        sa.CheckConstraint(
            "passenger_basis IN ('total_for_passengers', 'provider_single_adult_ticket')",
            name=f"ck_{prefix}_passenger_basis",
        ),
        sa.CheckConstraint(
            "protection_status IN ('explicitly_protected', 'self_transfer', 'unknown')",
            name=f"ck_{prefix}_protection",
        ),
        sa.CheckConstraint(
            "baggage_status IS NULL OR baggage_status IN ('included', 'not_included', 'unknown')",
            name=f"ck_{prefix}_baggage",
        ),
        sa.CheckConstraint(
            "transfer_status IS NULL OR "
            "transfer_status IN ('protected', 'self_transfer', 'unknown')",
            name=f"ck_{prefix}_transfer",
        ),
        sa.CheckConstraint(
            "visa_status IS NULL OR visa_status IN ('required', 'not_required', 'unknown')",
            name=f"ck_{prefix}_visa",
        ),
        sa.CheckConstraint(
            "created_at >= observed_at",
            name=f"ck_{prefix}_chronology",
        ),
    )
    if prefix == "agent_confirmed_evidence":
        return (
            *checks,
            sa.CheckConstraint(
                "length(trim(provider_id)) > 0 AND length(trim(source)) > 0",
                name="ck_agent_confirmed_evidence_identity",
            ),
            sa.CheckConstraint(
                "freshness IN ('live_observed', 'user_confirmed', 'browser_observed', "
                "'api_cached', 'live', 'recent', 'cached', 'stale', 'unknown_external')",
                name="ck_agent_confirmed_evidence_freshness",
            ),
        )
    return (
        *checks,
        sa.CheckConstraint(
            "component_evidence_ids_json <> '[]'",
            name="ck_agent_composed_candidate_components",
        ),
    )


def _create_household_run_stage_indexes(table_name: str) -> None:
    op.create_index(f"ix_{table_name}_household_id", table_name, ["household_id"])
    op.create_index(f"ix_{table_name}_run_id", table_name, ["run_id"])
    op.create_index(f"ix_{table_name}_stage_id", table_name, ["stage_id"])


def downgrade() -> None:
    op.drop_table("agent_ranking_snapshots")
    op.drop_table("agent_composed_route_candidates")
    op.drop_table("agent_confirmed_offer_evidence")
    op.drop_table("agent_discovery_signals")
    op.drop_table("agent_run_scope_snapshots")
    op.drop_table("agent_provider_circuit_state")
    op.drop_table("agent_provider_http_attempts")
    op.drop_table("agent_provider_rate_locks")
    op.drop_table("agent_run_operations")
    op.drop_table("agent_plan_stages")
    with op.batch_alter_table("agent_plan_runs") as batch:
        batch.drop_constraint("ck_agent_plan_run_budgets", type_="check")
        batch.drop_column("http_attempts_consumed")
        batch.drop_column("http_attempt_budget")
        batch.drop_column("logical_operations_consumed")
        batch.drop_column("logical_operation_budget")
