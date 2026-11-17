"""
Pydantic schemas for User Profiles (Customer and Artisan).
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.db.models.artisan_profile import AvailabilityStatus


class CustomerLocationInput(BaseModel):
    """Schema for customer location input"""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    address: Optional[str] = Field(None, max_length=500, description="Human-readable address")


# Customer Profile Schemas
class CustomerProfileResponse(BaseModel):
    """Schema for customer profile response"""

    id: str  # User UUID
    full_name: str
    email: str
    phone_number: str
    profile_picture_url: Optional[str] = None
    bio: Optional[str] = None
    location_address: Optional[str] = None
    location_latitude: Optional[float] = None
    location_longitude: Optional[float] = None
    is_email_verified: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CustomerProfileUpdate(BaseModel):
    """Schema for updating customer profile"""

    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=20)
    bio: Optional[str] = Field(None, max_length=1000)
    location: Optional[CustomerLocationInput] = None
    location_address: Optional[str] = Field(None, max_length=500)


# Artisan Profile Schemas
class LocationInput(BaseModel):
    """Schema for location input"""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    address: Optional[str] = Field(None, max_length=500, description="Human-readable address")


class ArtisanProfileBase(BaseModel):
    """Base schema for Artisan Profile"""

    location_address: Optional[str] = Field(None, max_length=500)
    service_radius_km: Optional[float] = Field(10.0, ge=1, le=100)
    hourly_rate_min: Optional[Decimal] = Field(None, ge=0)
    hourly_rate_max: Optional[Decimal] = Field(None, ge=0)
    years_of_experience: Optional[int] = Field(None, ge=0, le=50)
    specialization: Optional[str] = Field(None, max_length=200)


class ArtisanProfileCreate(ArtisanProfileBase):
    """Schema for creating artisan profile"""

    pass


class ArtisanProfileUpdate(BaseModel):
    """Schema for updating artisan profile"""

    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    phone_number: Optional[str] = Field(None, min_length=10, max_length=20)
    bio: Optional[str] = Field(None, max_length=1000)
    location: Optional[LocationInput] = None
    location_address: Optional[str] = Field(None, max_length=500)
    service_radius_km: Optional[float] = Field(None, ge=1, le=100)
    hourly_rate_min: Optional[Decimal] = Field(None, ge=0)
    hourly_rate_max: Optional[Decimal] = Field(None, ge=0)
    years_of_experience: Optional[int] = Field(None, ge=0, le=50)
    specialization: Optional[str] = Field(None, max_length=200)

    @field_validator("hourly_rate_max")
    @classmethod
    def validate_rate_range(cls, v, info):
        """Ensure max rate is greater than or equal to min rate"""
        if v is not None and info.data.get("hourly_rate_min") is not None:
            if v < info.data["hourly_rate_min"]:
                raise ValueError("hourly_rate_max must be greater than or equal to hourly_rate_min")
        return v


class ArtisanAvailabilityUpdate(BaseModel):
    """Schema for updating artisan availability"""

    availability_status: AvailabilityStatus


class ArtisanStatsResponse(BaseModel):
    """Schema for artisan statistics"""

    average_rating: float
    total_ratings: int
    total_jobs_completed: int
    response_time_avg_minutes: Optional[int] = None
    acceptance_rate: float

    class Config:
        from_attributes = True


class ArtisanProfileResponse(BaseModel):
    """Schema for artisan profile response (private - for the artisan themselves)"""

    # User info
    id: str  # User UUID
    full_name: str
    email: str
    phone_number: str
    profile_picture_url: Optional[str] = None
    bio: Optional[str] = None
    user_type: str

    # Artisan profile info
    location_address: Optional[str] = None
    service_radius_km: float
    hourly_rate_min: Optional[Decimal] = None
    hourly_rate_max: Optional[Decimal] = None
    years_of_experience: Optional[int] = None
    specialization: Optional[str] = None
    is_verified: bool
    verified_at: Optional[datetime] = None
    # unverified | pending | verified | failed (additive; see /artisans/me/verification)
    verification_status: str = "unverified"
    availability_status: AvailabilityStatus

    # Statistics
    average_rating: float
    total_ratings: int
    total_jobs_completed: int
    response_time_avg_minutes: Optional[int] = None
    acceptance_rate: float

    # Timestamps
    created_at: datetime

    class Config:
        from_attributes = True


class ArtisanPublicProfileResponse(BaseModel):
    """Schema for artisan public profile (what customers see)"""

    # User info
    id: str  # User UUID
    full_name: str
    profile_picture_url: Optional[str] = None
    bio: Optional[str] = None

    # Artisan profile info (limited)
    location_address: Optional[str] = None
    service_radius_km: float
    hourly_rate_min: Optional[Decimal] = None
    hourly_rate_max: Optional[Decimal] = None
    years_of_experience: Optional[int] = None
    specialization: Optional[str] = None
    is_verified: bool
    availability_status: AvailabilityStatus

    # Public statistics
    average_rating: float
    total_ratings: int
    total_jobs_completed: int
    response_time_avg_minutes: Optional[int] = None

    class Config:
        from_attributes = True


class ArtisanSearchResult(ArtisanPublicProfileResponse):
    """Schema for artisan search results with distance"""

    distance_km: Optional[float] = Field(
        None, description="Distance from search location in kilometers"
    )

    class Config:
        from_attributes = True


class ProfilePictureResponse(BaseModel):
    """Schema for profile picture upload/update response"""

    message: str
    profile_picture_url: str


class ArtisanServiceSelectionUpdate(BaseModel):
    """Schema for replacing artisan selected services"""

    service_ids: List[int] = Field(..., min_length=1)


class ArtisanServiceSelectionResponse(BaseModel):
    """Schema for artisan selected service response"""

    id: int
    name: str
    description: Optional[str] = None
    image: Optional[str] = None

    class Config:
        from_attributes = True
