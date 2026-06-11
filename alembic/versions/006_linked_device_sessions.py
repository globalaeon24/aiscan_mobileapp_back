"""linked device sessions

Revision ID: 006_linked_device_sessions
Revises: 005_mobile_settings_integrations
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "006_linked_device_sessions"
down_revision: Union[str, Sequence[str], None] = "005_mobile_settings_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "linked_device_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("core_session_id", sa.String(length=128), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("browser", sa.String(length=128), nullable=True),
        sa.Column("platform", sa.String(length=128), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("mobile_user_id", "core_session_id", name="uq_linked_device_sessions_user_core_session"),
    )
    op.create_index("ix_linked_device_sessions_mobile_user_id", "linked_device_sessions", ["mobile_user_id"])
    op.create_index("ix_linked_device_sessions_core_session_id", "linked_device_sessions", ["core_session_id"])
    op.create_index("ix_linked_device_sessions_status", "linked_device_sessions", ["status"])
    op.create_index("ix_linked_device_sessions_last_active_at", "linked_device_sessions", ["last_active_at"])
    op.create_index("ix_linked_device_sessions_created_at", "linked_device_sessions", ["created_at"])


def downgrade() -> None:
    op.drop_table("linked_device_sessions")
