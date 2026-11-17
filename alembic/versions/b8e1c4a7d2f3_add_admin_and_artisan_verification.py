"""add admin flag, artisan verification fields, dispute resolutions, admin audit log

Revision ID: b8e1c4a7d2f3
Revises: c8a1d2e3f4b5
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b8e1c4a7d2f3"
down_revision = "c8a1d2e3f4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.add_column(
        "artisan_profiles",
        sa.Column(
            "verification_status", sa.String(16), nullable=False, server_default="unverified"
        ),
    )
    op.add_column(
        "artisan_profiles", sa.Column("verification_method", sa.String(16), nullable=True)
    )
    op.add_column(
        "artisan_profiles", sa.Column("verification_reference", sa.String(100), nullable=True)
    )
    op.add_column(
        "artisan_profiles", sa.Column("verification_failure_reason", sa.Text(), nullable=True)
    )
    op.add_column("artisan_profiles", sa.Column("nin_last4", sa.String(4), nullable=True))
    op.create_index(
        "ix_artisan_profiles_verification_status", "artisan_profiles", ["verification_status"]
    )
    # Grandfather: artisans already verified (by the old temporary auto-verify) stay verified.
    op.execute(
        "UPDATE artisan_profiles SET verification_status = 'verified', "
        "verification_method = 'legacy' WHERE is_verified = TRUE"
    )

    op.create_table(
        "artisan_verification_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(16), nullable=False, server_default="dojah"),
        sa.Column("provider_reference", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("id_verified", sa.Boolean(), nullable=True),
        sa.Column("selfie_passed", sa.Boolean(), nullable=True),
        sa.Column("nin_last4", sa.String(4), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_artisan_verification_records_id", "artisan_verification_records", ["id"])
    op.create_index(
        "ix_artisan_verification_records_user_id", "artisan_verification_records", ["user_id"]
    )
    op.create_index(
        "ix_artisan_verification_records_provider_reference",
        "artisan_verification_records",
        ["provider_reference"],
        unique=True,
    )

    op.create_table(
        "dispute_resolutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "booking_id",
            sa.Integer(),
            sa.ForeignKey("bookings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("resolution", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispute_reason", sa.Text(), nullable=True),
        sa.Column("refund_reference", sa.String(255), nullable=True),
        sa.Column("refund_status", sa.String(16), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_dispute_resolutions_id", "dispute_resolutions", ["id"])
    op.create_index(
        "ix_dispute_resolutions_booking_id", "dispute_resolutions", ["booking_id"], unique=True
    )
    op.create_index("ix_dispute_resolutions_admin_id", "dispute_resolutions", ["admin_id"])

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_admin_audit_logs_id", "admin_audit_logs", ["id"])
    op.create_index("ix_admin_audit_logs_admin_id", "admin_audit_logs", ["admin_id"])
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("artisan_verification_records")
    op.drop_table("dispute_resolutions")
    op.drop_index("ix_artisan_profiles_verification_status", table_name="artisan_profiles")
    for col in (
        "nin_last4",
        "verification_failure_reason",
        "verification_reference",
        "verification_method",
        "verification_status",
    ):
        op.drop_column("artisan_profiles", col)
    op.drop_column("users", "is_admin")
