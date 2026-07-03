from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0012_watch_scan_jobs"
down_revision = "0011_source_health_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "watches",
        sa.Column("passengers", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "watches",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
    )
    op.add_column("watches", sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "watches",
        sa.Column("next_eligible_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "watches",
        sa.Column(
            "scan_interval_seconds",
            sa.Integer(),
            nullable=False,
            server_default="21600",
        ),
    )
    op.add_column(
        "watches",
        sa.Column(
            "allowed_provider_ids",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "watches",
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "watches",
        sa.Column("last_scan_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "watches",
        sa.Column("last_scan_error_code", sa.String(length=80), nullable=True),
    )
    op.create_index("ix_watches_next_eligible_at", "watches", ["next_eligible_at"])

    op.create_table(
        "watch_scan_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("watch_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False, unique=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=80), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_ids", sa.String(length=500), nullable=False),
        sa.Column(
            "provider_denials",
            sa.String(length=2000),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.create_index("ix_watch_scan_jobs_household_id", "watch_scan_jobs", ["household_id"])
    op.create_index("ix_watch_scan_jobs_watch_id", "watch_scan_jobs", ["watch_id"])
    op.create_index("ix_watch_scan_jobs_status", "watch_scan_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_watch_scan_jobs_status", table_name="watch_scan_jobs")
    op.drop_index("ix_watch_scan_jobs_watch_id", table_name="watch_scan_jobs")
    op.drop_index("ix_watch_scan_jobs_household_id", table_name="watch_scan_jobs")
    op.drop_table("watch_scan_jobs")
    op.drop_index("ix_watches_next_eligible_at", table_name="watches")
    op.drop_column("watches", "last_scan_error_code")
    op.drop_column("watches", "last_scan_status")
    op.drop_column("watches", "last_scanned_at")
    op.drop_column("watches", "allowed_provider_ids")
    op.drop_column("watches", "scan_interval_seconds")
    op.drop_column("watches", "next_eligible_at")
    op.drop_column("watches", "paused_until")
    op.drop_column("watches", "currency")
    op.drop_column("watches", "passengers")
