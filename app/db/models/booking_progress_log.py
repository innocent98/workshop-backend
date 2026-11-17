from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class BookingProgressLog(Base):
    """Progress updates posted by artisan during an active booking."""

    __tablename__ = "booking_progress_logs"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artisan_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description = Column(Text, nullable=False)
    image_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    booking = relationship("Booking", back_populates="progress_logs")

    def __repr__(self):
        return f"<BookingProgressLog booking={self.booking_id} artisan={self.artisan_id}>"
