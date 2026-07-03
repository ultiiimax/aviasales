from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0013_telegram_linking_outbox"
down_revision = "0012_watch_scan_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_link_codes",
        sa.Column("code", sa.String(length=32), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_telegram_link_codes_household_id", "telegram_link_codes", ["household_id"])
    op.create_index("ix_telegram_link_codes_user_id", "telegram_link_codes", ["user_id"])

    op.create_table(
        "telegram_accounts",
        sa.Column("user_id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("telegram_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("chat_id", sa.Integer(), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_telegram_accounts_household_id", "telegram_accounts", ["household_id"])

    op.create_table(
        "telegram_notification_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("household_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("chat_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("dedupe_key", sa.String(length=240), nullable=False, unique=True),
        sa.Column("payload_json", sa.String(length=4000), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
    )
    op.create_index(
        "ix_telegram_notification_outbox_household_id",
        "telegram_notification_outbox",
        ["household_id"],
    )
    op.create_index(
        "ix_telegram_notification_outbox_user_id",
        "telegram_notification_outbox",
        ["user_id"],
    )
    op.create_index(
        "ix_telegram_notification_outbox_status",
        "telegram_notification_outbox",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telegram_notification_outbox_status", table_name="telegram_notification_outbox"
    )
    op.drop_index(
        "ix_telegram_notification_outbox_user_id", table_name="telegram_notification_outbox"
    )
    op.drop_index(
        "ix_telegram_notification_outbox_household_id",
        table_name="telegram_notification_outbox",
    )
    op.drop_table("telegram_notification_outbox")
    op.drop_index("ix_telegram_accounts_household_id", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
    op.drop_index("ix_telegram_link_codes_user_id", table_name="telegram_link_codes")
    op.drop_index("ix_telegram_link_codes_household_id", table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
