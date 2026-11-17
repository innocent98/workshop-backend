"""
Wallet endpoints for artisan earnings and payout management.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from decimal import Decimal

from app.db.session import get_db
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
from app.db.models.withdrawal import Withdrawal
from app.schemas.wallet import (
    WalletBalanceResponse,
    EarningItemResponse,
    EarningsHistoryResponse,
    PayoutItemResponse,
    PayoutsHistoryResponse,
    BankItemResponse,
    VerifyAccountRequest,
    VerifyAccountResponse,
    RequestPayoutRequest,
    RequestPayoutResponse,
)
from app.services.paystack import PaystackService, PaystackError
from app.services.withdrawal_service import (
    WithdrawalError,
    available_balance,
    pending_withdrawal_amount,
    request_withdrawal,
)


router = APIRouter()


@router.get("/banks", response_model=list[BankItemResponse])
async def get_supported_banks(
    current_user: User = Depends(get_current_user),
):
    """
    Get supported Nigerian banks for payout.

    Only artisans can access wallet-related endpoints.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have wallet access"
        )

    try:
        banks = PaystackService.get_banks()
    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch banks: {str(e)}"
        )

    bank_items = []
    for bank in banks:
        bank_items.append({
            "name": bank.get("name", ""),
            "code": bank.get("code", ""),
            "slug": bank.get("slug"),
        })

    # Return a stable, user-friendly order
    bank_items.sort(key=lambda item: item["name"].lower())
    return bank_items


