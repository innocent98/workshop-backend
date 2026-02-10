"""add completion confirmation fields to bookings

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e6
Create Date: 2026-02-10 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9b8c7d6e5f4'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('completion_marked_by_artisan_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('completion_confirmed_by_client_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('completion_confirmation_deadline_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('completion_disputed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bookings', sa.Column('completion_dispute_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('bookings', 'completion_dispute_reason')
    op.drop_column('bookings', 'completion_disputed_at')
    op.drop_column('bookings', 'completion_confirmation_deadline_at')
    op.drop_column('bookings', 'completion_confirmed_by_client_at')
    op.drop_column('bookings', 'completion_marked_by_artisan_at')
