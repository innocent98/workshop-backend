from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Review(Base):
    """
    Review model for customer ratings and feedback.

    Customers can review artisans after job completion.
    Artisans can respond to reviews.
    """

    __tablename__ = "reviews"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Foreign Keys
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artisan_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Review Details
    rating = Column(Float, nullable=False)  # 1.0 to 5.0 stars
    review_text = Column(Text, nullable=True)
    is_anonymous = Column(Boolean, nullable=False, default=False)

    # Moderation. ``is_flagged`` hides the review from every public listing and from the artisan's
    # rating aggregates. flag_source: auto (word filter at creation) | admin.
    is_flagged = Column(Boolean, nullable=False, default=False, index=True)
    flag_source = Column(String(16), nullable=True)
    flag_reason = Column(Text, nullable=True)
    flagged_at = Column(DateTime(timezone=True), nullable=True)
    # Reports from users that no admin has looked at yet (reset to 0 by an admin decision).
    open_report_count = Column(Integer, nullable=False, default=0, server_default="0")

    # Artisan Response
    artisan_response = Column(Text, nullable=True)
    artisan_responded_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("rating >= 1.0 AND rating <= 5.0", name="check_rating_range"),
    )

    # Relationships
    booking = relationship("Booking", back_populates="review")
    customer = relationship("User", foreign_keys=[customer_id], backref="customer_reviews")
    artisan = relationship("User", foreign_keys=[artisan_id], backref="artisan_reviews")

    def __repr__(self):
        return f"<Review booking_id={self.booking_id} rating={self.rating}>"


class ReviewReport(Base):
    """A user's report of a review. One per (review, reporter), ever: UNIQUE makes a repeat or
    a double-tap a no-op conflict instead of a second count. ``resolved_at`` is set when an
    admin acts on the review (flag, unflag or dismiss)."""

    __tablename__ = "review_reports"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(
        Integer, ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reporter_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason = Column(String(16), nullable=False)  # abusive | spam | fake | other
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("review_id", "reporter_id", name="uq_review_report_once"),)

    review = relationship("Review", backref="reports")
    reporter = relationship("User", foreign_keys=[reporter_id])
