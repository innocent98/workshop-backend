"""add user notifications

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-05 11:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_notifications_id"), "user_notifications", ["id"], unique=False)
    op.create_index(op.f("ix_user_notifications_user_id"), "user_notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_notifications_event_type"), "user_notifications", ["event_type"], unique=False)
    op.create_index(op.f("ix_user_notifications_is_read"), "user_notifications", ["is_read"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_notifications_is_read"), table_name="user_notifications")
    op.drop_index(op.f("ix_user_notifications_event_type"), table_name="user_notifications")
    op.drop_index(op.f("ix_user_notifications_user_id"), table_name="user_notifications")
    op.drop_index(op.f("ix_user_notifications_id"), table_name="user_notifications")
    op.drop_table("user_notifications")
