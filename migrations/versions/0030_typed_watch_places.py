"""persist frozen typed watch places

Revision ID: 0030_typed_watch_places
Revises: 0029_agent_operation_telemetry
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_typed_watch_places"
down_revision: str | Sequence[str] | None = "0029_agent_operation_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("watches") as batch:
        batch.add_column(
            sa.Column(
                "origin_kind",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'city'"),
            )
        )
        batch.add_column(
            sa.Column(
                "destination_kind",
                sa.String(length=16),
                nullable=False,
                server_default=sa.text("'city'"),
            )
        )
        batch.add_column(
            sa.Column(
                "origin_airport_codes_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "destination_airport_codes_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(
            sa.Column(
                "directory_version",
                sa.String(length=160),
                nullable=False,
                server_default=sa.text("'legacy-provider-city-v1'"),
            )
        )
        batch.add_column(
            sa.Column("origin_membership_version", sa.String(length=160), nullable=True)
        )
        batch.add_column(
            sa.Column("destination_membership_version", sa.String(length=160), nullable=True)
        )

    with op.batch_alter_table("watches") as batch:
        batch.alter_column(
            "origin_kind",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default=None,
        )
        batch.alter_column(
            "destination_kind",
            existing_type=sa.String(length=16),
            existing_nullable=False,
            server_default=None,
        )
        batch.alter_column(
            "origin_airport_codes_json",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default=None,
        )
        batch.alter_column(
            "destination_airport_codes_json",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default=None,
        )
        batch.alter_column(
            "directory_version",
            existing_type=sa.String(length=160),
            existing_nullable=False,
            server_default=None,
        )


def downgrade() -> None:
    with op.batch_alter_table("watches") as batch:
        batch.drop_column("destination_membership_version")
        batch.drop_column("origin_membership_version")
        batch.drop_column("directory_version")
        batch.drop_column("destination_airport_codes_json")
        batch.drop_column("origin_airport_codes_json")
        batch.drop_column("destination_kind")
        batch.drop_column("origin_kind")
