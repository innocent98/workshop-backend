"""add payment commission fields

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-13 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("platform_fee", sa.DECIMAL(10, 2), nullable=True),
    )
    op.add_column(
        "payments",
        sa.Column("artisan_amount", sa.DECIMAL(10, 2), nullable=True),
    )

    op.execute(
        """
        UPDATE payments
        SET
          platform_fee = ROUND(amount * 0.10, 2),
          artisan_amount = amount - ROUND(amount * 0.10, 2)
        WHERE platform_fee IS NULL OR artisan_amount IS NULL
        """
    )

    op.alter_column("payments", "platform_fee", nullable=False)
    op.alter_column("payments", "artisan_amount", nullable=False)


def downgrade() -> None:
    op.drop_column("payments", "artisan_amount")
    op.drop_column("payments", "platform_fee")
