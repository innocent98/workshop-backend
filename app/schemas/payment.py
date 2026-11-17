from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class InitializePaymentRequest(BaseModel):
    """Request schema for initializing payment"""

    booking_id: int = Field(..., gt=0)

    model_config = ConfigDict(json_schema_extra={"example": {"booking_id": 1}})


class InitializePaymentResponse(BaseModel):
    """Response schema for payment initialization"""

    id: int
    payment_reference: str
    booking_id: int
    authorization_url: str
    amount: Decimal
    platform_fee: Decimal
    artisan_amount: Decimal
    status: str
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": 1,
                "payment_reference": "PAY-2025-000001",
                "booking_id": 1,
                "authorization_url": "https://checkout.paystack.com/xxxxxxxxx",
                "amount": 7500.00,
                "platform_fee": 750.00,
                "artisan_amount": 6750.00,
                "status": "pending",
                "created_at": "2025-01-31T10:00:00Z",
            }
        },
    )


class PaymentResponse(BaseModel):
    """Response schema for payment details"""

    id: int
    payment_reference: str
    paystack_reference: Optional[str]
    booking_id: int
    authorization_url: Optional[str]
    amount: Decimal
    platform_fee: Decimal
    artisan_amount: Decimal
    currency: str
    payment_method: Optional[str]
    status: str
    customer_email: str
    customer_name: str
    paid_at: Optional[datetime]
    released_at: Optional[datetime]
    refunded_at: Optional[datetime]
    failed_at: Optional[datetime]
    payout_reference: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaymentWebhookPayload(BaseModel):
    """Schema for Paystack webhook payload"""

    event: str
    data: dict

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event": "charge.success",
                "data": {
                    "reference": "PAY-2025-000001",
                    "amount": 750000,
                    "status": "success",
                    "customer": {"email": "customer@example.com"},
                },
            }
        }
    )


class ReleasePaymentRequest(BaseModel):
    """Request schema for releasing payment to artisan"""

    recipient_code: Optional[str] = None
    account_number: Optional[str] = None
    bank_code: Optional[str] = None
    account_name: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "account_number": "0123456789",
                "bank_code": "057",
                "account_name": "John Artisan",
            }
        }
    )


class VerifyPaymentResponse(BaseModel):
    """Response schema for payment verification"""

    payment_reference: str
    status: str
    amount: Decimal
    paid: bool
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "payment_reference": "PAY-2025-000001",
                "status": "success",
                "amount": 7500.00,
                "paid": True,
                "message": "Payment verified successfully",
            }
        }
    )
