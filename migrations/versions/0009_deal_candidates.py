from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0009_deal_candidates"
down_revision = "0008_browser_observation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deal_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("search_id", sa.String(length=160), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("discovered_url", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("extracted_origin", sa.String(length=3), nullable=True),
        sa.Column("extracted_destination", sa.String(length=3), nullable=True),
        sa.Column("extracted_departure_window", sa.String(length=120), nullable=True),
        sa.Column("extracted_price_minor_units", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requires_manual_verification", sa.Boolean(), nullable=False),
        sa.Column("raw_ref", sa.String(length=240), nullable=True),
    )
    op.create_index("ix_deal_candidates_household_id", "deal_candidates", ["household_id"])
    op.create_index("ix_deal_candidates_user_id", "deal_candidates", ["user_id"])
    op.create_index("ix_deal_candidates_search_id", "deal_candidates", ["search_id"])
    op.create_index("ix_deal_candidates_source_id", "deal_candidates", ["source_id"])
    op.create_index(
        "ix_deal_candidates_household_user_search",
        "deal_candidates",
        ["household_id", "user_id", "search_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_deal_candidates_household_user_search", table_name="deal_candidates")
    op.drop_index("ix_deal_candidates_source_id", table_name="deal_candidates")
    op.drop_index("ix_deal_candidates_search_id", table_name="deal_candidates")
    op.drop_index("ix_deal_candidates_user_id", table_name="deal_candidates")
    op.drop_index("ix_deal_candidates_household_id", table_name="deal_candidates")
    op.drop_table("deal_candidates")
