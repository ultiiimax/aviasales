from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0017_invitation_auth_foundation"
down_revision = "0016_manual_price_confirmations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "households",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "household_memberships",
        sa.Column("household_id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_household_memberships_user_id",
        "household_memberships",
        ["user_id"],
    )
    op.create_index(
        "ix_household_memberships_role",
        "household_memberships",
        ["role"],
    )
    op.create_table(
        "auth_invitations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("recipient_label", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_auth_invitations_household_id",
        "auth_invitations",
        ["household_id"],
    )
    op.create_index(
        "ix_auth_invitations_invited_by_user_id",
        "auth_invitations",
        ["invited_by_user_id"],
    )
    op.create_index(
        "ix_auth_invitations_code_hash",
        "auth_invitations",
        ["code_hash"],
        unique=True,
    )
    op.create_index(
        "ix_auth_invitations_expires_at",
        "auth_invitations",
        ["expires_at"],
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_sessions_household_id", "auth_sessions", ["household_id"])
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_household_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_auth_invitations_expires_at", table_name="auth_invitations")
    op.drop_index("ix_auth_invitations_code_hash", table_name="auth_invitations")
    op.drop_index("ix_auth_invitations_invited_by_user_id", table_name="auth_invitations")
    op.drop_index("ix_auth_invitations_household_id", table_name="auth_invitations")
    op.drop_table("auth_invitations")
    op.drop_index("ix_household_memberships_role", table_name="household_memberships")
    op.drop_index("ix_household_memberships_user_id", table_name="household_memberships")
    op.drop_table("household_memberships")
    op.drop_table("users")
    op.drop_table("households")
