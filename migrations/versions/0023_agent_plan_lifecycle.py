"""persist immutable agent plans, approvals, and runs

Revision ID: 0023_agent_plan_lifecycle
Revises: 0022_airport_commercial_provenance
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_agent_plan_lifecycle"
down_revision: str | Sequence[str] | None = "0022_airport_commercial_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_search_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_search_plans_household_id",
        "agent_search_plans",
        ["household_id"],
    )

    op.create_table(
        "agent_search_plan_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "plan_id",
            sa.String(length=36),
            sa.ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("source_revision_id", sa.String(length=36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("scope_snapshot_json", sa.Text(), nullable=False),
        sa.Column("capability_snapshot_json", sa.Text(), nullable=False),
        sa.Column("cost_model_snapshot_json", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=False),
        sa.Column("planner_version", sa.String(length=120), nullable=False),
        sa.Column("estimated_calendar_searches", sa.Integer(), nullable=True),
        sa.Column("estimated_exact_searches", sa.Integer(), nullable=True),
        sa.Column("estimated_logical_operations", sa.Integer(), nullable=True),
        sa.Column("estimated_http_attempts", sa.Integer(), nullable=True),
        sa.Column("estimated_deadline_seconds", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=71), nullable=False),
        sa.Column("clone_idempotency_key", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("plan_id", "revision_number", name="uq_agent_plan_revision_number"),
        sa.UniqueConstraint("plan_id", "content_hash", name="uq_agent_plan_revision_hash"),
        sa.CheckConstraint(
            "state IN ('draft', 'awaiting_approval', 'superseded', 'consumed', 'expired')",
            name="ck_agent_plan_revision_state",
        ),
        sa.CheckConstraint(
            "state != 'awaiting_approval' OR ("
            "estimated_calendar_searches IS NOT NULL AND "
            "estimated_calendar_searches >= 0 AND "
            "estimated_exact_searches IS NOT NULL AND estimated_exact_searches >= 0 AND "
            "estimated_logical_operations IS NOT NULL AND "
            "estimated_logical_operations > 0 AND "
            "estimated_logical_operations = "
            "estimated_calendar_searches + estimated_exact_searches AND "
            "estimated_http_attempts IS NOT NULL AND estimated_http_attempts > 0 AND "
            "estimated_deadline_seconds IS NOT NULL AND estimated_deadline_seconds > 0)",
            name="ck_agent_plan_revision_estimates",
        ),
    )
    op.create_index(
        "ix_agent_search_plan_revisions_plan_id",
        "agent_search_plan_revisions",
        ["plan_id"],
    )
    op.create_index(
        "ix_agent_search_plan_revisions_household_id",
        "agent_search_plan_revisions",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_search_plan_revisions_state",
        "agent_search_plan_revisions",
        ["state"],
    )
    op.create_index(
        "ix_agent_plan_revision_clone_idempotency",
        "agent_search_plan_revisions",
        ["household_id", "clone_idempotency_key"],
        unique=True,
        sqlite_where=sa.text("clone_idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("clone_idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "agent_plan_execution_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "plan_id",
            sa.String(length=36),
            sa.ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            sa.String(length=36),
            sa.ForeignKey("agent_search_plan_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=False),
        sa.Column("revision_content_hash", sa.String(length=71), nullable=False),
        sa.Column("approved_by_session_id", sa.String(length=36), nullable=False),
        sa.Column("approved_budget_json", sa.Text(), nullable=False),
        sa.Column("approved_strategies_json", sa.Text(), nullable=False),
        sa.Column("risk_warning_versions_json", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.UniqueConstraint("run_id", name="uq_agent_approval_run"),
    )
    op.create_index(
        "ix_agent_plan_execution_approvals_household_id",
        "agent_plan_execution_approvals",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_plan_execution_approvals_plan_id",
        "agent_plan_execution_approvals",
        ["plan_id"],
    )
    op.create_index(
        "ix_agent_plan_execution_approvals_revision_id",
        "agent_plan_execution_approvals",
        ["revision_id"],
    )

    op.create_table(
        "agent_plan_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "plan_id",
            sa.String(length=36),
            sa.ForeignKey("agent_search_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "revision_id",
            sa.String(length=36),
            sa.ForeignKey("agent_search_plan_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "approval_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_execution_approvals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("execute_idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.UniqueConstraint(
            "household_id",
            "execute_idempotency_key",
            name="uq_agent_run_execute_idempotency",
        ),
        sa.UniqueConstraint("approval_id", name="uq_agent_run_approval"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', "
            "'completed', 'partial', 'failed', 'cancelled')",
            name="ck_agent_plan_run_status",
        ),
        sa.CheckConstraint(
            "(started_at IS NULL OR started_at >= created_at) AND "
            "(cancel_requested_at IS NULL OR cancel_requested_at >= created_at) AND "
            "(finished_at IS NULL OR finished_at >= created_at) AND "
            "(finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at) AND "
            "(finished_at IS NULL OR cancel_requested_at IS NULL OR "
            "finished_at >= cancel_requested_at)",
            name="ck_agent_plan_run_chronology",
        ),
    )
    op.create_index("ix_agent_plan_runs_household_id", "agent_plan_runs", ["household_id"])
    op.create_index("ix_agent_plan_runs_plan_id", "agent_plan_runs", ["plan_id"])
    op.create_index("ix_agent_plan_runs_revision_id", "agent_plan_runs", ["revision_id"])
    op.create_index("ix_agent_plan_runs_status", "agent_plan_runs", ["status"])
    op.create_index(
        "ix_agent_plan_one_active_run",
        "agent_plan_runs",
        ["plan_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_plan_one_active_run", table_name="agent_plan_runs")
    op.drop_table("agent_plan_runs")
    op.drop_table("agent_plan_execution_approvals")
    op.drop_index(
        "ix_agent_plan_revision_clone_idempotency",
        table_name="agent_search_plan_revisions",
    )
    op.drop_table("agent_search_plan_revisions")
    op.drop_table("agent_search_plans")