@router.post("/account/verify", response_model=VerifyAccountResponse)
async def verify_bank_account(
    request: VerifyAccountRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Verify bank account details before payout request.

    Only artisans can access wallet-related endpoints.
    """
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have wallet access"
        )

    try:
        verification = PaystackService.verify_account_number(
            account_number=request.account_number,
            bank_code=request.bank_code
        )
    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    return {
        "account_number": verification.get("account_number", request.account_number),
        "account_name": verification.get("account_name", ""),
        "bank_code": request.bank_code,
        "bank_name": verification.get("bank_name"),
        "verified": True,
    }


def _require_artisan(user: User, detail: str) -> None:
    if user.user_type != UserType.ARTISAN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _artisan_payments(db: Session, artisan_id):
    """Base query: every payment belonging to this artisan's bookings."""
    return db.query(Payment).join(Booking, Booking.id == Payment.booking_id).filter(
        Booking.artisan_id == artisan_id
    )


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_wallet_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get wallet balance and earnings summary for artisan.

    `pending_release` is the amount withdrawable right now (kept for app compatibility;
    `available_balance` is the same number). Money already inside a processing
    withdrawal is reported as `pending_withdrawal` and is NOT available.
    """
    _require_artisan(current_user, "Only artisans have wallet access")
    artisan_id = current_user.id

    total_earned = _artisan_payments(db, artisan_id).filter(
        Payment.status == PaymentStatus.RELEASED
    ).with_entities(func.sum(Payment.artisan_amount)).scalar() or Decimal(0)

    available = available_balance(db, artisan_id)
    pending_withdrawal = pending_withdrawal_amount(db, artisan_id)

    total_platform_fee = _artisan_payments(db, artisan_id).filter(
        Payment.status.in_([PaymentStatus.SUCCESS, PaymentStatus.RELEASED]),
    ).with_entities(func.sum(Payment.platform_fee)).scalar() or Decimal(0)

    total_jobs_completed = db.query(func.count(Booking.id)).filter(
        and_(
            Booking.artisan_id == artisan_id,
            Booking.status == BookingStatus.COMPLETED
        )
    ).scalar() or 0

    total_jobs_paid = db.query(func.count(Booking.id)).filter(
        and_(
            Booking.artisan_id == artisan_id,
            Booking.status.in_([BookingStatus.PAID, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED])
        )
    ).scalar() or 0

    return {
        "total_earned": total_earned,
        "pending_release": available,
        "total_platform_fee": total_platform_fee,
        "total_jobs_completed": total_jobs_completed,
        "total_jobs_paid": total_jobs_paid,
        "lifetime_earnings": total_earned,
        # additive fields
        "available_balance": available,
        "pending_withdrawal": pending_withdrawal,
        "min_payout": settings.MIN_PAYOUT_NGN,
    }


@router.get("/earnings", response_model=EarningsHistoryResponse)
async def get_earnings_history(
    status_filter: Optional[str] = Query(None, description="Filter by payment status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get earnings history for artisan.

    Shows all payments with booking details. `withdrawal_id` / `withdrawal_status`
    (additive) tell the app which payments are inside a withdrawal.
    """
    _require_artisan(current_user, "Only artisans have earnings history")

    query = _artisan_payments(db, current_user.id)

    if status_filter:
        try:
            status_enum = PaymentStatus(status_filter)
            query = query.filter(Payment.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )

    total = query.count()
    payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    earnings = []
    total_amount = Decimal(0)

    for payment in payments:
        booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
        if not booking:
            continue

        customer = db.query(User).filter(User.id == booking.customer_id).first()
        service = db.query(Service).filter(Service.id == booking.service_id).first()

        earnings.append({
            "payment_id": payment.id,
            "payment_reference": payment.payment_reference,
            "booking_id": booking.id,
            "booking_reference": booking.booking_reference,
            "amount": payment.artisan_amount,
            "gross_amount": payment.amount,
            "platform_fee": payment.platform_fee,
            "status": payment.status.value,
            "customer_name": customer.full_name if customer else "Unknown",
            "service_name": service.name if service else None,
            "job_date": booking.job_date,
            "paid_at": payment.paid_at,
            "released_at": payment.released_at,
            "created_at": payment.created_at,
            "withdrawal_id": payment.withdrawal_id,
            "withdrawal_status": payment.withdrawal.status.value if payment.withdrawal else None,
        })

        if payment.status in [PaymentStatus.SUCCESS, PaymentStatus.RELEASED]:
            total_amount += payment.artisan_amount

    return {
        "earnings": earnings,
        "total": total,
        "page": page,
        "page_size": page_size,
        "summary": {
            "total_amount": str(total_amount),
            "count": len(earnings)
        }
    }


@router.get("/payouts", response_model=PayoutsHistoryResponse)
async def get_payout_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get payout history for artisan.

    `payouts` keeps its original shape: one row per RELEASED payment (money that actually
    reached the bank). `withdrawals` (additive) lists every withdrawal including
    processing / failed / reversed ones, newest first.
    """
    _require_artisan(current_user, "Only artisans have payout history")

    query = _artisan_payments(db, current_user.id).filter(
        Payment.status == PaymentStatus.RELEASED
    )

    total = query.count()
    payments = query.order_by(Payment.released_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    payouts = []
    for payment in payments:
        booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
        if not booking:
            continue

        customer = db.query(User).filter(User.id == booking.customer_id).first()

        payouts.append({
            "payment_id": payment.id,
            "payment_reference": payment.payment_reference,
            "payout_reference": payment.payout_reference,
            "amount": payment.artisan_amount,
            "gross_amount": payment.amount,
            "platform_fee": payment.platform_fee,
            "released_at": payment.released_at,
            "booking_reference": booking.booking_reference,
            "customer_name": customer.full_name if customer else "Unknown",
            "withdrawal_id": payment.withdrawal_id,
        })

    withdrawals = (
        db.query(Withdrawal)
        .filter(Withdrawal.artisan_id == current_user.id)
        .order_by(Withdrawal.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "payouts": payouts,
        "total": total,
        "page": page,
        "page_size": page_size,
        "withdrawals": [_withdrawal_item(w) for w in withdrawals],
    }


def _withdrawal_item(w: Withdrawal) -> dict:
    return {
        "id": w.id,
        "reference": w.reference,
        "amount": w.amount,
        "currency": w.currency,
        "status": w.status.value,
        "bank_code": w.bank_code,
        "account_number_last4": w.account_number_last4,
        "account_name": w.account_name,
        "created_at": w.created_at,
        "completed_at": w.completed_at,
    }


@router.get("/stats", response_model=dict)
async def get_wallet_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed wallet statistics for artisan.

    Includes monthly earnings, average job value, etc. `available_balance` and
    `pending_withdrawal` are additive.
    """
    _require_artisan(current_user, "Only artisans have wallet stats")

    successful_payments = _artisan_payments(db, current_user.id).filter(
        Payment.status.in_([PaymentStatus.SUCCESS, PaymentStatus.RELEASED])
    ).all()

    available = available_balance(db, current_user.id)
    pending_withdrawal = pending_withdrawal_amount(db, current_user.id)

    if not successful_payments:
        return {
            "total_earnings": "0.00",
            "average_job_value": "0.00",
            "highest_earning": "0.00",
            "lowest_earning": "0.00",
            "total_transactions": 0,
            "available_balance": str(available),
            "pending_withdrawal": str(pending_withdrawal),
        }

    amounts = [p.artisan_amount for p in successful_payments]
    total_amount = sum(amounts, Decimal(0))

    return {
        "total_earnings": str(total_amount),
        "average_job_value": str((total_amount / len(amounts)).quantize(Decimal("0.01"))),
        "highest_earning": str(max(amounts)),
        "lowest_earning": str(min(amounts)),
        "total_transactions": len(successful_payments),
        "available_balance": str(available),
        "pending_withdrawal": str(pending_withdrawal),
    }


@router.post("/payout/request", response_model=RequestPayoutResponse)
async def request_payout(
    request: RequestPayoutRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Request a withdrawal to a bank account.

    Whole completed-job payments are picked oldest-first, up to the requested amount,
    and sent as ONE Paystack transfer. The response `amount` is what is actually being
    transferred (it can be lower than the requested amount). Send an `Idempotency-Key`
    header to make double taps / retries safe: a repeat returns the original withdrawal.
    """
    _require_artisan(current_user, "Only artisans can request payouts")

    key = idempotency_key.strip() if idempotency_key else None
    if key and len(key) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be at most 100 characters"
        )

    try:
        result = request_withdrawal(
            db,
            artisan_id=current_user.id,
            amount=request.amount,
            account_number=request.account_number,
            bank_code=request.bank_code,
            account_name=request.account_name,
            idempotency_key=key or None,
        )
    except WithdrawalError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    withdrawal = result.withdrawal
    message = (
        f"Withdrawal of ₦{withdrawal.amount:,.2f} initiated successfully"
        if withdrawal.status.value == "processing"
        else f"Withdrawal of ₦{withdrawal.amount:,.2f} is {withdrawal.status.value}"
    )
    return {
        "success": withdrawal.status.value in ("processing", "success"),
        "message": message,
        "payout_reference": withdrawal.reference,
        "amount": withdrawal.amount,
        "account_number": request.account_number,
        "bank_code": withdrawal.bank_code,
        "status": withdrawal.status.value,
        # additive fields
        "withdrawal_id": withdrawal.id,
        "requested_amount": request.amount,
        "payments_count": result.payments_count,
        "idempotent_replay": result.replay,
    }
