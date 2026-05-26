"""mobile check tables

Revision ID: 003_mobile_checks
Revises: 002_mobile_security
Create Date: 2026-05-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003_mobile_checks"
down_revision: Union[str, Sequence[str], None] = "002_mobile_security"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mobile_check_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_user_id", sa.BigInteger(), nullable=False),
        sa.Column("core_user_id", sa.String(length=128), nullable=False),
        sa.Column("core_organization_id", sa.String(length=128), nullable=True),
        sa.Column("core_check_id", sa.String(length=128), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("document_name", sa.String(length=255), nullable=True),
        sa.Column("document_type", sa.String(length=64), nullable=True),
        sa.Column("created_from_device_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["mobile_user_id"], ["mobile_users.id"]),
    )
    op.create_index("ix_mobile_check_requests_mobile_user_id", "mobile_check_requests", ["mobile_user_id"])
    op.create_index("ix_mobile_check_requests_core_user_id", "mobile_check_requests", ["core_user_id"])
    op.create_index("ix_mobile_check_requests_core_organization_id", "mobile_check_requests", ["core_organization_id"])
    op.create_index("ix_mobile_check_requests_core_check_id", "mobile_check_requests", ["core_check_id"])
    op.create_index("ix_mobile_check_requests_status", "mobile_check_requests", ["status"])
    op.create_index("ix_mobile_check_requests_created_at", "mobile_check_requests", ["created_at"])

    op.create_table(
        "mobile_check_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_check_request_id", sa.BigInteger(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_provider", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=512), nullable=True),
        sa.Column("file_url", sa.Text(), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("upload_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["mobile_check_request_id"], ["mobile_check_requests.id"]),
    )
    op.create_index("ix_mobile_check_files_mobile_check_request_id", "mobile_check_files", ["mobile_check_request_id"])
    op.create_index("ix_mobile_check_files_upload_status", "mobile_check_files", ["upload_status"])
    op.create_index("ix_mobile_check_files_created_at", "mobile_check_files", ["created_at"])

    op.create_table(
        "mobile_check_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_check_request_id", sa.BigInteger(), nullable=False),
        sa.Column("core_check_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("originality_percent", sa.Float(), nullable=True),
        sa.Column("ai_probability_percent", sa.Float(), nullable=True),
        sa.Column("plagiarism_percent", sa.Float(), nullable=True),
        sa.Column("report_url", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_check_request_id"], ["mobile_check_requests.id"]),
    )
    op.create_index("ix_mobile_check_results_mobile_check_request_id", "mobile_check_results", ["mobile_check_request_id"])
    op.create_index("ix_mobile_check_results_core_check_id", "mobile_check_results", ["core_check_id"])
    op.create_index("ix_mobile_check_results_status", "mobile_check_results", ["status"])
    op.create_index("ix_mobile_check_results_created_at", "mobile_check_results", ["created_at"])

    op.create_table(
        "mobile_check_status_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("mobile_check_request_id", sa.BigInteger(), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("event_source", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["mobile_check_request_id"], ["mobile_check_requests.id"]),
    )
    op.create_index("ix_mobile_check_status_events_mobile_check_request_id", "mobile_check_status_events", ["mobile_check_request_id"])
    op.create_index("ix_mobile_check_status_events_new_status", "mobile_check_status_events", ["new_status"])
    op.create_index("ix_mobile_check_status_events_event_source", "mobile_check_status_events", ["event_source"])
    op.create_index("ix_mobile_check_status_events_created_at", "mobile_check_status_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("mobile_check_status_events")
    op.drop_table("mobile_check_results")
    op.drop_table("mobile_check_files")
    op.drop_table("mobile_check_requests")
