"""add service categories, artisan profiles, and portfolio

Revision ID: a619a39d94ad
Revises: b5aaeec89a89
Create Date: 2026-01-21 23:18:23.291611

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


# revision identifiers, used by Alembic.
revision = 'a619a39d94ad'
down_revision = 'b5aaeec89a89'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create service_categories table
    op.create_table(
        'service_categories',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_service_categories_id'), 'service_categories', ['id'], unique=False)
    op.create_index(op.f('ix_service_categories_name'), 'service_categories', ['name'], unique=True)

    # Add category_id to services table
    op.add_column('services', sa.Column('category_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_services_category_id'), 'services', ['category_id'], unique=False)
    op.create_foreign_key('fk_services_category_id', 'services', 'service_categories', ['category_id'], ['id'], ondelete='CASCADE')

    # Create artisan_profiles table
    op.create_table(
        'artisan_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, from_text='ST_GeogFromText', name='geography'), nullable=True),
        sa.Column('location_address', sa.String(length=500), nullable=True),
        sa.Column('service_radius_km', sa.Float(), nullable=False, server_default='10.0'),
        sa.Column('hourly_rate_min', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('hourly_rate_max', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('years_of_experience', sa.Integer(), nullable=True),
        sa.Column('specialization', sa.String(length=200), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('verification_documents', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verified_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('availability_status', sa.String(length=20), nullable=False, server_default='available'),
        sa.Column('average_rating', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('total_ratings', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_jobs_completed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('response_time_avg_minutes', sa.Integer(), nullable=True),
        sa.Column('acceptance_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_artisan_profiles_id'), 'artisan_profiles', ['id'], unique=False)
    op.create_index(op.f('ix_artisan_profiles_user_id'), 'artisan_profiles', ['user_id'], unique=True)

    # Create portfolio table
    op.create_table(
        'portfolio',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('artisan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('project_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['artisan_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portfolio_id'), 'portfolio', ['id'], unique=False)
    op.create_index(op.f('ix_portfolio_artisan_id'), 'portfolio', ['artisan_id'], unique=False)


def downgrade() -> None:
    # Drop portfolio table
    op.drop_index(op.f('ix_portfolio_artisan_id'), table_name='portfolio')
    op.drop_index(op.f('ix_portfolio_id'), table_name='portfolio')
    op.drop_table('portfolio')

    # Drop artisan_profiles table
    op.drop_index(op.f('ix_artisan_profiles_user_id'), table_name='artisan_profiles')
    op.drop_index(op.f('ix_artisan_profiles_id'), table_name='artisan_profiles')
    op.drop_table('artisan_profiles')

    # Remove category_id from services
    op.drop_constraint('fk_services_category_id', 'services', type_='foreignkey')
    op.drop_index(op.f('ix_services_category_id'), table_name='services')
    op.drop_column('services', 'category_id')

    # Drop service_categories table
    op.drop_index(op.f('ix_service_categories_name'), table_name='service_categories')
    op.drop_index(op.f('ix_service_categories_id'), table_name='service_categories')
    op.drop_table('service_categories')
