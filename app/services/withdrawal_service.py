"""
Artisan withdrawals: balance maths, payment selection, Paystack transfer orchestration
and settlement of Paystack transfer webhooks.

Money invariants
----------------
* A withdrawal is ONE Paystack transfer covering whole Payment rows
  (``payments.withdrawal_id``). Payments stay ``SUCCESS`` until the transfer is confirmed.
* A payment with ``withdrawal_id`` set is never part of the available balance.
* Failed / reversed transfers unlink their payments, so the money returns to the balance.
* Every state change is made inside one DB transaction with the relevant rows locked.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import logger
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.user import User
from app.db.models.withdrawal import Withdrawal, WithdrawalStatus
from app.services.notify import notify_user
from app.services.payment_service import naira_to_kobo
from app.services.paystack import PaystackError, PaystackService

GENERIC_PAYSTACK_ERROR = "We could not start your withdrawal right now. Please try again later."
ACCOUNT_VERIFY_ERROR = (
    "We could not verify that bank account. Please check the account number and bank."
)


class WithdrawalError(Exception):
    """Client-safe error: ``detail`` may be shown to the user verbatim."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class WithdrawalResult:
    withdrawal: Withdrawal
    replay: bool
    payments_count: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def naira(amount: Decimal) -> str:
    return f"₦{Decimal(amount):,.2f}"


# --------------------------------------------------------------------------- balance


def _eligible_conditions(artisan_id: UUID) -> list:
    """
    Payments that can be withdrawn: paid by the customer, not yet in a withdrawal,
    job completed, not disputed, and client-confirmed OR dispute window elapsed.
    """
    return [
        Booking.artisan_id == artisan_id,
        Payment.status == PaymentStatus.SUCCESS,
        Payment.withdrawal_id.is_(None),
        Booking.status == BookingStatus.COMPLETED,
        Booking.completion_disputed_at.is_(None),
        or_(
            Booking.completion_confirmed_by_client_at.is_not(None),
            and_(
                Booking.completion_confirmation_deadline_at.is_not(None),
                Booking.completion_confirmation_deadline_at <= func.now(),
            ),
        ),
    ]


def eligible_payments_query(db: Session, artisan_id: UUID):
    return (
        db.query(Payment)
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(*_eligible_conditions(artisan_id))
        .order_by(Payment.paid_at.asc().nulls_last(), Payment.id.asc())
    )


def available_balance(db: Session, artisan_id: UUID) -> Decimal:
    total = (
        db.query(func.sum(Payment.artisan_amount))
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(*_eligible_conditions(artisan_id))
        .scalar()
    )
    return total or Decimal("0")


def pending_withdrawal_amount(db: Session, artisan_id: UUID) -> Decimal:
    """Money in flight: processing withdrawals + needs_review ones still holding payments."""
    processing = (
        db.query(func.sum(Withdrawal.amount))
        .filter(
            Withdrawal.artisan_id == artisan_id,
            Withdrawal.status == WithdrawalStatus.PROCESSING,
        )
        .scalar()
    ) or Decimal("0")
    in_review = (
        db.query(func.sum(Payment.artisan_amount))
        .join(Withdrawal, Withdrawal.id == Payment.withdrawal_id)
        .filter(
            Withdrawal.artisan_id == artisan_id,
            Withdrawal.status == WithdrawalStatus.NEEDS_REVIEW,
        )
        .scalar()
    ) or Decimal("0")
    return processing + in_review


def select_payments(payments: List[Payment], requested: Decimal) -> List[Payment]:
    """Oldest-first greedy pick of whole payments whose total never exceeds ``requested``."""
    chosen: List[Payment] = []
    total = Decimal("0")
    for payment in payments:
        if total + payment.artisan_amount <= requested:
            chosen.append(payment)
            total += payment.artisan_amount
    return chosen


def check_minimum_total(chosen: List[Payment]) -> None:
    """The amount actually transferred (whole payments) must also meet the minimum payout."""
    total = sum((p.artisan_amount for p in chosen), Decimal("0"))
    if total < settings.MIN_PAYOUT_NGN:
        raise WithdrawalError(
            400,
            f"The completed jobs that fit your request total {naira(total)}, which is below "
            f"the minimum payout of {naira(settings.MIN_PAYOUT_NGN)}.",
        )


