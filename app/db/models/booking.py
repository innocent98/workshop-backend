import enum

from geoalchemy2 import Geography
from sqlalchemy import DECIMAL, Boolean, CheckConstraint, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class BookingStatus(str, enum.Enum):
    """Booking status enumeration"""

    PENDING = "pending"  # Awaiting artisan response
    ACCEPTED = "accepted"  # Artisan accepted, awaiting payment
    PAID = "paid"  # Payment successful, job can start
    IN_PROGRESS = "in_progress"  # Job is being done
    COMPLETED = "completed"  # Job done, awaiting review
    CANCELLED = "cancelled"  # Cancelled before/after payment
    REJECTED = "rejected"  # Artisan rejected
    DISPUTED = "disputed"  # Dispute raised


class Booking(Base):
    """
    Booking model for managing service booking requests.

    Status Flow:
    PENDING → ACCEPTED → PAID → IN_PROGRESS → COMPLETED
       ↓         ↓
    REJECTED  CANCELLED
    """

    __tablename__ = "bookings"

    # Primary Key
    id = Column(Integer, primary_key=True, index=True)

    # Reference Number
    booking_reference = Column(String(20), unique=True, nullable=False, index=True)

    # Foreign Keys
    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artisan_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id = Column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Job Details
    job_description = Column(Text, nullable=True)
    selected_service_ids = Column(Text, nullable=True)  # JSON array of service IDs
    job_date = Column(DateTime(timezone=True), nullable=False)
    job_location = Column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    job_address = Column(String(500), nullable=False)

    # Budget and Payment
    budget_min = Column(DECIMAL(10, 2), nullable=False)
    budget_max = Column(DECIMAL(10, 2), nullable=False)
    agreed_amount = Column(DECIMAL(10, 2), nullable=True)
    negotiated_amount = Column(DECIMAL(10, 2), nullable=True)
    negotiation_condition = Column(Text, nullable=True)
    negotiation_status = Column(String(32), nullable=False, default="none", server_default="none")
    negotiation_last_offer_by = Column(String(16), nullable=True)  # client | artisan
    artisan_negotiation_rounds_used = Column(Integer, nullable=False, default=0, server_default="0")
    client_negotiation_rounds_used = Column(Integer, nullable=False, default=0, server_default="0")
    negotiation_started_at = Column(DateTime(timezone=True), nullable=True)
    negotiation_updated_at = Column(DateTime(timezone=True), nullable=True)
    negotiation_agreed_at = Column(DateTime(timezone=True), nullable=True)
    negotiation_declined_at = Column(DateTime(timezone=True), nullable=True)
    negotiated_override = Column(Boolean, nullable=False, default=False, server_default="false")

    # Status
    status = Column(
        SQLEnum(BookingStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=BookingStatus.PENDING,
        index=True,
    )

    # Status Timestamps
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    # Completion Details
    completion_notes = Column(Text, nullable=True)
    completion_images = Column(Text, nullable=True)  # JSON array of Cloudinary URLs
    completion_marked_by_artisan_at = Column(DateTime(timezone=True), nullable=True)
    completion_confirmed_by_client_at = Column(DateTime(timezone=True), nullable=True)
    completion_confirmation_deadline_at = Column(DateTime(timezone=True), nullable=True)
    completion_disputed_at = Column(DateTime(timezone=True), nullable=True)
    completion_dispute_reason = Column(Text, nullable=True)

    # Cancellation/Rejection Reasons
    cancellation_reason = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Constraints
    __table_args__ = (
        CheckConstraint("budget_max >= budget_min", name="check_budget_range"),
        CheckConstraint(
            "agreed_amount IS NULL OR "
            "(agreed_amount >= budget_min AND agreed_amount <= budget_max) OR "
            "(negotiated_override = TRUE)",
            name="check_agreed_amount_in_range",
        ),
    )

    # Relationships
    customer = relationship("User", foreign_keys=[customer_id], backref="customer_bookings")
    artisan = relationship("User", foreign_keys=[artisan_id], backref="artisan_bookings")
    service = relationship("Service", backref="bookings")
    payment = relationship(
        "Payment", back_populates="booking", uselist=False, cascade="all, delete-orphan"
    )
    review = relationship(
        "Review", back_populates="booking", uselist=False, cascade="all, delete-orphan"
    )
    progress_logs = relationship(
        "BookingProgressLog",
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="BookingProgressLog.created_at.asc()",
    )

    def __repr__(self):
        return f"<Booking {self.booking_reference} ({self.status})>"
