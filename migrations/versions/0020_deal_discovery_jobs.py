"""add deal discovery jobs

Revision ID: 0020_deal_discovery_jobs
Revises: 0019_worker_heartbeats
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_deal_discovery_jobs"
down_revision: str | Sequence[str] | None = "0019_worker_heartbeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deal_discovery_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("search_id", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False, unique=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=80), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("search_intent_json", sa.String(length=2000), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_deal_discovery_jobs_household_id",
        "deal_discovery_jobs",
        ["household_id"],
    )
    op.create_index(
        "ix_deal_discovery_jobs_user_id",
        "deal_discovery_jobs",
        ["user_id"],
    )
    op.create_index(
        "ix_deal_discovery_jobs_search_id",
        "deal_discovery_jobs",
        ["search_id"],
    )
    op.create_index(
        "ix_deal_discovery_jobs_status",
        "deal_discovery_jobs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_deal_discovery_jobs_status", table_name="deal_discovery_jobs")
    op.drop_index("ix_deal_discovery_jobs_search_id", table_name="deal_discovery_jobs")
    op.drop_index("ix_deal_discovery_jobs_user_id", table_name="deal_discovery_jobs")
    op.drop_index("ix_deal_discovery_jobs_household_id", table_name="deal_discovery_jobs")
    op.drop_table("deal_discovery_jobs")