def no_fit_error(payments: List[Payment], requested: Decimal) -> WithdrawalError:
    if not payments:
        return WithdrawalError(400, "You have no withdrawable balance right now.")
    nearest = min(p.artisan_amount for p in payments)
    return WithdrawalError(
        400,
        f"No completed jobs fit within {naira(requested)}. Payouts are made per whole job, "
        f"so the nearest withdrawable amount is {naira(nearest)}.",
    )


# --------------------------------------------------------------------------- request


def _find_by_key(db: Session, artisan_id: UUID, key: str) -> Optional[Withdrawal]:
    return (
        db.query(Withdrawal)
        .filter(Withdrawal.artisan_id == artisan_id, Withdrawal.idempotency_key == key)
        .first()
    )


def _replay(
    db: Session, existing: Withdrawal, account_number: str, bank_code: str, amount: Decimal
):
    if (
        existing.account_number_last4 != account_number[-4:]
        or existing.bank_code != bank_code
        or (existing.requested_amount is not None and existing.requested_amount != amount)
    ):
        raise WithdrawalError(
            409, "This Idempotency-Key was already used for a different withdrawal request."
        )
    count = db.query(func.count(Payment.id)).filter(Payment.withdrawal_id == existing.id).scalar()
    return WithdrawalResult(existing, True, int(count or 0))


def request_withdrawal(
    db: Session,
    *,
    artisan_id: UUID,
    amount: Decimal,
    account_number: str,
    bank_code: str,
    account_name: str,
    idempotency_key: Optional[str],
) -> WithdrawalResult:
    min_payout = settings.MIN_PAYOUT_NGN
    if amount < min_payout:
        raise WithdrawalError(400, f"Minimum payout amount is {naira(min_payout)}")

    if idempotency_key:
        existing = _find_by_key(db, artisan_id, idempotency_key)
        if existing:
            return _replay(db, existing, account_number, bank_code, amount)

    # Fast, unlocked feasibility check so we do not call Paystack for hopeless requests.
    candidates = eligible_payments_query(db, artisan_id).all()
    preview = select_payments(candidates, amount)
    if not preview:
        raise no_fit_error(candidates, amount)
    check_minimum_total(preview)

    # Stateless Paystack calls (no DB locks held while we wait on the network).
    try:
        verification = PaystackService.verify_account_number(
            account_number=account_number, bank_code=bank_code
        )
    except PaystackError as exc:
        logger.warning(f"Payout account verification failed for artisan {artisan_id}: {exc}")
        raise WithdrawalError(400, ACCOUNT_VERIFY_ERROR)
    verified_name = verification.get("account_name") or account_name

    try:
        recipient = PaystackService.create_transfer_recipient(
            name=verified_name, account_number=account_number, bank_code=bank_code
        )
        recipient_code = recipient.get("recipient_code")
    except PaystackError as exc:
        logger.error(f"Paystack recipient creation failed for artisan {artisan_id}: {exc}")
        raise WithdrawalError(502, GENERIC_PAYSTACK_ERROR)
    if not recipient_code:
        logger.error("Paystack returned no recipient_code")
        raise WithdrawalError(502, GENERIC_PAYSTACK_ERROR)

    created = _create_locked(
        db,
        artisan_id=artisan_id,
        amount=amount,
        account_number=account_number,
        bank_code=bank_code,
        account_name=verified_name,
        recipient_code=recipient_code,
        idempotency_key=idempotency_key,
    )
    if isinstance(created, WithdrawalResult):  # idempotent replay found under lock
        return created

    return _initiate_transfer(db, created)


