"""add airport commercial provenance

Revision ID: 0022_airport_commercial_provenance
Revises: 0021_worker_drain_control
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_airport_commercial_provenance"
down_revision: str | Sequence[str] | None = "0021_worker_drain_control"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("airports") as batch:
        batch.add_column(
            sa.Column(
                "scheduled_service",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.add_column(
            sa.Column(
                "commercial_provenance",
                sa.String(length=120),
                nullable=False,
                server_default="legacy_import_filter",
            )
        )

    with op.batch_alter_table("airports") as batch:
        batch.alter_column(
            "scheduled_service",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=None,
        )
        batch.alter_column(
            "commercial_provenance",
            existing_type=sa.String(length=120),
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("airports") as batch:
        batch.drop_column("commercial_provenance")
        batch.drop_column("scheduled_service")
