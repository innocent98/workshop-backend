"""Admin-side audit models: dispute resolutions and a generic admin audit log."""

import enum

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class DisputeResolutionType(str, enum.Enum):
    RELEASE_TO_ARTISAN = "release_to_artisan"
    REFUND_CUSTOMER = "refund_customer"


class DisputeResolution(Base):
    """
    One row per resolved dispute. ``booking_id`` is UNIQUE: that is what makes
    resolution atomic/idempotent (a second concurrent resolve violates the constraint).
    Original dispute fields are snapshotted because ``release_to_artisan`` clears
    them on the booking so the normal payout flow can proceed.
    """

    __tablename__ = "dispute_resolutions"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    resolution = Column(String(32), nullable=False)  # DisputeResolutionType value
    note = Column(Text, nullable=False)
    disputed_at = Column(DateTime(timezone=True), nullable=True)  # snapshot
    dispute_reason = Column(Text, nullable=True)  # snapshot
    refund_reference = Column(String(255), nullable=True)  # Paystack refund id, refund path only
    # Refund path only: requested (intent committed, Paystack outcome unknown) | pending |
    # processing | processed | needs-attention | failed. NULL for release_to_artisan.
    refund_status = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    booking = relationship("Booking")
    admin = relationship("User", foreign_keys=[admin_id])


class AdminAuditLog(Base):
    """Append-only record of every state-changing admin action."""

    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)  # e.g. artisan.verify
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(64), nullable=False)
    details = Column(JSONB, nullable=True)  # never PII / secrets
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