def _create_locked(
    db: Session,
    *,
    artisan_id: UUID,
    amount: Decimal,
    account_number: str,
    bank_code: str,
    account_name: str,
    recipient_code: str,
    idempotency_key: Optional[str],
):
    """One transaction: serialise per artisan, pick payments, create + link the withdrawal.

    Returns the new withdrawal id, or a WithdrawalResult when an idempotent replay is found.
    """
    db.rollback()  # start a clean transaction (releases anything held by earlier reads)
    try:
        # Per-artisan mutex: concurrent payout requests (double tap) queue up here.
        db.query(User.id).filter(User.id == artisan_id).with_for_update().one()

        if idempotency_key:
            existing = _find_by_key(db, artisan_id, idempotency_key)
            if existing:
                result = _replay(db, existing, account_number, bank_code, amount)
                db.rollback()
                return result

        payments = eligible_payments_query(db, artisan_id).with_for_update(of=Payment).all()
        chosen = select_payments(payments, amount)
        if not chosen:
            raise no_fit_error(payments, amount)
        check_minimum_total(chosen)

        total = sum((p.artisan_amount for p in chosen), Decimal("0"))
        withdrawal = Withdrawal(
            artisan_id=artisan_id,
            amount=total,
            requested_amount=amount,
            currency="NGN",
            status=WithdrawalStatus.PROCESSING,
            reference=f"wdr_{uuid.uuid4().hex}",
            idempotency_key=idempotency_key,
            recipient_code=recipient_code,
            bank_code=bank_code,
            account_number_last4=account_number[-4:],
            account_name=account_name,
        )
        db.add(withdrawal)
        db.flush()
        for payment in chosen:
            payment.withdrawal_id = withdrawal.id
        withdrawal_id = withdrawal.id
        db.commit()
        return withdrawal_id
    except WithdrawalError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        logger.exception("Integrity error creating withdrawal")
        raise WithdrawalError(409, "A withdrawal for this request already exists.")
    except Exception:
        db.rollback()
        logger.exception("Unexpected error creating withdrawal")
        raise WithdrawalError(500, "Something went wrong creating your withdrawal.")


def _initiate_transfer(db: Session, withdrawal_id: int) -> WithdrawalResult:
    withdrawal = db.get(Withdrawal, withdrawal_id)
    count = db.query(func.count(Payment.id)).filter(Payment.withdrawal_id == withdrawal_id).scalar()
    reference = withdrawal.reference
    try:
        transfer = PaystackService.initiate_transfer(
            recipient_code=withdrawal.recipient_code,
            amount=withdrawal.amount,
            reason="Workchop payout",
            reference=reference,
        )
    except PaystackError as exc:
        logger.error(f"Paystack transfer initiation failed for {reference}: {exc}")
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            # Definitive rejection: nothing was sent, give the money back.
            fail_withdrawal(
                db, withdrawal_id, WithdrawalStatus.FAILED, f"initiation rejected: {exc}"
            )
            raise WithdrawalError(502, GENERIC_PAYSTACK_ERROR)
        # Timeout / 5xx: outcome unknown. Keep PROCESSING; the transfer webhook settles it
        # (the transfer reference is ours, so a retry can never double-pay).
        return WithdrawalResult(withdrawal, False, int(count or 0))

    transfer_status = (transfer.get("status") or "").lower()
    withdrawal.transfer_code = transfer.get("transfer_code")
    db.commit()

    if transfer_status == "otp":
        # The transfer EXISTS at Paystack (it just needs approval). Freeing the payments here
        # could pay the artisan twice, so keep PROCESSING and flag it (reconcile/ops resolve it).
        logger.error(
            f"Paystack transfer {reference} is waiting for OTP approval; disable transfer OTP in "
            "the Paystack dashboard. Withdrawal left PROCESSING."
        )
        withdrawal.failure_reason = "transfer awaiting OTP approval at Paystack"
        db.commit()
    if transfer_status == "success":
        settle_transfer_success(db, {**transfer, "reference": reference})
    withdrawal = db.get(Withdrawal, withdrawal_id)
    db.refresh(withdrawal)
    return WithdrawalResult(withdrawal, False, int(count or 0))


# --------------------------------------------------------------------------- settlement


def _lock_withdrawal(db: Session, data: dict) -> Optional[Withdrawal]:
    reference = data.get("reference")
    transfer_code = data.get("transfer_code")
    withdrawal = None
    if reference:
        withdrawal = (
            db.query(Withdrawal).filter(Withdrawal.reference == reference).with_for_update().first()
        )
    if withdrawal is None and transfer_code:
        withdrawal = (
            db.query(Withdrawal)
            .filter(Withdrawal.transfer_code == transfer_code)
            .with_for_update()
            .first()
        )
    return withdrawal


def _linked_payments(db: Session, withdrawal_id: int) -> List[Payment]:
    return db.query(Payment).filter(Payment.withdrawal_id == withdrawal_id).with_for_update().all()


