from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator, ConfigDict
from uuid import UUID


class CreateBookingRequest(BaseModel):
    """Request schema for creating a new booking"""
    artisan_id: UUID
    service_id: int
    job_description: Optional[str] = None
    job_date: datetime
    job_address: str = Field(..., min_length=5, max_length=500)
    job_latitude: float = Field(..., ge=-90, le=90)
    job_longitude: float = Field(..., ge=-180, le=180)
    budget_min: Decimal = Field(..., ge=0, decimal_places=2)
    budget_max: Decimal = Field(..., ge=0, decimal_places=2)

    @field_validator('budget_max')
    @classmethod
    def validate_budget(cls, v, info):
        budget_min = info.data.get('budget_min', 0)
        if v < budget_min:
            raise ValueError('budget_max must be greater than or equal to budget_min')
        return v

    @field_validator('job_date')
    @classmethod
    def validate_job_date(cls, v):
        # Compare with a "now" value that matches the incoming datetime's timezone
        # to avoid offset-aware vs offset-naive comparison errors.
        now = datetime.now(v.tzinfo) if v.tzinfo else datetime.now()
        if v < now:
            raise ValueError('job_date cannot be in the past')
        return v

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
            "service_id": 1,
            "job_description": "Need plumbing repair in kitchen",
            "job_date": "2025-02-15T10:00:00Z",
            "job_address": "123 Main Street, Lagos, Nigeria",
            "job_latitude": 6.5244,
            "job_longitude": 3.3792,
            "budget_min": 5000.00,
            "budget_max": 10000.00
        }
    })


class AcceptBookingRequest(BaseModel):
    """Request schema for artisan accepting a booking"""
    agreed_amount: Decimal = Field(..., ge=0, decimal_places=2)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "agreed_amount": 7500.00
        }
    })


class RejectBookingRequest(BaseModel):
    """Request schema for artisan rejecting a booking"""
    rejection_reason: str = Field(..., min_length=10, max_length=500)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "rejection_reason": "I am not available on the requested date"
        }
    })


class CancelBookingRequest(BaseModel):
    """Request schema for customer cancelling a booking"""
    cancellation_reason: str = Field(..., min_length=10, max_length=500)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "cancellation_reason": "Changed my mind about the service"
        }
    })


class CompleteBookingRequest(BaseModel):
    """Request schema for artisan completing a booking"""
    completion_notes: Optional[str] = Field(None, max_length=1000)
    completion_images: Optional[List[str]] = Field(None, max_items=10)

    @field_validator('completion_images')
    @classmethod
    def validate_images(cls, v):
        if v:
            for url in v:
                if not url.startswith('http://') and not url.startswith('https://'):
                    raise ValueError('All image URLs must be valid HTTP/HTTPS URLs')
        return v

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "completion_notes": "Job completed successfully. Fixed the leak and replaced pipes.",
            "completion_images": [
                "https://res.cloudinary.com/workchop/image/upload/v1234/completion1.jpg",
                "https://res.cloudinary.com/workchop/image/upload/v1234/completion2.jpg"
            ]
        }
    })


class NegotiateBookingRequest(BaseModel):
    """Request schema for starting/countering booking negotiation"""
    negotiated_amount: Decimal = Field(..., gt=0, decimal_places=2)
    negotiation_condition: str = Field(..., min_length=5, max_length=500)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "negotiated_amount": 10000.00,
            "negotiation_condition": "Distance and material transport cost are higher."
        }
    })


class NegotiateResponseRequest(BaseModel):
    """Request schema for client negotiation response"""
    action: str = Field(..., pattern="^(agree|counter|decline)$")
    negotiated_amount: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    negotiation_condition: Optional[str] = Field(None, min_length=5, max_length=500)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        return v.lower()

    @field_validator("negotiation_condition")
    @classmethod
    def trim_condition(cls, v):
        return v.strip() if v else v

    @field_validator("negotiated_amount")
    @classmethod
    def validate_counter_amount(cls, v):
        return v

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "action": "counter",
            "negotiated_amount": 9000.00,
            "negotiation_condition": "Let's meet halfway due to budget limits."
        }
    })


class DisputeCompletionRequest(BaseModel):
    """Request schema for customer disputing completion"""
    dispute_reason: str = Field(..., min_length=10, max_length=500)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "dispute_reason": "Job was marked complete but issue is not fixed yet."
        }
    })


class BookingResponse(BaseModel):
    """Response schema for booking details"""
    id: int
    booking_reference: str
    customer_id: UUID
    artisan_id: UUID
    service_id: int
    customer_name: Optional[str] = None
    customer_profile_picture_url: Optional[str] = None
    customer_phone_number: Optional[str] = None
    artisan_name: Optional[str] = None
    artisan_profile_picture_url: Optional[str] = None
    artisan_phone_number: Optional[str] = None
    service_name: Optional[str] = None
    service_image: Optional[str] = None
    job_description: Optional[str]
    job_date: datetime
    job_address: str
    job_latitude: float
    job_longitude: float
    budget_min: Decimal
    budget_max: Decimal
    agreed_amount: Optional[Decimal]
    status: str
    accepted_at: Optional[datetime]
    paid_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    completion_notes: Optional[str]
    completion_images: Optional[List[str]]
    completion_marked_by_artisan_at: Optional[datetime]
    completion_confirmed_by_client_at: Optional[datetime]
    completion_confirmation_deadline_at: Optional[datetime]
    completion_disputed_at: Optional[datetime]
    completion_dispute_reason: Optional[str]
    negotiated_amount: Optional[Decimal]
    negotiation_condition: Optional[str]
    negotiation_status: str
    negotiation_last_offer_by: Optional[str]
    artisan_negotiation_rounds_used: int
    client_negotiation_rounds_used: int
    negotiation_started_at: Optional[datetime]
    negotiation_updated_at: Optional[datetime]
    negotiation_agreed_at: Optional[datetime]
    negotiation_declined_at: Optional[datetime]
    negotiated_override: bool
    cancellation_reason: Optional[str]
    rejection_reason: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookingListResponse(BaseModel):
    """Response schema for list of bookings"""
    bookings: List[BookingResponse]
    total: int
    page: int
    page_size: int


class BookingStatsResponse(BaseModel):
    """Response schema for booking statistics"""
    total_bookings: int
    pending_bookings: int
    accepted_bookings: int
    paid_bookings: int
    in_progress_bookings: int
    completed_bookings: int
    cancelled_bookings: int
    rejected_bookings: int
    disputed_bookings: int
