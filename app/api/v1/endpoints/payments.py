"""
Payment endpoints for managing escrow holds (the provider is chosen by ESCROW_PROVIDER).
"""

import json
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logger import logger
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.user import User, UserType
from app.db.models.withdrawal import WithdrawalStatus
from app.db.session import get_db
from app.schemas.payment import (
    InitializePaymentRequest,
    InitializePaymentResponse,
    PaymentResponse,
    ReleasePaymentRequest,
    VerifyPaymentResponse,
)
from app.services.admin import handle_refund_event
from app.services.escrow import get_escrow_provider
from app.services.escrow.base import (
    HoldFailed,
    HoldFunded,
    Ignored,
    PayoutFailed,
    PayoutSucceeded,
    RefundUpdated,
    WebhookRejected,
)
from app.services.payment_service import (
    OUTCOME_ALREADY,
    OUTCOME_MISMATCH,
    OUTCOME_NOT_FOUND,
    apply_charge_failed,
    apply_charge_success,
    archive_payment_reference,
    find_payment_by_reference,
)
from app.services.provider_errors import DuplicateReferenceError, ProviderError
from app.services.withdrawal_service import settle_transfer_failure, settle_transfer_success
from app.tasks.notification_tasks import send_push_notification
from app.utils.commission import calculate_artisan_amount, calculate_platform_fee
from app.utils.payment_reference import generate_payment_reference

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


@router.post(
    "/initialize", response_model=InitializePaymentResponse, status_code=status.HTTP_201_CREATED
)
def initialize_payment(
    request: InitializePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Initialize payment for a booking.

    Only customers who own the booking can initialize payment.
    Booking must be in ACCEPTED status.
    """
    # Only customers can initialize payments
    if current_user.user_type != UserType.CLIENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only customers can initialize payments"
        )

    # Get booking
    booking = db.query(Booking).filter(Booking.id == request.booking_id).with_for_update().first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Check ownership
    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You don't own this booking"
        )

    artisan = db.query(User).filter(User.id == booking.artisan_id).first()
    if artisan is None or not artisan.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "account_unavailable",
                "message": "The artisan's account is no longer available.",
            },
        )

    # Check booking status
    if booking.status != BookingStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pay for booking in {booking.status.value} status. Booking must be accepted by artisan first.",  # noqa: E501
        )
    if booking.agreed_amount is None or booking.agreed_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking agreed amount must be greater than zero before payment can be initialized",  # noqa: E501
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

    try:
        # Start the hold with the escrow provider.
        # Retry with a fresh reference if upstream reports duplicate reference.
        escrow = get_escrow_provider()
        checkout = None
        payment_reference = None
        last_provider_error = None
        for _ in range(3):
            payment_reference = generate_payment_reference(db)
            try:
                checkout = escrow.initiate_hold(
                    booking=booking,
                    amount=booking.agreed_amount,
                    customer_email=current_user.email,
                    reference=payment_reference,
                )
                break
            except DuplicateReferenceError as e:
                last_provider_error = e
                continue

        if checkout is None:
            raise last_provider_error or ProviderError("Transaction initialization failed")

        platform_fee, artisan_amount = _payment_split(booking.agreed_amount)

        # If an existing failed/refunded record exists, reuse it for a new checkout attempt.
        if existing_payment and existing_payment.status in [
            PaymentStatus.FAILED,
            PaymentStatus.REFUNDED,
        ]:
            # keep the old reference(s): a late charge.success for them must still find this payment
            archive_payment_reference(db, existing_payment)
            existing_payment.payment_reference = payment_reference
            existing_payment.paystack_reference = checkout.reference
            existing_payment.paystack_access_code = checkout.access_code
            existing_payment.authorization_url = checkout.authorization_url
            existing_payment.amount = booking.agreed_amount
            existing_payment.platform_fee = platform_fee
            existing_payment.artisan_amount = artisan_amount
            existing_payment.currency = "NGN"
            existing_payment.status = PaymentStatus.PENDING
            existing_payment.customer_email = current_user.email
            existing_payment.customer_name = current_user.full_name
            existing_payment.paystack_response = json.dumps(checkout.raw)
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
                paystack_reference=checkout.reference,
                paystack_access_code=checkout.access_code,
                booking_id=booking.id,
                authorization_url=checkout.authorization_url,
                amount=booking.agreed_amount,
                platform_fee=platform_fee,
                artisan_amount=artisan_amount,
                currency="NGN",
                status=PaymentStatus.PENDING,
                customer_email=current_user.email,
                customer_name=current_user.full_name,
                paystack_response=json.dumps(checkout.raw),
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
            "created_at": payment.created_at,
        }

    except ProviderError as e:
        mapped_status = (
            status.HTTP_400_BAD_REQUEST
            if e.status_code is not None and 400 <= e.status_code < 500
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=mapped_status, detail=f"Payment initialization failed: {str(e)}"
        )


@router.get("/verify/{reference}", response_model=VerifyPaymentResponse)
def verify_payment(
    reference: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Verify payment status.

    Checks with Paystack and updates local payment record.
    """
    # Get payment by reference
    payment = find_payment_by_reference(db, reference)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    # Get booking
    booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to verify this payment",
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
        # Ask the escrow provider where the hold stands.
        outcome = get_escrow_provider().fetch_status(reference)
    except ProviderError as e:
        logger.error(f"Payment provider verify failed for {reference}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify payment with the payment provider. Please try again.",
        )

    if isinstance(outcome, HoldFunded):
        # Same settlement function as the webhook: idempotent, amount/currency checked.
        result = apply_charge_success(db, reference, outcome.data)
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
            "message": "Payment verified successfully",
        }

    if isinstance(outcome, HoldFailed):
        # Only a terminal provider status may fail a payment; apply_charge_failed never
        # regresses a SUCCESS/RELEASED payment.
        apply_charge_failed(db, reference, outcome.data)
        db.refresh(payment)
        return {
            "payment_reference": payment.payment_reference,
            "status": payment.status.value,
            "amount": payment.amount,
            "paid": False,
            "message": "Payment verification failed",
        }

    # pending / ongoing / abandoned / queued / processing / unknown: not paid YET. The payment
    # stays PENDING so a later verify or the webhook can still settle it.
    return {
        "payment_reference": payment.payment_reference,
        "status": payment.status.value,
        "amount": payment.amount,
        "paid": False,
        "message": "Payment not completed yet",
    }


