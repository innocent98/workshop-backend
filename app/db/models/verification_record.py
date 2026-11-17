from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base


class ArtisanVerificationRecord(Base):
    """
    One row per verification attempt (per ``POST .../verification/start``). Doubles as the
    attempt counter (rows created in the rolling window) and the audit trail. Holds no raw
    NIN, names, DOB or images: only pass/fail flags and, if Dojah returns it, the last 4 NIN digits.
    """

    __tablename__ = "artisan_verification_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String(16), nullable=False, default="dojah", server_default="dojah")
    provider_reference = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(12), nullable=False, default="pending", server_default="pending")
    id_verified = Column(Boolean, nullable=True)
    selfie_passed = Column(Boolean, nullable=True)
    nin_last4 = Column(String(4), nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
