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
    # Enable PostGIS extension
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis;')
    # Enable PostGIS topology support (optional but useful)
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis_topology;')
    # Enable PostGIS raster support (optional)
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis_raster;')


def downgrade() -> None:
    # Disable extensions in reverse order
    op.execute('DROP EXTENSION IF EXISTS postgis_raster;')
    op.execute('DROP EXTENSION IF EXISTS postgis_topology;')
    op.execute('DROP EXTENSION IF EXISTS postgis;')
