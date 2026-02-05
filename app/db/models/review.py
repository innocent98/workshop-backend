from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Boolean, Float, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

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
        index=True
    )
    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    artisan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Review Details
    rating = Column(Float, nullable=False)  # 1.0 to 5.0 stars
    review_text = Column(Text, nullable=True)
    is_anonymous = Column(Boolean, nullable=False, default=False)

    # Moderation
    is_flagged = Column(Boolean, nullable=False, default=False)

    # Artisan Response
    artisan_response = Column(Text, nullable=True)
    artisan_responded_at = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Constraints
    __table_args__ = (
        CheckConstraint('rating >= 1.0 AND rating <= 5.0', name='check_rating_range'),
    )

    # Relationships
    booking = relationship("Booking", back_populates="review")
    customer = relationship("User", foreign_keys=[customer_id], backref="customer_reviews")
    artisan = relationship("User", foreign_keys=[artisan_id], backref="artisan_reviews")

    def __repr__(self):
        return f"<Review booking_id={self.booking_id} rating={self.rating}>"
