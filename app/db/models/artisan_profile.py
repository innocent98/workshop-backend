"""
Artisan Profile model with location and service details.
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Enum, Text, DECIMAL
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
import enum

from app.db.base import Base


class AvailabilityStatus(str, enum.Enum):
    """Artisan availability status"""
    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class ArtisanProfile(Base):
    """
    Extended profile for artisan users.
    Contains artisan-specific information like location, rates, verification, etc.
    """
    __tablename__ = "artisan_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Location (PostGIS)
    location = Column(Geography(geometry_type='POINT', srid=4326), nullable=True)
    location_address = Column(String(500), nullable=True)  # Human-readable address
    service_radius_km = Column(Float, default=10.0, nullable=False)  # How far they'll travel

    # Pricing
    hourly_rate_min = Column(DECIMAL(10, 2), nullable=True)  # Minimum hourly rate in Naira
    hourly_rate_max = Column(DECIMAL(10, 2), nullable=True)  # Maximum hourly rate in Naira

    # Experience
    years_of_experience = Column(Integer, nullable=True)
    specialization = Column(String(200), nullable=True)  # e.g., "Residential plumbing", "Commercial electrical"

    # Verification
    is_verified = Column(Boolean, default=False, nullable=False)  # Admin-approved
    verification_documents = Column(Text, nullable=True)  # JSON array of document URLs
    verified_at = Column(DateTime(timezone=True), nullable=True)
    verified_by = Column(UUID(as_uuid=True), nullable=True)  # Admin user who verified

    # Availability
    availability_status = Column(
        Enum(AvailabilityStatus, native_enum=False),
        default=AvailabilityStatus.AVAILABLE,
        nullable=False
    )

    # Statistics (updated by triggers/background jobs)
    average_rating = Column(Float, default=0.0, nullable=False)
    total_ratings = Column(Integer, default=0, nullable=False)
    total_jobs_completed = Column(Integer, default=0, nullable=False)
    response_time_avg_minutes = Column(Integer, nullable=True)  # Average time to accept jobs
    acceptance_rate = Column(Float, default=0.0, nullable=False)  # % of jobs accepted

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    user = relationship("User", back_populates="artisan_profile")
    portfolio = relationship("Portfolio", back_populates="artisan", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ArtisanProfile user_id={self.user_id} verified={self.is_verified}>"

    @property
    def has_location(self) -> bool:
        """Check if artisan has set their location"""
        return self.location is not None

    @property
    def rating_display(self) -> str:
        """Display rating as string (e.g., '4.5/5.0')"""
        return f"{self.average_rating:.1f}/5.0"
