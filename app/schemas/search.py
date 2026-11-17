"""
Search-related schemas for artisan and service discovery
"""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class LocationSearch(BaseModel):
    """Location-based search parameters"""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude coordinate")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude coordinate")
    radius_km: float = Field(
        default=10.0, ge=0.1, le=100, description="Search radius in kilometers"
    )

    @field_validator("latitude", "longitude")
    @classmethod
    def validate_coordinates(cls, v, info):
        """Validate coordinate values"""
        field_name = info.field_name
        if field_name == "latitude" and (v < -90 or v > 90):
            raise ValueError("Latitude must be between -90 and 90")
        if field_name == "longitude" and (v < -180 or v > 180):
            raise ValueError("Longitude must be between -180 and 180")
        return v


class ArtisanSearchFilters(BaseModel):
    """Filters for artisan search"""

    category_id: Optional[int] = Field(None, description="Filter by service category")
    service_ids: Optional[List[int]] = Field(None, description="Filter by specific services")
    min_hourly_rate: Optional[Decimal] = Field(None, ge=0, description="Minimum hourly rate")
    max_hourly_rate: Optional[Decimal] = Field(None, ge=0, description="Maximum hourly rate")
    min_rating: Optional[float] = Field(None, ge=0, le=5, description="Minimum average rating")
    verified_only: bool = Field(False, description="Show only verified artisans")
    availability_status: Optional[str] = Field(None, description="Filter by availability status")
    min_years_experience: Optional[int] = Field(
        None, ge=0, description="Minimum years of experience"
    )


class SearchSortOptions(BaseModel):
    """Sorting options for search results"""

    sort_by: str = Field(
        default="distance",
        description="Field to sort by: distance, rating, price, experience, jobs_completed",
    )
    sort_order: str = Field(default="asc", description="Sort order: asc or desc")

    @field_validator("sort_by")
    @classmethod
    def validate_sort_by(cls, v):
        """Validate sort_by field"""
        allowed_values = [
            "distance",
            "rating",
            "price",
            "experience",
            "jobs_completed",
            "response_time",
        ]
        if v not in allowed_values:
            raise ValueError(f"sort_by must be one of: {', '.join(allowed_values)}")
        return v

    @field_validator("sort_order")
    @classmethod
    def validate_sort_order(cls, v):
        """Validate sort_order field"""
        if v not in ["asc", "desc"]:
            raise ValueError("sort_order must be 'asc' or 'desc'")
        return v


class ArtisanSearchResult(BaseModel):
    """Artisan search result with distance"""

    # User basic info
    id: str
    full_name: str
    profile_picture: Optional[str] = None

    # Artisan profile info
    location_address: Optional[str] = None
    service_radius_km: float
    hourly_rate_min: Optional[Decimal] = None
    hourly_rate_max: Optional[Decimal] = None
    years_of_experience: Optional[int] = None
    specialization: Optional[str] = None
    is_verified: bool
    availability_status: str

    # Statistics
    average_rating: float
    total_ratings: int
    total_jobs_completed: int
    response_time_avg_minutes: Optional[int] = None
    acceptance_rate: float

    # Distance from search location
    distance_km: float = Field(..., description="Distance from search location in kilometers")

    # Services offered
    services: List[str] = Field(default_factory=list, description="List of service names")
    category_name: Optional[str] = Field(None, description="Primary selected service category name")

    # Recent portfolio sample
    portfolio_sample: Optional[str] = Field(None, description="URL of a recent portfolio image")

    class Config:
        from_attributes = True


class ArtisanSearchResponse(BaseModel):
    """Search response with pagination and metadata"""

    results: List[ArtisanSearchResult]
    total: int
    page: int
    page_size: int
    total_pages: int
    search_location: dict = Field(..., description="Search location coordinates")
    filters_applied: dict = Field(default_factory=dict, description="Filters used in search")


class ServiceAvailability(BaseModel):
    """Service availability in a location"""

    service_id: int
    service_name: str
    category_id: int
    category_name: str
    artisans_available: int = Field(..., description="Number of available artisans")
    average_hourly_rate: Optional[Decimal] = None
    average_rating: Optional[float] = None
    closest_artisan_distance_km: Optional[float] = None


class NearbyArtisanSummary(BaseModel):
    """Summary of nearby artisans"""

    total_artisans: int
    total_verified: int
    total_available: int
    services_offered: int
    average_rating: float
    distance_range_km: dict = Field(..., description="Min and max distance of artisans found")
