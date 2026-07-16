"""persist cumulative agent operation telemetry

Revision ID: 0029_agent_operation_telemetry
Revises: 0028_agent_fare_analysis_history
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_agent_operation_telemetry"
down_revision: str | Sequence[str] | None = "0028_agent_fare_analysis_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_run_operations",
        sa.Column(
            "provider_denial_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agent_run_operations",
        sa.Column(
            "lease_recovery_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_run_operations", "lease_recovery_count")
    op.drop_column("agent_run_operations", "provider_denial_count")
