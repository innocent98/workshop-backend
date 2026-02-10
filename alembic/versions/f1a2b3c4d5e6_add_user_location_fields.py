"""add user location fields

Revision ID: f1a2b3c4d5e6
Revises: d7f8e9a1b2c3
Create Date: 2026-02-07 18:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a2b3c4d5e6'
down_revision = 'd7f8e9a1b2c3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('location_address', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('location_latitude', sa.Float(), nullable=True))
    op.add_column('users', sa.Column('location_longitude', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'location_longitude')
    op.drop_column('users', 'location_latitude')
    op.drop_column('users', 'location_address')
