"""mobile settings and integration tables

Revision ID: 005_mobile_settings_integrations
Revises: 004_mobile_admin
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005_mobile_settings_integrations"
down_revision: Union[str, Sequence[str], None] = "004_mobile_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mobile_user_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), nullable=False),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("biometric_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("mobile_user_id", name="uq_mobile_user_settings_mobile_user_id"),
    )
    op.create_index("ix_mobile_user_settings_mobile_user_id", "mobile_user_settings", ["mobile_user_id"])
    op.create_index("ix_mobile_user_settings_created_at", "mobile_user_settings", ["created_at"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("push_enabled", sa.Boolean(), nullable=False),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False),
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("mobile_user_id", "notification_type", name="uq_notification_preferences_user_type"),
    )
    op.create_index("ix_notification_preferences_mobile_user_id", "notification_preferences", ["mobile_user_id"])
    op.create_index("ix_notification_preferences_notification_type", "notification_preferences", ["notification_type"])
    op.create_index("ix_notification_preferences_created_at", "notification_preferences", ["created_at"])

    op.create_table(
        "app_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("build_number", sa.String(length=64), nullable=False),
        sa.Column("min_supported_version", sa.String(length=64), nullable=True),
        sa.Column("force_update", sa.Boolean(), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("platform", "version", "build_number", name="uq_app_versions_platform_version_build"),
    )
    op.create_index("ix_app_versions_platform", "app_versions", ["platform"])
    op.create_index("ix_app_versions_created_at", "app_versions", ["created_at"])

    op.create_table(
        "core_api_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("endpoint", sa.String(length=512), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_core_api_requests_mobile_user_id", "core_api_requests", ["mobile_user_id"])
    op.create_index("ix_core_api_requests_method", "core_api_requests", ["method"])
    op.create_index("ix_core_api_requests_endpoint", "core_api_requests", ["endpoint"])
    op.create_index("ix_core_api_requests_status_code", "core_api_requests", ["status_code"])
    op.create_index("ix_core_api_requests_request_id", "core_api_requests", ["request_id"])
    op.create_index("ix_core_api_requests_created_at", "core_api_requests", ["created_at"])

    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_sync_jobs_job_type", "sync_jobs", ["job_type"])
    op.create_index("ix_sync_jobs_status", "sync_jobs", ["status"])
    op.create_index("ix_sync_jobs_created_at", "sync_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_table("sync_jobs")
    op.drop_table("core_api_requests")
    op.drop_table("app_versions")
    op.drop_table("notification_preferences")
    op.drop_table("mobile_user_settings")
