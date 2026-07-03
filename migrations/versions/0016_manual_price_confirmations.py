from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0016_manual_price_confirmations"
down_revision = "0015_watch_lifecycle_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "manual_price_confirmations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("target_kind", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=160), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_manual_price_confirmations_household_id",
        "manual_price_confirmations",
        ["household_id"],
    )
    op.create_index(
        "ix_manual_price_confirmations_user_id",
        "manual_price_confirmations",
        ["user_id"],
    )
    op.create_index(
        "ix_manual_price_confirmations_target_kind",
        "manual_price_confirmations",
        ["target_kind"],
    )
    op.create_index(
        "ix_manual_price_confirmations_target_id",
        "manual_price_confirmations",
        ["target_id"],
    )
    op.create_index(
        "ix_manual_price_confirmations_source_id",
        "manual_price_confirmations",
        ["source_id"],
    )
    op.create_index(
        "ix_manual_price_confirmations_status",
        "manual_price_confirmations",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_manual_price_confirmations_status", table_name="manual_price_confirmations")
    op.drop_index(
        "ix_manual_price_confirmations_source_id", table_name="manual_price_confirmations"
    )
    op.drop_index(
        "ix_manual_price_confirmations_target_id", table_name="manual_price_confirmations"
    )
    op.drop_index(
        "ix_manual_price_confirmations_target_kind",
        table_name="manual_price_confirmations",
    )
    op.drop_index("ix_manual_price_confirmations_user_id", table_name="manual_price_confirmations")
    op.drop_index(
        "ix_manual_price_confirmations_household_id",
        table_name="manual_price_confirmations",
    )
    op.drop_table("manual_price_confirmations")
