"""add fare analysis history and immutable snapshots

Revision ID: 0028_agent_fare_analysis_history
Revises: 0027_agent_hidden_city_research
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_agent_fare_analysis_history"
down_revision: str | Sequence[str] | None = "0027_agent_hidden_city_research"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESULT_TYPE_CHECK = (
    "result_type IS NULL OR result_type IN ('scope_snapshot', 'discovery_signal', "
    "'confirmed_offer', 'composed_candidate', 'ranking_snapshot', "
    "'analysis_snapshot', 'operation')"
)
_OLD_RESULT_TYPE_CHECK = (
    "result_type IS NULL OR result_type IN ('scope_snapshot', 'discovery_signal', "
    "'confirmed_offer', 'composed_candidate', 'ranking_snapshot', 'operation')"
)


def upgrade() -> None:
    op.add_column(
        "agent_confirmed_offer_evidence",
        sa.Column("history_series_hash", sa.String(length=71), nullable=True),
    )
    op.create_index(
        "ix_agent_confirmed_evidence_history_series",
        "agent_confirmed_offer_evidence",
        ["household_id", "history_series_hash", "observed_at", "id"],
    )

    op.create_table(
        "agent_analysis_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_evidence_ids_json", sa.Text(), nullable=False),
        sa.Column("analysis_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_agent_analysis_snapshot_run"),
        sa.CheckConstraint(
            "source_evidence_ids_json <> '[]'",
            name="ck_agent_analysis_snapshot_references",
        ),
        sa.CheckConstraint(
            "analysis_json <> '{}'",
            name="ck_agent_analysis_snapshot_payload",
        ),
        sa.CheckConstraint(
            "length(fingerprint) = 71",
            name="ck_agent_analysis_snapshot_fingerprint",
        ),
    )
    op.create_index(
        "ix_agent_analysis_snapshots_household_id",
        "agent_analysis_snapshots",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_analysis_snapshots_run_id",
        "agent_analysis_snapshots",
        ["run_id"],
    )

    _replace_result_type_check(_RESULT_TYPE_CHECK)


def downgrade() -> None:
    _replace_result_type_check(_OLD_RESULT_TYPE_CHECK)

    op.drop_index(
        "ix_agent_analysis_snapshots_run_id",
        table_name="agent_analysis_snapshots",
    )
    op.drop_index(
        "ix_agent_analysis_snapshots_household_id",
        table_name="agent_analysis_snapshots",
    )
    op.drop_table("agent_analysis_snapshots")

    op.drop_index(
        "ix_agent_confirmed_evidence_history_series",
        table_name="agent_confirmed_offer_evidence",
    )
    with op.batch_alter_table("agent_confirmed_offer_evidence") as batch:
        batch.drop_column("history_series_hash")


def _replace_result_type_check(check_sql: str) -> None:
    with op.batch_alter_table("agent_run_operations") as batch:
        batch.drop_constraint("ck_agent_run_operation_result_type", type_="check")
        batch.create_check_constraint(
            "ck_agent_run_operation_result_type",
            check_sql,
        )
