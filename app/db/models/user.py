import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Float, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class UserType(str, enum.Enum):
    """User type enumeration"""

    ARTISAN = "artisan"
    CLIENT = "client"


class User(Base):
    """
    User model for authentication and profile management.
    Supports multi-step registration and Google OAuth.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Personal Information (Step 1)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    phone_number = Column(String(20), unique=True, index=True, nullable=False)
    user_type = Column(
        SQLEnum(UserType, values_callable=lambda x: [e.value for e in x]), nullable=False
    )

    # Authentication (Step 2)
    hashed_password = Column(String(255), nullable=True)  # Nullable for Google OAuth users

    # Profile (Step 5)
    profile_picture_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    location_address = Column(String(500), nullable=True)
    location_latitude = Column(Float, nullable=True)
    location_longitude = Column(Float, nullable=True)

    # OAuth
    google_id = Column(String(255), unique=True, nullable=True, index=True)

    # Verification & Status
    is_email_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    registration_completed = Column(Boolean, default=False, nullable=False)
    # Set when the user deletes their account (soft delete + anonymisation, see
    # app/services/account_deletion.py). The row stays so bookings/payments keep their foreign keys.
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Admin is a flag, not a user type: admins keep user_type CLIENT/ARTISAN and
    # log in through the normal /auth/login. Granted only via scripts/create_admin.py.
    is_admin = Column(Boolean, default=False, nullable=False, server_default="false")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    otps = relationship("OTP", back_populates="user", cascade="all, delete-orphan")
    services = relationship("UserService", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship(
        "PasswordResetToken", back_populates="user", cascade="all, delete-orphan"
    )
    artisan_profile = relationship(
        "ArtisanProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    push_devices = relationship("PushDevice", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship(
        "UserNotification", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<User {self.email} ({self.user_type})>"
