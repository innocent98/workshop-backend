import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta, timezone

from app.db.base import Base


class OTPType(str, enum.Enum):
    """OTP type enumeration"""
    PHONE_VERIFICATION = "phone_verification"
    PASSWORD_RESET = "password_reset"


class OTP(Base):
    """
    OTP model for email verification and password reset.
    OTP codes are 6 digits and expire after 10 minutes.
    """
    __tablename__ = "otps"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    otp_code = Column(String(6), nullable=False)
    otp_type = Column(SQLEnum(OTPType, values_callable=lambda x: [e.value for e in x]), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)

    # OTP expires after 10 minutes as per documentation
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationship
    user = relationship("User", back_populates="otps")

    def is_expired(self) -> bool:
        """Check if OTP has expired"""
        return datetime.now(timezone.utc) > self.expires_at

    def is_valid(self, code: str) -> bool:
        """Check if OTP is valid (not used, not expired, and matches code)"""
        return (
            not self.is_used
            and not self.is_expired()
            and self.otp_code == code
        )

    @staticmethod
    def calculate_expiry() -> datetime:
        """Calculate expiry time (10 minutes from now)"""
        return datetime.now(timezone.utc) + timedelta(minutes=10)

    def __repr__(self):
        return f"<OTP {self.user_id} - {self.otp_type}>"
