"""registration agreement consents

Revision ID: 008_registration_consents
Revises: 007_linked_ua_fields
Create Date: 2026-10-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_registration_consents"
down_revision: Union[str, Sequence[str], None] = "007_linked_ua_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "registration_consents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("agreement_version", sa.String(length=64), nullable=False),
        sa.Column("agreement_url", sa.String(length=512), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("core_response_code", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_registration_consents_email",
        "registration_consents",
        ["email"],
    )
    op.create_index(
        "ix_registration_consents_accepted_at",
        "registration_consents",
        ["accepted_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_registration_consents_accepted_at",
        table_name="registration_consents",
    )
    op.drop_index(
        "ix_registration_consents_email",
        table_name="registration_consents",
    )
    op.drop_table("registration_consents")
