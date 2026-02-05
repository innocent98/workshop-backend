from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from uuid import UUID


class CreateReviewRequest(BaseModel):
    """Request schema for creating a review"""
    booking_id: int = Field(..., gt=0)
    rating: float = Field(..., ge=1.0, le=5.0)
    review_text: Optional[str] = Field(None, max_length=1000)
    is_anonymous: bool = False

    @field_validator('rating')
    @classmethod
    def validate_rating(cls, v):
        # Ensure rating is in 0.5 increments
        if (v * 2) % 1 != 0:
            raise ValueError('Rating must be in 0.5 increments (e.g., 3.5, 4.0)')
        return v

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "booking_id": 1,
            "rating": 4.5,
            "review_text": "Excellent service! The plumber was professional and fixed the issue quickly.",
            "is_anonymous": False
        }
    })


class RespondToReviewRequest(BaseModel):
    """Request schema for artisan responding to a review"""
    artisan_response: str = Field(..., min_length=10, max_length=500)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "artisan_response": "Thank you for the kind words! It was a pleasure working with you."
        }
    })


class ReviewResponse(BaseModel):
    """Response schema for review details"""
    id: int
    booking_id: int
    customer_id: UUID
    artisan_id: UUID
    rating: float
    review_text: Optional[str]
    is_anonymous: bool
    is_flagged: bool
    artisan_response: Optional[str]
    artisan_responded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    # Optional customer and artisan details
    customer_name: Optional[str] = None
    artisan_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    """Response schema for list of reviews"""
    reviews: List[ReviewResponse]
    total: int
    average_rating: float
    rating_distribution: dict  # e.g., {"5": 10, "4": 5, "3": 2, "2": 0, "1": 1}


class ArtisanReviewStatsResponse(BaseModel):
    """Response schema for artisan review statistics"""
    artisan_id: UUID
    total_reviews: int
    average_rating: float
    rating_distribution: dict
    total_jobs_completed: int
