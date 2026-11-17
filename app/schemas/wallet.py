from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class WalletBalanceResponse(BaseModel):
    """Response schema for wallet balance/earnings summary"""
    total_earned: Decimal  # Total amount released to artisan
    pending_release: Decimal  # Payments that are SUCCESS but not yet RELEASED
    total_platform_fee: Decimal  # Total Workchop commission on released + pending-release
    total_jobs_completed: int  # Total completed jobs
    total_jobs_paid: int  # Total paid jobs
    lifetime_earnings: Decimal  # All-time earnings
    # Additive fields (withdrawal ledger)
    available_balance: Decimal = Decimal("0")  # withdrawable now (same value as pending_release)
    pending_withdrawal: Decimal = Decimal("0")  # inside a withdrawal that is still processing
    min_payout: Optional[Decimal] = None  # minimum withdrawal amount (MIN_PAYOUT_NGN)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "total_earned": 125000.00,
            "pending_release": 25000.00,
            "total_platform_fee": 15000.00,
            "total_jobs_completed": 15,
            "total_jobs_paid": 12,
            "lifetime_earnings": 125000.00
        }
    })


class EarningItemResponse(BaseModel):
    """Response schema for individual earning item"""
    payment_id: int
    payment_reference: str
    booking_id: int
    booking_reference: str
    amount: Decimal
    gross_amount: Decimal
    platform_fee: Decimal
    status: str  # Payment status
    customer_name: str
    service_name: Optional[str]
    job_date: datetime
    paid_at: Optional[datetime]
    released_at: Optional[datetime]
    created_at: datetime
    # Additive fields
    withdrawal_id: Optional[int] = None
    withdrawal_status: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EarningsHistoryResponse(BaseModel):
    """Response schema for earnings history list"""
    earnings: List[EarningItemResponse]
    total: int
    page: int
    page_size: int
    summary: dict  # Total earned in this list


class PayoutItemResponse(BaseModel):
    """Response schema for payout history item"""
    payment_id: int
    payment_reference: str
    payout_reference: Optional[str]
    amount: Decimal
    gross_amount: Decimal
    platform_fee: Decimal
    released_at: Optional[datetime]
    booking_reference: str
    customer_name: str
    withdrawal_id: Optional[int] = None  # additive

    model_config = ConfigDict(from_attributes=True)


class WithdrawalItemResponse(BaseModel):
    """A withdrawal (one bank transfer) - additive, any status"""
    id: int
    reference: str
    amount: Decimal
    currency: str
    status: str  # processing | success | failed | reversed
    bank_code: str
    account_number_last4: str
    account_name: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class PayoutsHistoryResponse(BaseModel):
    """Response schema for payout history"""
    payouts: List[PayoutItemResponse]
    total: int
    page: int
    page_size: int
    withdrawals: List[WithdrawalItemResponse] = []  # additive


class RequestPayoutRequest(BaseModel):
    """Request schema for requesting payout"""
    amount: Decimal
    account_number: str
    bank_code: str
    account_name: str

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "amount": 50000.00,
            "account_number": "0123456789",
            "bank_code": "057",
            "account_name": "John Artisan"
        }
    })


class RequestPayoutResponse(BaseModel):
    """Response schema for payout request"""
    success: bool
    message: str
    payout_reference: Optional[str]
    amount: Decimal
    account_number: str
    bank_code: str
    status: str
    # Additive fields
    withdrawal_id: Optional[int] = None
    requested_amount: Optional[Decimal] = None
    payments_count: Optional[int] = None
    idempotent_replay: bool = False


class BankItemResponse(BaseModel):
    """Response schema for a supported bank"""
    name: str
    code: str
    slug: Optional[str] = None


class VerifyAccountRequest(BaseModel):
    """Request schema for verifying bank account details"""
    account_number: str
    bank_code: str


class VerifyAccountResponse(BaseModel):
    """Response schema for verified bank account"""
    account_number: str
    account_name: str
    bank_code: str
    bank_name: Optional[str] = None
    verified: bool = True
