from datetime import datetime
from decimal import Decimal
from typing import Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int


class AdminUserItem(BaseModel):
    id: str
    full_name: str
    email: str
    phone_number: str
    user_type: str
    is_active: bool
    is_admin: bool
    is_email_verified: bool
    created_at: datetime
    # Artisans only (null for clients)
    is_verified: Optional[bool] = None
    verification_status: Optional[str] = None


class AdminBookingItem(BaseModel):
    id: int
    booking_reference: str
    status: str
    customer_id: str
    customer_name: Optional[str] = None
    artisan_id: str
    artisan_name: Optional[str] = None
    agreed_amount: Optional[Decimal] = None
    budget_min: Decimal
    budget_max: Decimal
    job_date: datetime
    payment_status: Optional[str] = None
    completion_disputed_at: Optional[datetime] = None
    completion_confirmed_by_client_at: Optional[datetime] = None
    created_at: datetime


class AdminPaymentItem(BaseModel):
    id: int
    payment_reference: str
    booking_id: int
    booking_reference: Optional[str] = None
    status: str
    amount: Decimal
    platform_fee: Decimal
    artisan_amount: Decimal
    currency: str
    customer_email: str
    paid_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    refunded_at: Optional[datetime] = None
    created_at: datetime


class AdminDisputeItem(BaseModel):
    booking_id: int
    booking_reference: str
    customer_id: str
    customer_name: Optional[str] = None
    artisan_id: str
    artisan_name: Optional[str] = None
    agreed_amount: Optional[Decimal] = None
    payment_status: Optional[str] = None
    disputed_at: datetime
    dispute_reason: Optional[str] = None
    completion_notes: Optional[str] = None


class ResolveDisputeRequest(BaseModel):
    resolution: Literal["release_to_artisan", "refund_customer"]
    note: str = Field(..., min_length=3, max_length=2000)


class ResolveDisputeResponse(BaseModel):
    booking_id: int
    booking_status: str
    resolution: str
    note: str
    resolved_by: str
    resolved_at: datetime
    payment_status: Optional[str] = None
    refund_reference: Optional[str] = None
    # refund path: pending | processing | processed | needs-attention (accepted by Paystack)
    refund_status: Optional[str] = None
    already_resolved: bool = False


class ArtisanVerifyRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=1000)


class ArtisanRejectRequest(BaseModel):
    note: str = Field(..., min_length=3, max_length=1000)


class AdminArtisanVerificationResponse(BaseModel):
    user_id: str
    is_verified: bool
    verification_status: str
    verification_method: Optional[str] = None
    verified_at: Optional[datetime] = None
    verification_failure_reason: Optional[str] = None


class AdminReviewItem(BaseModel):
    id: int
    booking_id: int
    rating: float
    review_text: Optional[str] = None
    is_anonymous: bool
    customer_id: str
    customer_name: Optional[str] = None
    artisan_id: str
    artisan_name: Optional[str] = None
    is_flagged: bool
    flag_source: Optional[str] = None  # auto | admin
    flag_reason: Optional[str] = None
    flagged_at: Optional[datetime] = None
    open_report_count: int
    created_at: datetime


class AdminReviewReportItem(BaseModel):
    id: int
    reporter_id: str
    reporter_name: Optional[str] = None
    reason: str
    details: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None


class AdminReviewDetail(AdminReviewItem):
    reports: List[AdminReviewReportItem]


class ReviewModerationRequest(BaseModel):
    note: str = Field(..., min_length=3, max_length=500)