def _handle_webhook_event(db: Session, event) -> dict:
    """Blocking part of the webhook (DB locks, row updates): runs in the threadpool."""
    if isinstance(event, HoldFunded):
        if not event.reference:
            return {"status": "ignored", "message": "No reference in payload"}
        result = apply_charge_success(db, event.reference, event.data)
        if result.outcome == OUTCOME_NOT_FOUND:
            return {"status": "ignored", "message": "Payment not found"}
        if result.outcome == OUTCOME_MISMATCH:
            # 200 so the provider stops retrying; the mismatch is logged for manual review.
            return {"status": "ignored", "message": "Amount or currency mismatch"}
        if result.outcome == OUTCOME_ALREADY:
            return {"status": "success", "message": "Payment already processed"}
        return {"status": "success", "message": "Payment processed"}

    if isinstance(event, HoldFailed):
        if not event.reference:
            return {"status": "ignored", "message": "No reference in payload"}
        result = apply_charge_failed(db, event.reference, event.data)
        if result.outcome == OUTCOME_NOT_FOUND:
            return {"status": "ignored", "message": "Payment not found"}
        return {"status": "success", "message": "Payment failure recorded"}

    if isinstance(event, PayoutSucceeded):
        outcome = settle_transfer_success(db, event.data)
        return {"status": "success", "message": f"Transfer {outcome}"}

    if isinstance(event, PayoutFailed):
        new_status = WithdrawalStatus.REVERSED if event.reversed else WithdrawalStatus.FAILED
        outcome = settle_transfer_failure(db, event.data, new_status)
        return {"status": "success", "message": f"Transfer {outcome}"}

    if isinstance(event, RefundUpdated):
        # Async refund lifecycle of an admin dispute resolution (app/services/admin.py).
        refund_status = handle_refund_event(db, event.event, event.data)
        if refund_status is None:
            return {"status": "ignored", "message": "Refund not found"}
        return {"status": "success", "message": f"Refund {refund_status}"}

    name = event.event if isinstance(event, Ignored) else None
    return {"status": "ignored", "message": f"Unhandled event: {name}"}


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Escrow provider webhook handler (Paystack today).

    Processes payment notifications from the provider.
    No authentication required (verified via the provider's signature).
    """
    # Get raw body for signature verification
    body = await request.body()

    try:
        event = get_escrow_provider().verify_and_parse_webhook(request.headers, body)
    except WebhookRejected as rejected:
        raise HTTPException(status_code=rejected.status_code, detail=rejected.detail)

    return await run_in_threadpool(_handle_webhook_event, db, event)


@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Get payment details.

    Only customer or artisan involved in the booking can view payment.
    """
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    # Get booking
    booking = db.query(Booking).filter(Booking.id == payment.booking_id).first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Check permission
    if booking.customer_id != current_user.id and booking.artisan_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to view this payment",
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
        detail="Manual payment release is disabled. Withdraw your balance from the wallet instead.",
    )
