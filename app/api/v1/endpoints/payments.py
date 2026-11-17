"""
Payment endpoints for managing Paystack transactions.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.orm import Session
import json
from decimal import Decimal

from app.db.session import get_db
from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.withdrawal import WithdrawalStatus
from app.schemas.payment import (
    InitializePaymentRequest,
    InitializePaymentResponse,
    PaymentResponse,
    ReleasePaymentRequest,
    VerifyPaymentResponse,
)
from app.utils.payment_reference import generate_payment_reference
from app.utils.commission import calculate_artisan_amount, calculate_platform_fee
from app.services.paystack import PaystackService, PaystackError
from app.core.logger import logger
from app.services.payment_service import (
    OUTCOME_ALREADY,
    OUTCOME_MISMATCH,
    OUTCOME_NOT_FOUND,
    apply_charge_failed,
    apply_charge_success,
)
from app.services.withdrawal_service import settle_transfer_failure, settle_transfer_success
from app.tasks.notification_tasks import send_push_notification


router = APIRouter()


def _payment_split(gross_amount: Decimal) -> tuple[Decimal, Decimal]:
    platform_fee = calculate_platform_fee(
        gross_amount,
        settings.PLATFORM_COMMISSION_PERCENT,
    )
    artisan_amount = calculate_artisan_amount(
        gross_amount,
        settings.PLATFORM_COMMISSION_PERCENT,
    )
    return platform_fee, artisan_amount

def _notify_user(user_id, title: str, body: str, data: Optional[dict] = None) -> None:
    try:
        send_push_notification.delay(
            user_id=str(user_id),
            title=title,
            body=body,
            data=data or {},
        )
    except Exception:
        # Notifications must not break payment flow
        pass


@router.post("/initialize", response_model=InitializePaymentResponse, status_code=status.HTTP_201_CREATED)
async def initialize_payment(
    request: InitializePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Initialize payment for a booking.

    Only customers who own the booking can initialize payment.
    Booking must be in ACCEPTED status.
    """
    # Only customers can initialize payments
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can initialize payments"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == request.booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check ownership
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't own this booking"
        )

    # Check booking status
    if booking.status != BookingStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pay for booking in {booking.status.value} status. Booking must be accepted by artisan first."
        )
    if booking.agreed_amount is None or booking.agreed_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking agreed amount must be greater than zero before payment can be initialized"
        )

    # Idempotency for repeated initialize attempts on same booking
    existing_payment = db.query(Payment).filter(Payment.booking_id == booking.id).first()
    if existing_payment:
        # Active/paid flows should return existing payment details, not crash on unique booking_id
        if existing_payment.status in [
            PaymentStatus.PENDING,
            PaymentStatus.PROCESSING,
            PaymentStatus.SUCCESS,
            PaymentStatus.RELEASED,
        ]:
            return {
                "id": existing_payment.id,
                "payment_reference": existing_payment.payment_reference,
                "booking_id": existing_payment.booking_id,
                "authorization_url": existing_payment.authorization_url,
                "amount": existing_payment.amount,
                "platform_fee": existing_payment.platform_fee,
                "artisan_amount": existing_payment.artisan_amount,
                "status": existing_payment.status.value,
                "created_at": existing_payment.created_at,
            }

    # Prepare metadata
    metadata = {
        "booking_id": booking.id,
        "booking_reference": booking.booking_reference,
        "customer_id": str(booking.customer_id),
        "artisan_id": str(booking.artisan_id),
        "service_id": booking.service_id,
    }

    try:
        # Initialize transaction with Paystack.
        # Retry with a fresh reference if upstream reports duplicate reference.
        paystack_response = None
        payment_reference = None
        last_paystack_error = None
        for _ in range(3):
            payment_reference = generate_payment_reference(db)
            try:
                paystack_response = PaystackService.initialize_transaction(
                    email=current_user.email,
                    amount=booking.agreed_amount,
                    reference=payment_reference,
                    metadata=metadata
                )
                break
            except PaystackError as e:
                last_paystack_error = e
                if "Duplicate Transaction Reference" in str(e):
                    continue
                raise

        if paystack_response is None:
            raise last_paystack_error or PaystackError("Transaction initialization failed")

        platform_fee, artisan_amount = _payment_split(booking.agreed_amount)

        # If an existing failed/refunded record exists, reuse it for a new checkout attempt.
        if existing_payment and existing_payment.status in [PaymentStatus.FAILED, PaymentStatus.REFUNDED]:
            existing_payment.payment_reference = payment_reference
            existing_payment.paystack_reference = paystack_response.get('reference')
            existing_payment.paystack_access_code = paystack_response.get('access_code')
            existing_payment.authorization_url = paystack_response.get('authorization_url')
            existing_payment.amount = booking.agreed_amount
            existing_payment.platform_fee = platform_fee
            existing_payment.artisan_amount = artisan_amount
            existing_payment.currency = "NGN"
            existing_payment.status = PaymentStatus.PENDING
            existing_payment.customer_email = current_user.email
            existing_payment.customer_name = current_user.full_name
            existing_payment.paystack_response = json.dumps(paystack_response)
            existing_payment.payment_method = None
            existing_payment.paid_at = None
            existing_payment.released_at = None
            existing_payment.refunded_at = None
            existing_payment.failed_at = None
            payment = existing_payment
            db.commit()
            db.refresh(payment)
        else:
            # Create payment record
            payment = Payment(
                payment_reference=payment_reference,
                paystack_reference=paystack_response.get('reference'),
                paystack_access_code=paystack_response.get('access_code'),
                booking_id=booking.id,
                authorization_url=paystack_response.get('authorization_url'),
                amount=booking.agreed_amount,
                platform_fee=platform_fee,
                artisan_amount=artisan_amount,
                currency="NGN",
                status=PaymentStatus.PENDING,
                customer_email=current_user.email,
                customer_name=current_user.full_name,
                paystack_response=json.dumps(paystack_response)
            )

            db.add(payment)
            db.commit()
            db.refresh(payment)

        return {
            "id": payment.id,
            "payment_reference": payment.payment_reference,
            "booking_id": payment.booking_id,
            "authorization_url": payment.authorization_url,
            "amount": payment.amount,
            "platform_fee": payment.platform_fee,
            "artisan_amount": payment.artisan_amount,
            "status": payment.status.value,
            "created_at": payment.created_at
        }

    except PaystackError as e:
        mapped_status = (
            status.HTTP_400_BAD_REQUEST
            if e.status_code is not None and 400 <= e.status_code < 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=mapped_status,
            detail=f"Payment initialization failed: {str(e)}"
        )


