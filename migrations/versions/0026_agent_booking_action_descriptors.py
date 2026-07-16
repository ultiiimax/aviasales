"""store opaque household-scoped agent booking descriptors

Revision ID: 0026_agent_booking_action_descriptors
Revises: 0025_agent_anywhere_discovery
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_agent_booking_action_descriptors"
down_revision: str | Sequence[str] | None = "0025_agent_anywhere_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_booking_action_descriptors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("agent_plan_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "confirmed_evidence_id",
            sa.String(length=36),
            sa.ForeignKey(
                "agent_confirmed_offer_evidence.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(length=80), nullable=False),
        sa.Column("private_descriptor_json", sa.Text(), nullable=False),
        sa.Column("fingerprint", sa.String(length=71), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "confirmed_evidence_id",
            name="uq_agent_booking_descriptor_evidence",
        ),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name="uq_agent_booking_descriptor_fingerprint",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_agent_booking_descriptor_chronology",
        ),
    )
    op.create_index(
        "ix_agent_booking_action_descriptors_household_id",
        "agent_booking_action_descriptors",
        ["household_id"],
    )
    op.create_index(
        "ix_agent_booking_action_descriptors_run_id",
        "agent_booking_action_descriptors",
        ["run_id"],
    )
    op.create_index(
        "ix_agent_booking_action_descriptors_confirmed_evidence_id",
        "agent_booking_action_descriptors",
        ["confirmed_evidence_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_booking_action_descriptors_confirmed_evidence_id",
        table_name="agent_booking_action_descriptors",
    )
    op.drop_index(
        "ix_agent_booking_action_descriptors_run_id",
        table_name="agent_booking_action_descriptors",
    )
    op.drop_index(
        "ix_agent_booking_action_descriptors_household_id",
        table_name="agent_booking_action_descriptors",
    )
    op.drop_table("agent_booking_action_descriptors")
