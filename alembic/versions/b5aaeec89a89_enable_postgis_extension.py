"""enable_postgis_extension

Revision ID: b5aaeec89a89
Revises: 001_initial
Create Date: 2026-01-20 00:44:30.808214

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5aaeec89a89'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable core PostGIS extension (sufficient for point geometry and distance calculations)
    # Topology and raster extensions removed - not needed for basic spatial operations
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis;')


def downgrade() -> None:
    # Disable extension
    op.execute('DROP EXTENSION IF EXISTS postgis;')