@router.get("/verify/{reference}", response_model=VerifyPaymentResponse)
async def verify_payment(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verify payment status.

    Checks with Paystack and updates local payment record.
    """
    # Get payment by reference
    payment = db.query(Payment).filter(Payment.payment_reference == reference).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to verify this payment"
        )
    if payment.status in [PaymentStatus.SUCCESS, PaymentStatus.RELEASED]:
        if payment.platform_fee is None or payment.artisan_amount is None:
            platform_fee, artisan_amount = _payment_split(payment.amount)
            payment.platform_fee = platform_fee
            payment.artisan_amount = artisan_amount
            db.commit()
        return {
            "payment_reference": payment.payment_reference,
            "status": payment.status.value,
            "amount": payment.amount,
            "paid": True,
            "message": "Payment already verified",
        }

    try:
        # Verify with Paystack
        verification_response = PaystackService.verify_transaction(reference)
    except PaystackError as e:
        logger.error(f"Paystack verify failed for {reference}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify payment with the payment provider. Please try again."
        )

    paystack_status = verification_response.get('status')
    if paystack_status == 'success':
        # Same settlement function as the webhook: idempotent, amount/currency checked.
        result = apply_charge_success(db, payment.payment_reference, verification_response)
        db.refresh(payment)
        if result.outcome == OUTCOME_MISMATCH:
            return {
                "payment_reference": payment.payment_reference,
                "status": payment.status.value,
                "amount": payment.amount,
                "paid": False,
                "message": "Payment amount could not be confirmed. Please contact support.",
            }
        return {
            "payment_reference": payment.payment_reference,
            "status": payment.status.value,
            "amount": payment.amount,
            "paid": True,
            "message": "Payment verified successfully"
        }

    if paystack_status == 'failed':
        apply_charge_failed(db, payment.payment_reference, verification_response)
        db.refresh(payment)
        return {
            "payment_reference": payment.payment_reference,
            "status": payment.status.value,
            "amount": payment.amount,
            "paid": False,
            "message": "Payment verification failed"
        }

    # abandoned / ongoing / pending: the customer has not finished paying yet.
    return {
        "payment_reference": payment.payment_reference,
        "status": payment.status.value,
        "amount": payment.amount,
        "paid": False,
        "message": "Payment not completed yet"
    }


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(
    request: Request,
    x_paystack_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Paystack webhook handler.

    Processes payment notifications from Paystack.
    No authentication required (verified via signature).
    """
    # Get raw body for signature verification
    body = await request.body()

    # Verify webhook signature
    if not x_paystack_signature or not PaystackService.verify_webhook_signature(x_paystack_signature, body):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature"
        )

    # Parse webhook payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )

    event = payload.get('event')
    data = payload.get('data') or {}

    if event == 'charge.success':
        reference = data.get('reference')
        if not reference:
            return {"status": "ignored", "message": "No reference in payload"}
        result = apply_charge_success(db, reference, data)
        if result.outcome == OUTCOME_NOT_FOUND:
            return {"status": "ignored", "message": "Payment not found"}
        if result.outcome == OUTCOME_MISMATCH:
            # 200 so Paystack stops retrying; the mismatch is logged for manual review.
            return {"status": "ignored", "message": "Amount or currency mismatch"}
        if result.outcome == OUTCOME_ALREADY:
            return {"status": "success", "message": "Payment already processed"}
        return {"status": "success", "message": "Payment processed"}

    if event == 'charge.failed':
        reference = data.get('reference')
        if not reference:
            return {"status": "ignored", "message": "No reference in payload"}
        result = apply_charge_failed(db, reference, data)
        if result.outcome == OUTCOME_NOT_FOUND:
            return {"status": "ignored", "message": "Payment not found"}
        return {"status": "success", "message": "Payment failure recorded"}

    if event == 'transfer.success':
        outcome = settle_transfer_success(db, data)
        return {"status": "success", "message": f"Transfer {outcome}"}

    if event in ('transfer.failed', 'transfer.reversed'):
        new_status = (
            WithdrawalStatus.FAILED if event == 'transfer.failed' else WithdrawalStatus.REVERSED
        )
        outcome = settle_transfer_failure(db, data, new_status)
        return {"status": "success", "message": f"Transfer {outcome}"}

    return {"status": "ignored", "message": f"Unhandled event: {event}"}


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get payment details.

    Only customer or artisan involved in the booking can view payment.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found"
        )

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this payment"
        )

    return payment


@router.post("/{payment_id}/release", response_model=PaymentResponse)
async def release_payment(
    payment_id: int,
    request: ReleasePaymentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Disabled for everyone.

    Releasing funds used to be callable by the artisan and only flipped a database flag
    (no money moved). Payouts now happen exclusively through `POST /wallet/payout/request`
    and Paystack transfer webhooks. This route stays disabled until an admin-only role
    exists (see `require_admin`).
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Manual payment release is disabled. Withdraw your balance from the wallet instead."
    )
