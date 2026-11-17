"""add users.deleted_at for account deletion (soft delete + anonymisation)

Revision ID: d3f5a7c9e1b2
Revises: b8e1c4a7d2f3
Create Date: 2026-11-17
"""

import sqlalchemy as sa

from alembic import op

revision = "d3f5a7c9e1b2"
down_revision = "b8e1c4a7d2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
