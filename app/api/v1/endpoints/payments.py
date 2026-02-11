"""
Payment endpoints for managing Paystack transactions.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
import json
from datetime import datetime

from app.db.session import get_db
from app.api.deps import get_current_user
from app.db.models.user import User, UserType
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus, PaymentMethod
from app.schemas.payment import (
    InitializePaymentRequest,
    InitializePaymentResponse,
    PaymentResponse,
    PaymentWebhookPayload,
    ReleasePaymentRequest,
    VerifyPaymentResponse,
)
from app.utils.payment_reference import generate_payment_reference
from app.services.paystack import PaystackService, PaystackError
from app.tasks.notification_tasks import send_push_notification


router = APIRouter()

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
                "status": existing_payment.status.value,
                "created_at": existing_payment.created_at,
            }

    # Generate payment reference
    payment_reference = generate_payment_reference(db)

    # Prepare metadata
    metadata = {
        "booking_id": booking.id,
        "booking_reference": booking.booking_reference,
        "customer_id": str(booking.customer_id),
        "artisan_id": str(booking.artisan_id),
        "service_id": booking.service_id,
    }

    try:
        # Initialize transaction with Paystack
        paystack_response = PaystackService.initialize_transaction(
            email=current_user.email,
            amount=booking.agreed_amount,
            reference=payment_reference,
            metadata=metadata
        )

        # If an existing failed/refunded record exists, reuse it for a new checkout attempt.
        if existing_payment and existing_payment.status in [PaymentStatus.FAILED, PaymentStatus.REFUNDED]:
            existing_payment.payment_reference = payment_reference
            existing_payment.paystack_reference = paystack_response.get('reference')
            existing_payment.paystack_access_code = paystack_response.get('access_code')
            existing_payment.authorization_url = paystack_response.get('authorization_url')
            existing_payment.amount = booking.agreed_amount
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
            "status": payment.status.value,
            "created_at": payment.created_at
        }

    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
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

        # Update payment status
        if verification_response.get('status') == 'success':
            payment.status = PaymentStatus.SUCCESS
            payment.paid_at = datetime.utcnow()
            payment.payment_method = PaymentMethod(verification_response.get('channel', 'card'))
            payment.paystack_response = json.dumps(verification_response)

            # Update booking status to PAID
            booking.status = BookingStatus.PAID
            booking.paid_at = datetime.utcnow()

            db.commit()
            _notify_user(
                booking.artisan_id,
                "Payment received",
                "Client has paid for a booking. You can now start the job.",
                {"booking_id": str(booking.id), "event": "payment_success"},
            )

            return {
                "payment_reference": payment.payment_reference,
                "status": payment.status.value,
                "amount": payment.amount,
                "paid": True,
                "message": "Payment verified successfully"
            }
        else:
            payment.status = PaymentStatus.FAILED
            payment.failed_at = datetime.utcnow()
            payment.paystack_response = json.dumps(verification_response)
            db.commit()

            return {
                "payment_reference": payment.payment_reference,
                "status": payment.status.value,
                "amount": payment.amount,
                "paid": False,
                "message": "Payment verification failed"
            }

    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment verification failed: {str(e)}"
        )


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
    data = payload.get('data', {})

    # Handle charge.success event
    if event == 'charge.success':
        reference = data.get('reference')
        if not reference:
            return {"status": "ignored", "message": "No reference in payload"}

        # Find payment
        payment = db.query(Payment).filter(Payment.payment_reference == reference).first()
        if not payment:
            return {"status": "ignored", "message": "Payment not found"}

        # Skip if already processed
        if payment.status == PaymentStatus.SUCCESS:
            return {"status": "success", "message": "Payment already processed"}

        # Update payment
        payment.status = PaymentStatus.SUCCESS
        payment.paid_at = datetime.utcnow()
        payment.payment_method = PaymentMethod(data.get('channel', 'card'))
        payment.paystack_response = json.dumps(data)
        payment.paystack_reference = data.get('reference')

        # Update booking
        booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
        if booking:
            booking.status = BookingStatus.PAID
            booking.paid_at = datetime.utcnow()

        db.commit()

        if booking:
            _notify_user(
                booking.artisan_id,
                "Payment received",
                "Client has paid for a booking. You can now start the job.",
                {"booking_id": str(booking.id), "event": "payment_success"},
            )

        return {"status": "success", "message": "Payment processed"}

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
    db: Session = Depends(get_db)
):
    """
    Release payment to artisan.

    Admin or automated process releases funds after job completion.
    For now, allowing artisan to trigger release (in production, this should be admin-only).
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

    # Check permission (in production, should be admin only)
    # For now, allowing artisan to release
    if booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to release this payment"
        )

    # Check payment status
    if payment.status != PaymentStatus.SUCCESS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot release payment in {payment.status.value} status"
        )

    # Check if already released
    if payment.status == PaymentStatus.RELEASED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment already released"
        )

    # Check if booking is completed
    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot release payment. Job must be completed first."
        )

    # Guard release with client confirmation/dispute-window rule
    now_utc = datetime.utcnow()
    is_confirmed = booking.completion_confirmed_by_client_at is not None
    dispute_window_elapsed = (
        booking.completion_confirmation_deadline_at is not None
        and booking.completion_confirmation_deadline_at <= now_utc
    )
    if booking.completion_disputed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot release payment for disputed completion."
        )
    if not (is_confirmed or dispute_window_elapsed):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot release payment until customer confirms completion or dispute window elapses."
        )

    try:
        # For now, we'll just mark as released without actual transfer
        # In production, you would:
        # 1. Create transfer recipient if not exists
        # 2. Initiate transfer via Paystack
        # 3. Store transfer reference

        # TODO: Implement actual Paystack transfer
        # if request.recipient_code:
        #     transfer_response = PaystackService.initiate_transfer(
        #         recipient_code=request.recipient_code,
        #         amount=payment.amount,
        #         reason=f"Payment for booking {booking.booking_reference}",
        #         reference=f"PAYOUT-{payment.payment_reference}"
        #     )
        # elif request.account_number and request.bank_code:
        #     # Create recipient first
        #     recipient = PaystackService.create_transfer_recipient(
        #         name=request.account_name or booking.artisan.full_name,
        #         account_number=request.account_number,
        #         bank_code=request.bank_code
        #     )
        #     transfer_response = PaystackService.initiate_transfer(...)

        # For now, just mark as released
        payment.status = PaymentStatus.RELEASED
        payment.released_at = datetime.utcnow()
        payment.payout_reference = f"PAYOUT-{payment.payment_reference}"

        db.commit()
        db.refresh(payment)

        _notify_user(
            booking.artisan_id,
            "Payment released",
            "A completed booking payment has been released to your wallet flow.",
            {"booking_id": str(booking.id), "event": "payment_released"},
        )

        return payment

    except PaystackError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment release failed: {str(e)}"
        )
