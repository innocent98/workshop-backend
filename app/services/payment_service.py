"""
Shared charge-settlement logic.

Both ``POST /payments/webhook`` (``charge.success`` / ``charge.failed``) and
``GET /payments/verify/{reference}`` call these functions, so the two paths behave
identically and can safely race each other: the payment row is locked
(``SELECT ... FOR UPDATE``) and the transition is idempotent.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.logger import logger
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentMethod, PaymentStatus
from app.services.notify import notify_user

# Paystack channel -> our PaymentMethod. Anything unknown falls back to OTHER.
_CHANNEL_MAP = {
    "card": PaymentMethod.CARD,
    "bank": PaymentMethod.BANK,
    "bank_transfer": PaymentMethod.BANK_TRANSFER,
    "ussd": PaymentMethod.USSD,
    "mobile_money": PaymentMethod.MOBILE_MONEY,
    "qr": PaymentMethod.QR,
    "eft": PaymentMethod.EFT,
    "apple_pay": PaymentMethod.APPLE_PAY,
    "bank_account": PaymentMethod.BANK_ACCOUNT,
}

OUTCOME_PROCESSED = "processed"
OUTCOME_ALREADY = "already_processed"
OUTCOME_MISMATCH = "mismatch"
OUTCOME_NOT_FOUND = "not_found"
OUTCOME_IGNORED = "ignored"


def map_paystack_channel(channel: Optional[str]) -> PaymentMethod:
    """Map any Paystack channel string to a PaymentMethod without ever raising."""
    if not channel or not isinstance(channel, str):
        return PaymentMethod.OTHER
    return _CHANNEL_MAP.get(channel.strip().lower(), PaymentMethod.OTHER)


def naira_to_kobo(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class ChargeResult:
    outcome: str
    payment: Optional[Payment] = None
    booking: Optional[Booking] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lock_payment(db: Session, reference: str) -> Optional[Payment]:
    return (
        db.query(Payment).filter(Payment.payment_reference == reference).with_for_update().first()
    )


def charge_matches_payment(payment: Payment, data: dict) -> bool:
    """Amount (kobo) and currency reported by Paystack must equal what we stored."""
    paystack_amount = data.get("amount")
    currency = data.get("currency")
    if paystack_amount is None or not currency:
        return False
    try:
        amount_ok = int(paystack_amount) == naira_to_kobo(payment.amount)
    except (TypeError, ValueError):
        return False
    return amount_ok and str(currency).upper() == str(payment.currency).upper()


def apply_charge_success(db: Session, reference: str, data: dict) -> ChargeResult:
    """
    Settle a successful Paystack charge. Idempotent.

    - Validates amount + currency against the stored Payment (mismatch is NOT settled).
    - Payment becomes SUCCESS (from PENDING / PROCESSING / FAILED).
    - Booking moves ACCEPTED -> PAID only; it is never moved backwards.
    """
    payment = _lock_payment(db, reference)
    if payment is None:
        return ChargeResult(OUTCOME_NOT_FOUND)

    booking = db.query(Booking).filter(Booking.id == payment.booking_id).with_for_update().first()

    if payment.status in (PaymentStatus.SUCCESS, PaymentStatus.RELEASED, PaymentStatus.REFUNDED):
        db.rollback()  # release row locks, nothing to change
        return ChargeResult(OUTCOME_ALREADY, payment, booking)

    if not charge_matches_payment(payment, data):
        logger.error(
            f"Paystack charge for {reference} does not match stored payment "
            f"(paystack amount={data.get('amount')} currency={data.get('currency')}, "
            f"stored amount={payment.amount} currency={payment.currency}); NOT settled"
        )
        db.rollback()
        return ChargeResult(OUTCOME_MISMATCH, payment, booking)

    now = _now()
    payment.status = PaymentStatus.SUCCESS
    payment.paid_at = now
    payment.failed_at = None
    payment.payment_method = map_paystack_channel(data.get("channel"))
    payment.paystack_response = json.dumps(data)
    payment.paystack_reference = data.get("reference") or payment.paystack_reference

    booking_moved = False
    if booking is not None and booking.status == BookingStatus.ACCEPTED:
        booking.status = BookingStatus.PAID
        booking.paid_at = now
        booking_moved = True
    elif booking is not None:
        logger.warning(
            f"Payment {reference} succeeded but booking {booking.id} is "
            f"{booking.status.value}; booking left unchanged"
        )

    db.commit()

    if booking_moved:
        notify_user(
            booking.artisan_id,
            "Payment received",
            "Client has paid for a booking. You can now start the job.",
            {"booking_id": str(booking.id), "event": "payment_success"},
        )
    return ChargeResult(OUTCOME_PROCESSED, payment, booking)


def apply_charge_failed(db: Session, reference: str, data: dict) -> ChargeResult:
    """Mark an unpaid payment FAILED. Never regresses SUCCESS / RELEASED / REFUNDED."""
    payment = _lock_payment(db, reference)
    if payment is None:
        return ChargeResult(OUTCOME_NOT_FOUND)

    if payment.status not in (PaymentStatus.PENDING, PaymentStatus.PROCESSING):
        db.rollback()
        return ChargeResult(OUTCOME_IGNORED, payment)

    payment.status = PaymentStatus.FAILED
    payment.failed_at = _now()
    payment.paystack_response = json.dumps(data)
    db.commit()
    return ChargeResult(OUTCOME_PROCESSED, payment)
