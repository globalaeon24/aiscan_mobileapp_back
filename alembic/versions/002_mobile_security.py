"""mobile security tables

Revision ID: 002_mobile_security
Revises: 001_mobile_core
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_mobile_security"
down_revision: Union[str, Sequence[str], None] = "001_mobile_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "qr_login_sessions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_token_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("web_session_id", sa.String(length=255), nullable=True),
        sa.Column("requested_ip", sa.String(length=64), nullable=True),
        sa.Column("requested_user_agent", sa.Text(), nullable=True),
        sa.Column("approved_by_mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_device_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["approved_by_mobile_user_id"], ["mobile_users.id"]),
        sa.UniqueConstraint("qr_token_hash", name="uq_qr_login_sessions_qr_token_hash"),
    )
    op.create_index("ix_qr_login_sessions_qr_token_hash", "qr_login_sessions", ["qr_token_hash"])
    op.create_index("ix_qr_login_sessions_status", "qr_login_sessions", ["status"])
    op.create_index("ix_qr_login_sessions_expires_at", "qr_login_sessions", ["expires_at"])
    op.create_index("ix_qr_login_sessions_approved_by_mobile_user_id", "qr_login_sessions", ["approved_by_mobile_user_id"])
    op.create_index("ix_qr_login_sessions_created_at", "qr_login_sessions", ["created_at"])

    op.create_table(
        "qr_login_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("qr_login_session_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["qr_login_session_id"], ["qr_login_sessions.id"]),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_qr_login_events_qr_login_session_id", "qr_login_events", ["qr_login_session_id"])
    op.create_index("ix_qr_login_events_event_type", "qr_login_events", ["event_type"])
    op.create_index("ix_qr_login_events_mobile_user_id", "qr_login_events", ["mobile_user_id"])
    op.create_index("ix_qr_login_events_device_id", "qr_login_events", ["device_id"])
    op.create_index("ix_qr_login_events_created_at", "qr_login_events", ["created_at"])

    op.create_table(
        "two_factor_challenges",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("challenge_type", sa.String(length=64), nullable=False),
        sa.Column("delivery_channel", sa.String(length=32), nullable=False),
        sa.Column("destination_masked", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_two_factor_challenges_mobile_user_id", "two_factor_challenges", ["mobile_user_id"])
    op.create_index("ix_two_factor_challenges_challenge_type", "two_factor_challenges", ["challenge_type"])
    op.create_index("ix_two_factor_challenges_status", "two_factor_challenges", ["status"])
    op.create_index("ix_two_factor_challenges_expires_at", "two_factor_challenges", ["expires_at"])
    op.create_index("ix_two_factor_challenges_created_at", "two_factor_challenges", ["created_at"])

    op.create_table(
        "two_factor_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("challenge_id", sa.BigInteger(), nullable=False),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("attempt_result", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["challenge_id"], ["two_factor_challenges.id"]),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_two_factor_attempts_challenge_id", "two_factor_attempts", ["challenge_id"])
    op.create_index("ix_two_factor_attempts_mobile_user_id", "two_factor_attempts", ["mobile_user_id"])
    op.create_index("ix_two_factor_attempts_attempt_result", "two_factor_attempts", ["attempt_result"])
    op.create_index("ix_two_factor_attempts_device_id", "two_factor_attempts", ["device_id"])
    op.create_index("ix_two_factor_attempts_created_at", "two_factor_attempts", ["created_at"])

    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_security_events_mobile_user_id", "security_events", ["mobile_user_id"])
    op.create_index("ix_security_events_event_type", "security_events", ["event_type"])
    op.create_index("ix_security_events_severity", "security_events", ["severity"])
    op.create_index("ix_security_events_device_id", "security_events", ["device_id"])
    op.create_index("ix_security_events_created_at", "security_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("security_events")
    op.drop_table("two_factor_attempts")
    op.drop_table("two_factor_challenges")
    op.drop_table("qr_login_events")
    op.drop_table("qr_login_sessions")