def _mark_needs_review(db: Session, withdrawal: Withdrawal, reason: str) -> str:
    """Freeze a withdrawal whose money state is unclear. Payments are left untouched."""
    logger.error(f"Withdrawal {withdrawal.reference} needs review: {reason}")
    withdrawal.status = WithdrawalStatus.NEEDS_REVIEW
    withdrawal.failure_reason = reason[:500]
    artisan_id, amount, withdrawal_id = withdrawal.artisan_id, withdrawal.amount, withdrawal.id
    db.commit()
    notify_user(
        artisan_id,
        "Withdrawal under review",
        f"Your withdrawal of {naira(amount)} is being reviewed by our team. "
        "We will update you shortly.",
        {"event": "withdrawal_needs_review", "withdrawal_id": str(withdrawal_id)},
    )
    return "needs_review"


def settle_transfer_success(db: Session, data: dict) -> str:
    """
    transfer.success: withdrawal SUCCESS, linked payments RELEASED. Idempotent.

    Anything unclear is frozen as NEEDS_REVIEW instead of being ignored: a success arriving after
    we freed the payments (FAILED/REVERSED) means the artisan may be paid twice, and a missing or
    different amount/currency means we cannot trust the match.
    """
    withdrawal = _lock_withdrawal(db, data)
    if withdrawal is None:
        db.rollback()
        return "not_found"
    if withdrawal.status in (WithdrawalStatus.SUCCESS, WithdrawalStatus.NEEDS_REVIEW):
        db.rollback()
        return "already_processed"
    if withdrawal.status in (WithdrawalStatus.FAILED, WithdrawalStatus.REVERSED):
        return _mark_needs_review(
            db,
            withdrawal,
            f"transfer.success received after the withdrawal was marked {withdrawal.status.value}; "
            "the payments were freed, check for a double payout",
        )

    paystack_amount = data.get("amount")
    currency = data.get("currency")
    if paystack_amount is None:
        return _mark_needs_review(db, withdrawal, "transfer.success carried no amount")
    if int(paystack_amount) != naira_to_kobo(withdrawal.amount):
        return _mark_needs_review(
            db,
            withdrawal,
            f"transfer.success amount {paystack_amount} kobo != withdrawal {withdrawal.amount}",
        )
    if currency and str(currency).upper() != str(withdrawal.currency).upper():
        return _mark_needs_review(
            db, withdrawal, f"transfer.success currency {currency} != {withdrawal.currency}"
        )

    now = _now()
    withdrawal.status = WithdrawalStatus.SUCCESS
    withdrawal.completed_at = now
    withdrawal.failure_reason = None
    withdrawal.transfer_code = data.get("transfer_code") or withdrawal.transfer_code
    for payment in _linked_payments(db, withdrawal.id):
        if payment.status == PaymentStatus.SUCCESS:
            payment.status = PaymentStatus.RELEASED
            payment.released_at = now
            payment.payout_reference = f"{withdrawal.reference}:{payment.id}"
            payment.payout_response = json.dumps(data)
    artisan_id, amount, withdrawal_id = withdrawal.artisan_id, withdrawal.amount, withdrawal.id
    db.commit()

    notify_user(
        artisan_id,
        "Withdrawal successful",
        f"{naira(amount)} has been sent to your bank account.",
        {"event": "withdrawal_success", "withdrawal_id": str(withdrawal_id)},
    )
    return "processed"


def fail_withdrawal(
    db: Session, withdrawal_id: int, new_status: WithdrawalStatus, reason: Optional[str]
) -> str:
    """Mark a withdrawal FAILED/REVERSED and unlink its payments. Idempotent."""
    withdrawal = (
        db.query(Withdrawal).filter(Withdrawal.id == withdrawal_id).with_for_update().first()
    )
    if withdrawal is None:
        db.rollback()
        return "not_found"
    return _apply_failure(db, withdrawal, new_status, reason)


