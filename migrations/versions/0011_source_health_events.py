from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0011_source_health_events"
down_revision = "0010_browser_observation_job_retries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_health_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_source_health_events_source_id", "source_health_events", ["source_id"])
    op.create_index("ix_source_health_events_event_type", "source_health_events", ["event_type"])
    op.create_index("ix_source_health_events_status", "source_health_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_source_health_events_status", table_name="source_health_events")
    op.drop_index("ix_source_health_events_event_type", table_name="source_health_events")
    op.drop_index("ix_source_health_events_source_id", table_name="source_health_events")
    op.drop_table("source_health_events")
