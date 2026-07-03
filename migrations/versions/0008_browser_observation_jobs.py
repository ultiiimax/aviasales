from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0008_browser_observation_jobs"
down_revision = "0007_browser_observed_offers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "browser_observation_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("search_id", sa.String(length=160), nullable=False),
        sa.Column("search_intent_hash", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("grant_id", sa.String(length=36), nullable=False),
        sa.Column("origin", sa.String(length=3), nullable=False),
        sa.Column("destination", sa.String(length=3), nullable=False),
        sa.Column("departure_date", sa.String(length=10), nullable=False),
        sa.Column("return_date", sa.String(length=10), nullable=True),
        sa.Column("passengers", sa.Integer(), nullable=False),
        sa.Column("adults", sa.Integer(), nullable=False),
        sa.Column("children", sa.Integer(), nullable=False),
        sa.Column("infants", sa.Integer(), nullable=False),
        sa.Column("trip_type", sa.String(length=40), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_browser_observation_jobs_household_id",
        "browser_observation_jobs",
        ["household_id"],
    )
    op.create_index("ix_browser_observation_jobs_user_id", "browser_observation_jobs", ["user_id"])
    op.create_index(
        "ix_browser_observation_jobs_source_id",
        "browser_observation_jobs",
        ["source_id"],
    )
    op.create_index(
        "ix_browser_observation_jobs_search_id",
        "browser_observation_jobs",
        ["search_id"],
    )
    op.create_index(
        "ix_browser_observation_jobs_grant_id",
        "browser_observation_jobs",
        ["grant_id"],
    )
    op.create_index(
        "uq_browser_observation_jobs_idempotency",
        "browser_observation_jobs",
        ["household_id", "user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_browser_observation_jobs_idempotency", table_name="browser_observation_jobs")
    op.drop_index("ix_browser_observation_jobs_grant_id", table_name="browser_observation_jobs")
    op.drop_index("ix_browser_observation_jobs_search_id", table_name="browser_observation_jobs")
    op.drop_index("ix_browser_observation_jobs_source_id", table_name="browser_observation_jobs")
    op.drop_index("ix_browser_observation_jobs_user_id", table_name="browser_observation_jobs")
    op.drop_index(
        "ix_browser_observation_jobs_household_id",
        table_name="browser_observation_jobs",
    )
    op.drop_table("browser_observation_jobs")
