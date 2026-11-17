"""add withdrawals ledger and payments.withdrawal_id

Revision ID: c8a1d2e3f4b5
Revises: f7b8c9d0e1f2
Create Date: 2026-11-17 13:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c8a1d2e3f4b5"
down_revision = "f7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "withdrawals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artisan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.DECIMAL(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        # processing | success | failed | reversed (VARCHAR, not a PG enum: easy to extend)
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("transfer_code", sa.String(100), nullable=True),
        sa.Column("recipient_code", sa.String(100), nullable=True),
        sa.Column("bank_code", sa.String(20), nullable=False),
        sa.Column("account_number_last4", sa.String(4), nullable=False),
        sa.Column("account_name", sa.String(255), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "artisan_id", "idempotency_key", name="uq_withdrawals_artisan_idem_key"
        ),
    )
    op.create_index("ix_withdrawals_id", "withdrawals", ["id"])
    op.create_index("ix_withdrawals_artisan_id", "withdrawals", ["artisan_id"])
    op.create_index("ix_withdrawals_status", "withdrawals", ["status"])
    op.create_index("ix_withdrawals_reference", "withdrawals", ["reference"], unique=True)
    op.create_index("ix_withdrawals_transfer_code", "withdrawals", ["transfer_code"])

    op.add_column("payments", sa.Column("withdrawal_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payments_withdrawal_id",
        "payments",
        "withdrawals",
        ["withdrawal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_payments_withdrawal_id", "payments", ["withdrawal_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_withdrawal_id", table_name="payments")
    op.drop_constraint("fk_payments_withdrawal_id", "payments", type_="foreignkey")
    op.drop_column("payments", "withdrawal_id")

    op.drop_index("ix_withdrawals_transfer_code", table_name="withdrawals")
    op.drop_index("ix_withdrawals_reference", table_name="withdrawals")
    op.drop_index("ix_withdrawals_status", table_name="withdrawals")
    op.drop_index("ix_withdrawals_artisan_id", table_name="withdrawals")
    op.drop_index("ix_withdrawals_id", table_name="withdrawals")
    op.drop_table("withdrawals")
