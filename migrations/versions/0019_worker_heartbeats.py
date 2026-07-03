"""add worker heartbeats

Revision ID: 0019_worker_heartbeats
Revises: 0018_browser_observation_operator_controls
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_worker_heartbeats"
down_revision: str | Sequence[str] | None = "0018_browser_observation_operator_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=120), primary_key=True),
        sa.Column("role", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_phase", sa.String(length=80), nullable=False),
        sa.Column("current_job_kind", sa.String(length=80), nullable=True),
        sa.Column("current_job_id", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_summary_json", sa.String(length=4000), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_worker_heartbeats_role",
        "worker_heartbeats",
        ["role"],
    )
    op.create_index(
        "ix_worker_heartbeats_status",
        "worker_heartbeats",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_status", table_name="worker_heartbeats")
    op.drop_index("ix_worker_heartbeats_role", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
