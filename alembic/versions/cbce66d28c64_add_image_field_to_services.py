"""add_image_field_to_services

Revision ID: cbce66d28c64
Revises: a619a39d94ad
Create Date: 2026-01-30 14:43:22.347874

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cbce66d28c64'
down_revision = 'a619a39d94ad'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add image column to services table
    op.add_column('services', sa.Column('image', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # Remove image column from services table
    op.drop_column('services', 'image')
