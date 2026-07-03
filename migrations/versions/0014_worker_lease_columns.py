from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0014_worker_lease_columns"
down_revision = "0013_telegram_linking_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_observation_jobs",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "browser_observation_jobs",
        sa.Column("locked_by", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "telegram_notification_outbox",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "telegram_notification_outbox",
        sa.Column("locked_by", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_notification_outbox", "locked_by")
    op.drop_column("telegram_notification_outbox", "locked_at")
    op.drop_column("browser_observation_jobs", "locked_by")
    op.drop_column("browser_observation_jobs", "locked_at")
