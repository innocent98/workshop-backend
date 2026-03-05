"""add booking progress logs

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-05 00:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "booking_progress_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("artisan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["artisan_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_booking_progress_logs_id"), "booking_progress_logs", ["id"], unique=False)
    op.create_index(op.f("ix_booking_progress_logs_booking_id"), "booking_progress_logs", ["booking_id"], unique=False)
    op.create_index(op.f("ix_booking_progress_logs_artisan_id"), "booking_progress_logs", ["artisan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_progress_logs_artisan_id"), table_name="booking_progress_logs")
    op.drop_index(op.f("ix_booking_progress_logs_booking_id"), table_name="booking_progress_logs")
    op.drop_index(op.f("ix_booking_progress_logs_id"), table_name="booking_progress_logs")
    op.drop_table("booking_progress_logs")
