"""add booking negotiation fields

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-28 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("negotiated_amount", sa.DECIMAL(10, 2), nullable=True))
    op.add_column("bookings", sa.Column("negotiation_condition", sa.Text(), nullable=True))
    op.add_column(
        "bookings",
        sa.Column("negotiation_status", sa.String(length=32), nullable=False, server_default="none"),
    )
    op.add_column("bookings", sa.Column("negotiation_last_offer_by", sa.String(length=16), nullable=True))
    op.add_column(
        "bookings",
        sa.Column("artisan_negotiation_rounds_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "bookings",
        sa.Column("client_negotiation_rounds_used", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("bookings", sa.Column("negotiation_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("negotiation_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("negotiation_agreed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("bookings", sa.Column("negotiation_declined_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "bookings",
        sa.Column("negotiated_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.drop_constraint("check_agreed_amount_in_range", "bookings", type_="check")
    op.create_check_constraint(
        "check_agreed_amount_in_range",
        "bookings",
        "agreed_amount IS NULL OR "
        "(agreed_amount >= budget_min AND agreed_amount <= budget_max) OR "
        "(negotiated_override = TRUE)",
    )


def downgrade() -> None:
    op.drop_constraint("check_agreed_amount_in_range", "bookings", type_="check")
    op.create_check_constraint(
        "check_agreed_amount_in_range",
        "bookings",
        "agreed_amount IS NULL OR (agreed_amount >= budget_min AND agreed_amount <= budget_max)",
    )

    op.drop_column("bookings", "negotiated_override")
    op.drop_column("bookings", "negotiation_declined_at")
    op.drop_column("bookings", "negotiation_agreed_at")
    op.drop_column("bookings", "negotiation_updated_at")
    op.drop_column("bookings", "negotiation_started_at")
    op.drop_column("bookings", "client_negotiation_rounds_used")
    op.drop_column("bookings", "artisan_negotiation_rounds_used")
    op.drop_column("bookings", "negotiation_last_offer_by")
    op.drop_column("bookings", "negotiation_status")
    op.drop_column("bookings", "negotiation_condition")
    op.drop_column("bookings", "negotiated_amount")
