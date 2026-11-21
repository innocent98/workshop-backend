"""review moderation (flag reason, reports) + backfill artisan response time

Revision ID: a4c8e2f6b1d9
Revises: d3f5a7c9e1b2
Create Date: 2026-11-18
"""

import sqlalchemy as sa

from alembic import op

revision = "a4c8e2f6b1d9"
down_revision = "d3f5a7c9e1b2"
branch_labels = None
depends_on = None

# Same calculation as app/services/response_time.py: average request-to-acceptance minutes over the
# artisan's last 20 accepted bookings, whole minutes, at least 1. Rejected/expired requests have no
# accepted_at so they are not counted.
BACKFILL_RESPONSE_TIME = """
UPDATE artisan_profiles AS ap
SET response_time_avg_minutes = sub.minutes
FROM (
    SELECT artisan_id,
           GREATEST(
               1,
               ROUND(AVG(GREATEST(EXTRACT(EPOCH FROM (accepted_at - created_at)), 0)) / 60.0)
           )::int AS minutes
    FROM (
        SELECT artisan_id, accepted_at, created_at,
               ROW_NUMBER() OVER (
                   PARTITION BY artisan_id ORDER BY accepted_at DESC, id DESC
               ) AS rn
        FROM bookings
        WHERE accepted_at IS NOT NULL
    ) ranked
    WHERE rn <= 20
    GROUP BY artisan_id
) AS sub
WHERE ap.user_id = sub.artisan_id
"""


def upgrade() -> None:
    op.add_column("reviews", sa.Column("flag_source", sa.String(length=16), nullable=True))
    op.add_column("reviews", sa.Column("flag_reason", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "reviews",
        sa.Column("open_report_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "review_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id", "reporter_id", name="uq_review_report_once"),
    )
    op.create_index("ix_review_reports_id", "review_reports", ["id"])
    op.create_index("ix_review_reports_review_id", "review_reports", ["review_id"])
    op.create_index("ix_review_reports_reporter_id", "review_reports", ["reporter_id"])
    # The moderation queue filters on these
    op.create_index("ix_reviews_is_flagged", "reviews", ["is_flagged"])

    op.execute(BACKFILL_RESPONSE_TIME)


def downgrade() -> None:
    # The backfilled response_time_avg_minutes values are left in place: the column pre-dates this
    # migration and the figures are true.
    op.drop_index("ix_reviews_is_flagged", table_name="reviews")
    op.drop_index("ix_review_reports_reporter_id", table_name="review_reports")
    op.drop_index("ix_review_reports_review_id", table_name="review_reports")
    op.drop_index("ix_review_reports_id", table_name="review_reports")
    op.drop_table("review_reports")
    op.drop_column("reviews", "open_report_count")
    op.drop_column("reviews", "flagged_at")
    op.drop_column("reviews", "flag_reason")
    op.drop_column("reviews", "flag_source")
