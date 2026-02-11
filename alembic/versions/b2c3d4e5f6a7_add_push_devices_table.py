"""add push devices table

Revision ID: b2c3d4e5f6a7
Revises: a9b8c7d6e5f4
Create Date: 2026-02-11 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'pushplatform') THEN
                CREATE TYPE pushplatform AS ENUM ('android', 'ios', 'web');
            END IF;
        END $$;
        """
    )

    op.create_table(
        "push_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fcm_token", sa.String(length=1024), nullable=False),
        sa.Column(
            "platform",
            postgresql.ENUM("android", "ios", "web", name="pushplatform", create_type=False),
            nullable=False,
        ),
        sa.Column("device_id", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_push_devices_id"), "push_devices", ["id"], unique=False)
    op.create_index(op.f("ix_push_devices_user_id"), "push_devices", ["user_id"], unique=False)
    op.create_index(op.f("ix_push_devices_fcm_token"), "push_devices", ["fcm_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_push_devices_fcm_token"), table_name="push_devices")
    op.drop_index(op.f("ix_push_devices_user_id"), table_name="push_devices")
    op.drop_index(op.f("ix_push_devices_id"), table_name="push_devices")
    op.drop_table("push_devices")

    op.execute("DROP TYPE IF EXISTS pushplatform")
