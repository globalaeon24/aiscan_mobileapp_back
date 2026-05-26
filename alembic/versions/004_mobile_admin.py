"""mobile admin action tables

Revision ID: 004_mobile_admin
Revises: 003_mobile_checks
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004_mobile_admin"
down_revision: Union[str, Sequence[str], None] = "003_mobile_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_delegation_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("requested_by_mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_core_user_id", sa.String(length=128), nullable=True),
        sa.Column("target_phone", sa.String(length=32), nullable=True),
        sa.Column("target_email", sa.String(length=255), nullable=True),
        sa.Column("core_organization_id", sa.String(length=128), nullable=True),
        sa.Column("requested_role", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requires_2fa", sa.Boolean(), nullable=False),
        sa.Column("two_factor_challenge_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_mobile_user_id"], ["mobile_users.id"]),
        sa.ForeignKeyConstraint(["two_factor_challenge_id"], ["two_factor_challenges.id"]),
    )
    op.create_index("ix_access_delegation_requests_requested_by_mobile_user_id", "access_delegation_requests", ["requested_by_mobile_user_id"])
    op.create_index("ix_access_delegation_requests_target_core_user_id", "access_delegation_requests", ["target_core_user_id"])
    op.create_index("ix_access_delegation_requests_core_organization_id", "access_delegation_requests", ["core_organization_id"])
    op.create_index("ix_access_delegation_requests_status", "access_delegation_requests", ["status"])
    op.create_index("ix_access_delegation_requests_created_at", "access_delegation_requests", ["created_at"])

    op.create_table(
        "admin_action_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("requested_by_mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("target_core_user_id", sa.String(length=128), nullable=True),
        sa.Column("core_organization_id", sa.String(length=128), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requires_2fa", sa.Boolean(), nullable=False),
        sa.Column("two_factor_challenge_id", sa.BigInteger(), nullable=True),
        sa.Column("core_request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_mobile_user_id"], ["mobile_users.id"]),
        sa.ForeignKeyConstraint(["two_factor_challenge_id"], ["two_factor_challenges.id"]),
    )
    op.create_index("ix_admin_action_requests_requested_by_mobile_user_id", "admin_action_requests", ["requested_by_mobile_user_id"])
    op.create_index("ix_admin_action_requests_target_core_user_id", "admin_action_requests", ["target_core_user_id"])
    op.create_index("ix_admin_action_requests_core_organization_id", "admin_action_requests", ["core_organization_id"])
    op.create_index("ix_admin_action_requests_action_type", "admin_action_requests", ["action_type"])
    op.create_index("ix_admin_action_requests_status", "admin_action_requests", ["status"])
    op.create_index("ix_admin_action_requests_created_at", "admin_action_requests", ["created_at"])

    op.create_table(
        "admin_action_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("admin_action_request_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_mobile_user_id", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["admin_action_request_id"], ["admin_action_requests.id"]),
        sa.ForeignKeyConstraint(["actor_mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_admin_action_events_admin_action_request_id", "admin_action_events", ["admin_action_request_id"])
    op.create_index("ix_admin_action_events_event_type", "admin_action_events", ["event_type"])
    op.create_index("ix_admin_action_events_actor_mobile_user_id", "admin_action_events", ["actor_mobile_user_id"])
    op.create_index("ix_admin_action_events_created_at", "admin_action_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("admin_action_events")
    op.drop_table("admin_action_requests")
    op.drop_table("access_delegation_requests")
