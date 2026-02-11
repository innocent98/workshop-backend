"""
Wallet endpoints for artisan earnings and payout management.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from decimal import Decimal
from datetime import datetime
import json

from app.db.session import get_db
from app.api.deps import get_current_user
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.service import Service
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


@router.get("/balance", response_model=WalletBalanceResponse)
async def get_wallet_balance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get wallet balance and earnings summary for artisan.

    Only artisans can access wallet.
    """
    # Only artisans have wallets
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have wallet access"
        )

    # Get all bookings for this artisan
    artisan_bookings = db.query(Booking).filter(
        Booking.artisan_id == current_user.id
    ).all()

    booking_ids = [b.id for b in artisan_bookings]

    # Get total earned (RELEASED payments)
    total_earned = db.query(func.sum(Payment.amount)).filter(
        and_(
            Payment.booking_id.in_(booking_ids) if booking_ids else False,
            Payment.status == PaymentStatus.RELEASED
        )
    ).scalar() or Decimal(0)

    # Get pending release (SUCCESS payments eligible for payout)
    # Eligibility matches request_payout rules:
    # - booking completed
    # - not disputed
    # - client confirmed OR dispute window elapsed
    pending_release = db.query(func.sum(Payment.amount)).filter(
        and_(
            Payment.booking_id.in_(booking_ids) if booking_ids else False,
            Payment.status == PaymentStatus.SUCCESS,
            Payment.booking.has(Booking.status == BookingStatus.COMPLETED),
            Payment.booking.has(Booking.completion_disputed_at.is_(None)),
            Payment.booking.has(
                or_(
                    Booking.completion_confirmed_by_client_at.is_not(None),
                    and_(
                        Booking.completion_confirmation_deadline_at.is_not(None),
                        Booking.completion_confirmation_deadline_at <= func.now(),
                    ),
                )
            ),
        )
    ).scalar() or Decimal(0)

    # Count completed jobs
    total_jobs_completed = db.query(func.count(Booking.id)).filter(
        and_(
            Booking.artisan_id == current_user.id,
            Booking.status == BookingStatus.COMPLETED
        )
    ).scalar() or 0

    # Count paid jobs
    total_jobs_paid = db.query(func.count(Booking.id)).filter(
        and_(
            Booking.artisan_id == current_user.id,
            Booking.status.in_([BookingStatus.PAID, BookingStatus.IN_PROGRESS, BookingStatus.COMPLETED])
        )
    ).scalar() or 0

    # Lifetime earnings (all time - same as total earned for now)
    lifetime_earnings = total_earned

    return {
        "total_earned": total_earned,
        "pending_release": pending_release,
        "total_jobs_completed": total_jobs_completed,
        "total_jobs_paid": total_jobs_paid,
        "lifetime_earnings": lifetime_earnings
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

    Shows all payments with booking details.
    """
    # Only artisans can access
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have earnings history"
        )

    # Get all bookings for this artisan
    artisan_bookings = db.query(Booking).filter(
        Booking.artisan_id == current_user.id
    ).all()

    booking_ids = [b.id for b in artisan_bookings]

    # Base query for payments
    query = db.query(Payment).filter(
        Payment.booking_id.in_(booking_ids) if booking_ids else False
    )

    # Apply status filter
    if status_filter:
        try:
            status_enum = PaymentStatus(status_filter)
            query = query.filter(Payment.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {status_filter}"
            )

    # Get total count
    total = query.count()

    # Apply pagination
    payments = query.order_by(Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Build response with booking details
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
            "amount": payment.amount,
            "status": payment.status.value,
            "customer_name": customer.full_name if customer else "Unknown",
            "service_name": service.name if service else None,
            "job_date": booking.job_date,
            "paid_at": payment.paid_at,
            "released_at": payment.released_at,
            "created_at": payment.created_at
        })

        if payment.status in [PaymentStatus.SUCCESS, PaymentStatus.RELEASED]:
            total_amount += payment.amount

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

    Shows all payments that have been released (paid out) to the artisan.
    """
    # Only artisans can access
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have payout history"
        )

    # Get all bookings for this artisan
    artisan_bookings = db.query(Booking).filter(
        Booking.artisan_id == current_user.id
    ).all()

    booking_ids = [b.id for b in artisan_bookings]

    # Query for RELEASED payments only
    query = db.query(Payment).filter(
        and_(
            Payment.booking_id.in_(booking_ids) if booking_ids else False,
            Payment.status == PaymentStatus.RELEASED
        )
    )

    # Get total count
    total = query.count()

    # Apply pagination
    payments = query.order_by(Payment.released_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # Build response with booking details
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
            "amount": payment.amount,
            "released_at": payment.released_at,
            "booking_reference": booking.booking_reference,
            "customer_name": customer.full_name if customer else "Unknown"
        })

    return {
        "payouts": payouts,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/stats", response_model=dict)
async def get_wallet_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get detailed wallet statistics for artisan.

    Includes monthly earnings, average job value, etc.
    """
    # Only artisans can access
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans have wallet stats"
        )

    # Get all bookings for this artisan
    artisan_bookings = db.query(Booking).filter(
        Booking.artisan_id == current_user.id
    ).all()

    booking_ids = [b.id for b in artisan_bookings]

    # Get all successful payments
    successful_payments = db.query(Payment).filter(
        and_(
            Payment.booking_id.in_(booking_ids) if booking_ids else False,
            Payment.status.in_([PaymentStatus.SUCCESS, PaymentStatus.RELEASED])
        )
    ).all()

    if not successful_payments:
        return {
            "total_earnings": "0.00",
            "average_job_value": "0.00",
            "highest_earning": "0.00",
            "lowest_earning": "0.00",
            "total_transactions": 0
        }

    amounts = [float(p.amount) for p in successful_payments]

    return {
        "total_earnings": str(sum(amounts)),
        "average_job_value": str(sum(amounts) / len(amounts)) if amounts else "0.00",
        "highest_earning": str(max(amounts)) if amounts else "0.00",
        "lowest_earning": str(min(amounts)) if amounts else "0.00",
        "total_transactions": len(successful_payments)
    }


@router.post("/payout/request", response_model=RequestPayoutResponse)
async def request_payout(
    request: RequestPayoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Request payout/withdrawal to bank account.

    Artisan can request to withdraw their available balance.
    Validates minimum amount, available balance, and bank details.
    """
    # Only artisans can request payouts
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can request payouts"
        )

    # Minimum payout amount (e.g., ₦5,000)
    MINIMUM_PAYOUT = Decimal("5000.00")

    if request.amount < MINIMUM_PAYOUT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum payout amount is ₦{MINIMUM_PAYOUT}"
        )

    # Get artisan's available balance (SUCCESS payments - paid by customer, pending release)
    artisan_bookings = db.query(Booking).filter(
        Booking.artisan_id == current_user.id
    ).all()

    booking_ids = [b.id for b in artisan_bookings]

    # Calculate available balance from payments that are:
    # - SUCCESS (paid by customer, not yet released),
    # - booking is COMPLETED,
    # - not disputed,
    # - and either client-confirmed or dispute window has elapsed.
    available_balance = db.query(func.sum(Payment.amount)).filter(
        and_(
            Payment.booking_id.in_(booking_ids) if booking_ids else False,
            Payment.status == PaymentStatus.SUCCESS,
            Payment.booking.has(Booking.status == BookingStatus.COMPLETED),
            Payment.booking.has(Booking.completion_disputed_at.is_(None)),
            Payment.booking.has(
                or_(
                    Booking.completion_confirmed_by_client_at.is_not(None),
                    and_(
                        Booking.completion_confirmation_deadline_at.is_not(None),
                        Booking.completion_confirmation_deadline_at <= func.now(),
                    ),
                )
            ),
        )
    ).scalar() or Decimal(0)

    # Check if sufficient balance
    if request.amount > available_balance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance. Available: ₦{available_balance}, Requested: ₦{request.amount}"
        )

    try:
        # Step 1: Verify bank account with Paystack
        verification = PaystackService.verify_account_number(
            account_number=request.account_number,
            bank_code=request.bank_code
        )

        verified_account_name = verification.get('account_name', '')

        # Optional: Validate account name matches (fuzzy match)
        # For now, we'll just use the verified name

        # Step 2: Create transfer recipient
        recipient = PaystackService.create_transfer_recipient(
            name=verified_account_name or request.account_name,
            account_number=request.account_number,
            bank_code=request.bank_code
        )

        recipient_code = recipient.get('recipient_code')

        # Step 3: Get payments to release (up to requested amount)
        payments_to_release = db.query(Payment).filter(
            and_(
                Payment.booking_id.in_(booking_ids) if booking_ids else False,
                Payment.status == PaymentStatus.SUCCESS,
                Payment.booking.has(Booking.status == BookingStatus.COMPLETED),
                Payment.booking.has(Booking.completion_disputed_at.is_(None)),
                Payment.booking.has(
                    or_(
                        Booking.completion_confirmed_by_client_at.is_not(None),
                        and_(
                            Booking.completion_confirmation_deadline_at.is_not(None),
                            Booking.completion_confirmation_deadline_at <= func.now(),
                        ),
                    )
                ),
            )
        ).order_by(Payment.paid_at.asc()).all()

        # Release payments until we reach the requested amount
        total_released = Decimal(0)
        released_payment_ids = []

        for payment in payments_to_release:
            if total_released >= request.amount:
                break

            amount_to_release = min(payment.amount, request.amount - total_released)

            # For simplicity, we'll release full payments
            # In production, you might want to support partial releases
            if payment.amount <= (request.amount - total_released):
                # Generate payout reference
                payout_reference = f"PAYOUT-{payment.payment_reference}"

                # Initiate transfer
                transfer = PaystackService.initiate_transfer(
                    recipient_code=recipient_code,
                    amount=payment.amount,
                    reason=f"Payout for booking {payment.booking.booking_reference}",
                    reference=payout_reference
                )

                # Update payment status
                payment.status = PaymentStatus.RELEASED
                payment.released_at = func.now()
                payment.payout_reference = payout_reference
                payment.payout_response = json.dumps(transfer)

                total_released += payment.amount
                released_payment_ids.append(payment.id)

        db.commit()

        return {
            "success": True,
            "message": f"Payout of ₦{total_released} initiated successfully",
            "payout_reference": f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "amount": total_released,
            "account_number": request.account_number,
            "bank_code": request.bank_code,
            "status": "processing"
        }

    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payout request failed: {str(e)}"
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred: {str(e)}"
        )