def _apply_failure(
    db: Session, withdrawal: Withdrawal, new_status: WithdrawalStatus, reason: Optional[str]
) -> str:
    allowed_from = {WithdrawalStatus.PROCESSING}
    if new_status == WithdrawalStatus.REVERSED:
        allowed_from.add(WithdrawalStatus.SUCCESS)  # Paystack can reverse a settled transfer
    if withdrawal.status == new_status:
        db.rollback()
        return "already_processed"
    if withdrawal.status not in allowed_from:
        logger.error(
            f"{new_status.value} event for withdrawal {withdrawal.reference} in status "
            f"{withdrawal.status.value}; ignored"
        )
        db.rollback()
        return "ignored"

    withdrawal.status = new_status
    withdrawal.completed_at = _now()
    withdrawal.failure_reason = (reason or "")[:500] or None
    for payment in _linked_payments(db, withdrawal.id):
        if payment.status == PaymentStatus.RELEASED:  # undo a reversed, previously settled transfer
            payment.status = PaymentStatus.SUCCESS
            payment.released_at = None
            payment.payout_reference = None
            payment.payout_response = None
        payment.withdrawal_id = None
    artisan_id, amount, withdrawal_id = withdrawal.artisan_id, withdrawal.amount, withdrawal.id
    db.commit()

    notify_user(
        artisan_id,
        "Withdrawal failed" if new_status == WithdrawalStatus.FAILED else "Withdrawal reversed",
        f"Your withdrawal of {naira(amount)} did not go through. "
        "The money is back in your available balance.",
        {"event": f"withdrawal_{new_status.value}", "withdrawal_id": str(withdrawal_id)},
    )
    return "processed"


def settle_transfer_failure(db: Session, data: dict, new_status: WithdrawalStatus) -> str:
    """transfer.failed / transfer.reversed webhook handler."""
    withdrawal = _lock_withdrawal(db, data)
    if withdrawal is None:
        db.rollback()
        return "not_found"
    reason = data.get("reason") or data.get("message") or data.get("status")
    return _apply_failure(db, withdrawal, new_status, str(reason) if reason else None)


# --------------------------------------------------------------------------- reconciliation

RECONCILE_AFTER_MINUTES = 10
_FAILED_STATUSES = {"failed", "rejected", "blocked", "abandoned"}
_IN_FLIGHT_STATUSES = {"pending", "received", "queued", "processing", "otp"}


def reconcile_processing_withdrawals(db: Session, now: Optional[datetime] = None) -> dict:
    """
    Settle withdrawals stuck in PROCESSING (webhook never arrived, or the transfer call timed out).

    For each PROCESSING withdrawal older than RECONCILE_AFTER_MINUTES, ask Paystack
    (``GET /transfer/verify/:reference``) and apply the same settle/fail functions the webhooks use.
    Paystack saying the transfer does not exist (404) means it was never created: fail + unlink.
    Pending/otp/unknown answers and network errors leave the withdrawal untouched for the next run.
    """
    cutoff = (now or _now()) - timedelta(minutes=RECONCILE_AFTER_MINUTES)
    rows = (
        db.query(Withdrawal.id, Withdrawal.reference)
        .filter(Withdrawal.status == WithdrawalStatus.PROCESSING, Withdrawal.created_at <= cutoff)
        .order_by(Withdrawal.id)
        .all()
    )
    db.rollback()  # no transaction (or locks) held while we talk to Paystack
    summary = {"checked": len(rows), "success": 0, "failed": 0, "not_found": 0, "left": 0}

    for withdrawal_id, reference in rows:
        try:
            data = PaystackService.verify_transfer(reference)
        except PaystackError as exc:
            if exc.status_code == 404:
                logger.error(
                    f"Withdrawal {reference}: transfer does not exist at Paystack, failing"
                )
                fail_withdrawal(
                    db, withdrawal_id, WithdrawalStatus.FAILED, "transfer not found at Paystack"
                )
                summary["not_found"] += 1
            else:
                logger.warning(f"Could not verify transfer {reference}: {exc}")
                summary["left"] += 1
            continue

        status = (data.get("status") or "").lower()
        payload = {**data, "reference": reference}
        if status == "success":
            settle_transfer_success(db, payload)
            summary["success"] += 1
        elif status in _FAILED_STATUSES:
            settle_transfer_failure(db, payload, WithdrawalStatus.FAILED)
            summary["failed"] += 1
        elif status == "reversed":
            settle_transfer_failure(db, payload, WithdrawalStatus.REVERSED)
            summary["failed"] += 1
        else:
            if status == "otp":
                logger.error(f"Transfer {reference} is still waiting for OTP approval")
            elif status not in _IN_FLIGHT_STATUSES:
                logger.warning(f"Transfer {reference} has unrecognised status '{status}'")
            summary["left"] += 1
    return summary
