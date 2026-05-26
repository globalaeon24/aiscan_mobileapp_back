"""mobile core tables

Revision ID: 001_mobile_core
Revises:
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_mobile_core"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    op.create_table(
        "mobile_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("core_user_id", sa.String(length=128), nullable=False),
        sa.Column("core_organization_id", sa.String(length=128), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("core_user_id", name="uq_mobile_users_core_user_id"),
    )
    op.create_index("ix_mobile_users_core_user_id", "mobile_users", ["core_user_id"])
    op.create_index("ix_mobile_users_core_organization_id", "mobile_users", ["core_organization_id"])
    op.create_index("ix_mobile_users_phone", "mobile_users", ["phone"])
    op.create_index("ix_mobile_users_email", "mobile_users", ["email"])
    op.create_index("ix_mobile_users_status", "mobile_users", ["status"])
    op.create_index("ix_mobile_users_created_at", "mobile_users", ["created_at"])

    op.create_table(
        "mobile_devices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("device_model", sa.String(length=255), nullable=True),
        sa.Column("os_version", sa.String(length=64), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("push_token", sa.Text(), nullable=True),
        sa.Column("push_provider", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("mobile_user_id", "device_id", name="uq_mobile_devices_user_device"),
    )
    op.create_index("ix_mobile_devices_mobile_user_id", "mobile_devices", ["mobile_user_id"])
    op.create_index("ix_mobile_devices_device_id", "mobile_devices", ["device_id"])
    op.create_index("ix_mobile_devices_platform", "mobile_devices", ["platform"])
    op.create_index("ix_mobile_devices_is_active", "mobile_devices", ["is_active"])
    op.create_index("ix_mobile_devices_created_at", "mobile_devices", ["created_at"])

    op.create_table(
        "mobile_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("access_token_jti", sa.String(length=255), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("refresh_token_hash", name="uq_mobile_sessions_refresh_token_hash"),
    )
    op.create_index("ix_mobile_sessions_mobile_user_id", "mobile_sessions", ["mobile_user_id"])
    op.create_index("ix_mobile_sessions_device_id", "mobile_sessions", ["device_id"])
    op.create_index("ix_mobile_sessions_status", "mobile_sessions", ["status"])
    op.create_index("ix_mobile_sessions_refresh_token_hash", "mobile_sessions", ["refresh_token_hash"])
    op.create_index("ix_mobile_sessions_expires_at", "mobile_sessions", ["expires_at"])
    op.create_index("ix_mobile_sessions_created_at", "mobile_sessions", ["created_at"])

    op.create_table(
        "push_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_push_tokens_mobile_user_id", "push_tokens", ["mobile_user_id"])
    op.create_index("ix_push_tokens_device_id", "push_tokens", ["device_id"])
    op.create_index("ix_push_tokens_token", "push_tokens", ["token"])
    op.create_index("ix_push_tokens_is_active", "push_tokens", ["is_active"])
    op.create_index("ix_push_tokens_created_at", "push_tokens", ["created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_notifications_mobile_user_id", "notifications", ["mobile_user_id"])
    op.create_index("ix_notifications_notification_type", "notifications", ["notification_type"])
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("notification_id", sa.BigInteger(), nullable=False),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"]),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
    op.create_index("ix_notification_deliveries_mobile_user_id", "notification_deliveries", ["mobile_user_id"])
    op.create_index("ix_notification_deliveries_device_id", "notification_deliveries", ["device_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index("ix_notification_deliveries_created_at", "notification_deliveries", ["created_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("core_user_id", sa.String(length=128), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("session_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=True),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["mobile_sessions.id"]),
    )
    op.create_index("ix_audit_logs_mobile_user_id", "audit_logs", ["mobile_user_id"])
    op.create_index("ix_audit_logs_core_user_id", "audit_logs", ["core_user_id"])
    op.create_index("ix_audit_logs_device_id", "audit_logs", ["device_id"])
    op.create_index("ix_audit_logs_session_id", "audit_logs", ["session_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("push_tokens")
    op.drop_table("mobile_sessions")
    op.drop_table("mobile_devices")
    op.drop_table("mobile_users")
