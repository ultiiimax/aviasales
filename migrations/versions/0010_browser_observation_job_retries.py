from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0010_browser_observation_job_retries"
down_revision = "0009_deal_candidates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_observation_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "browser_observation_jobs",
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "browser_observation_jobs",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_browser_observation_jobs_next_retry_at",
        "browser_observation_jobs",
        ["next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_browser_observation_jobs_next_retry_at",
        table_name="browser_observation_jobs",
    )
    op.drop_column("browser_observation_jobs", "next_retry_at")
    op.drop_column("browser_observation_jobs", "last_attempted_at")
    op.drop_column("browser_observation_jobs", "attempts")
