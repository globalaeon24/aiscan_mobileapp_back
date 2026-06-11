"""linked device user agent fields

Revision ID: 007_linked_ua_fields
Revises: 006_linked_device_sessions
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007_linked_ua_fields"
down_revision: Union[str, Sequence[str], None] = "006_linked_device_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("linked_device_sessions", sa.Column("browser_version", sa.String(length=64), nullable=True))
    op.add_column("linked_device_sessions", sa.Column("os_version", sa.String(length=128), nullable=True))
    op.add_column("linked_device_sessions", sa.Column("device_type", sa.String(length=64), nullable=True))
    op.add_column("linked_device_sessions", sa.Column("user_agent", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("linked_device_sessions", "user_agent")
    op.drop_column("linked_device_sessions", "device_type")
    op.drop_column("linked_device_sessions", "os_version")
    op.drop_column("linked_device_sessions", "browser_version")
