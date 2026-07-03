"""add browser observation operator controls

Revision ID: 0018_browser_observation_operator_controls
Revises: 0017_invitation_auth_foundation
Create Date: 2026-06-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_browser_observation_operator_controls"
down_revision: str | Sequence[str] | None = "0017_invitation_auth_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_observation_jobs",
        sa.Column("operator_resume_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "browser_observation_jobs",
        sa.Column("operator_abort_requested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("browser_observation_jobs", "operator_abort_requested_at")
    op.drop_column("browser_observation_jobs", "operator_resume_requested_at")
