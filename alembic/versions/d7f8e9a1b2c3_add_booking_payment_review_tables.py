"""add booking payment review tables

Revision ID: d7f8e9a1b2c3
Revises: cbce66d28c64
Create Date: 2026-02-05 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import geoalchemy2


# revision identifiers, used by Alembic.
revision = 'd7f8e9a1b2c3'
down_revision = 'cbce66d28c64'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create bookings table
    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_reference', sa.String(length=20), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('artisan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('service_id', sa.Integer(), nullable=False),
        sa.Column('job_description', sa.Text(), nullable=True),
        sa.Column('job_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('job_location', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, from_text='ST_GeogFromText', name='geography'), nullable=False),
        sa.Column('job_address', sa.String(length=500), nullable=False),
        sa.Column('budget_min', sa.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('budget_max', sa.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('agreed_amount', sa.DECIMAL(precision=10, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completion_notes', sa.Text(), nullable=True),
        sa.Column('completion_images', sa.Text(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('budget_max >= budget_min', name='check_budget_range'),
        sa.CheckConstraint('agreed_amount IS NULL OR (agreed_amount >= budget_min AND agreed_amount <= budget_max)', name='check_agreed_amount_in_range'),
        sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['artisan_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['service_id'], ['services.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bookings_id'), 'bookings', ['id'], unique=False)
    op.create_index(op.f('ix_bookings_booking_reference'), 'bookings', ['booking_reference'], unique=True)
    op.create_index(op.f('ix_bookings_customer_id'), 'bookings', ['customer_id'], unique=False)
    op.create_index(op.f('ix_bookings_artisan_id'), 'bookings', ['artisan_id'], unique=False)
    op.create_index(op.f('ix_bookings_service_id'), 'bookings', ['service_id'], unique=False)
    op.create_index(op.f('ix_bookings_status'), 'bookings', ['status'], unique=False)

    # Create payments table
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('payment_reference', sa.String(length=20), nullable=False),
        sa.Column('paystack_reference', sa.String(length=255), nullable=True),
        sa.Column('paystack_access_code', sa.String(length=255), nullable=True),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('authorization_url', sa.String(length=500), nullable=True),
        sa.Column('amount', sa.DECIMAL(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='NGN'),
        sa.Column('payment_method', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('paystack_response', sa.Text(), nullable=True),
        sa.Column('customer_email', sa.String(length=255), nullable=False),
        sa.Column('customer_name', sa.String(length=255), nullable=False),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('payout_reference', sa.String(length=255), nullable=True),
        sa.Column('payout_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payments_id'), 'payments', ['id'], unique=False)
    op.create_index(op.f('ix_payments_payment_reference'), 'payments', ['payment_reference'], unique=True)
    op.create_index(op.f('ix_payments_paystack_reference'), 'payments', ['paystack_reference'], unique=True)
    op.create_index(op.f('ix_payments_payout_reference'), 'payments', ['payout_reference'], unique=True)
    op.create_index(op.f('ix_payments_booking_id'), 'payments', ['booking_id'], unique=True)
    op.create_index(op.f('ix_payments_status'), 'payments', ['status'], unique=False)

    # Create reviews table
    op.create_table(
        'reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('artisan_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('rating', sa.Float(), nullable=False),
        sa.Column('review_text', sa.Text(), nullable=True),
        sa.Column('is_anonymous', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_flagged', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('artisan_response', sa.Text(), nullable=True),
        sa.Column('artisan_responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('rating >= 1.0 AND rating <= 5.0', name='check_rating_range'),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['artisan_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reviews_id'), 'reviews', ['id'], unique=False)
    op.create_index(op.f('ix_reviews_booking_id'), 'reviews', ['booking_id'], unique=True)
    op.create_index(op.f('ix_reviews_customer_id'), 'reviews', ['customer_id'], unique=False)
    op.create_index(op.f('ix_reviews_artisan_id'), 'reviews', ['artisan_id'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index(op.f('ix_reviews_artisan_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_customer_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_booking_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_id'), table_name='reviews')
    op.drop_table('reviews')

    op.drop_index(op.f('ix_payments_status'), table_name='payments')
    op.drop_index(op.f('ix_payments_booking_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_payout_reference'), table_name='payments')
    op.drop_index(op.f('ix_payments_paystack_reference'), table_name='payments')
    op.drop_index(op.f('ix_payments_payment_reference'), table_name='payments')
    op.drop_index(op.f('ix_payments_id'), table_name='payments')
    op.drop_table('payments')

    op.drop_index(op.f('ix_bookings_status'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_service_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_artisan_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_customer_id'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_booking_reference'), table_name='bookings')
    op.drop_index(op.f('ix_bookings_id'), table_name='bookings')
    op.drop_table('bookings')
