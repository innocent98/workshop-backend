"""
Account deletion (App Store / Google Play requirement): soft delete + anonymise.

The ``users`` row is kept (inactive, anonymised) because bookings, payments and withdrawals must
remain for accounting and keep their foreign keys. Everything personal is removed or replaced with
unique-safe placeholders; every existing token dies because ``get_current_user`` rejects inactive
users. Deletion is refused while money or work is in flight (see ``find_blockers``).

Deliberately NOT touched: booking/payment amounts, references and statuses, Paystack references,
withdrawal rows (only the account holder's name on them is cleared), reviews (ratings stay, the
reviewer name shows as "Deleted User"), and the booking free-text/location fields (kept for the
counterparty's records and disputes; a legal-retention decision, see the SOP).
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.db.models.admin import AdminAuditLog
from app.db.models.artisan_profile import ArtisanProfile, AvailabilityStatus
from app.db.models.booking import Booking, BookingStatus
from app.db.models.otp import OTP
from app.db.models.password_reset import PasswordResetToken
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.portfolio import Portfolio
from app.db.models.push_device import PushDevice
from app.db.models.service import UserService
from app.db.models.user import User
from app.db.models.user_notification import UserNotification
from app.db.models.verification_record import ArtisanVerificationRecord
from app.db.models.withdrawal import Withdrawal, WithdrawalStatus

ACTIVE_BOOKING_STATES = (
    BookingStatus.ACCEPTED,
    BookingStatus.PAID,
    BookingStatus.IN_PROGRESS,
    BookingStatus.DISPUTED,
)
UNFINISHED_WITHDRAWAL_STATES = (WithdrawalStatus.PROCESSING, WithdrawalStatus.NEEDS_REVIEW)

BLOCKER_MESSAGES = {
    "active_bookings": "Finish or cancel your accepted, paid, in-progress and disputed bookings.",
    "unfinished_withdrawal": "A withdrawal is still being processed. Wait for it to finish first.",
    "wallet_balance": "Withdraw your earnings first (money awaiting confirmation counts too).",
}


def find_blockers(db: Session, user: User) -> List[dict]:
    """Reasons the account cannot be deleted yet (empty list = deletable)."""
    blockers: List[dict] = []

    active = (
        db.query(func.count(Booking.id))
        .filter(
            (Booking.customer_id == user.id) | (Booking.artisan_id == user.id),
            Booking.status.in_(ACTIVE_BOOKING_STATES),
        )
        .scalar()
    )
    if active:
        blockers.append({"code": "active_bookings", "count": active})

    unfinished = (
        db.query(func.count(Withdrawal.id))
        .filter(
            Withdrawal.artisan_id == user.id,
            Withdrawal.status.in_(UNFINISHED_WITHDRAWAL_STATES),
        )
        .scalar()
    )
    if unfinished:
        blockers.append({"code": "unfinished_withdrawal", "count": unfinished})

    # Completed jobs whose money has not been withdrawn: withdrawable now, or still inside the
    # client's confirmation window. Either way it is the artisan's money and must be paid out first.
    owed = (
        db.query(func.coalesce(func.sum(Payment.artisan_amount), 0))
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(
            Booking.artisan_id == user.id,
            Booking.status == BookingStatus.COMPLETED,
            Payment.status == PaymentStatus.SUCCESS,
            Payment.withdrawal_id.is_(None),
        )
        .scalar()
    )
    if owed and Decimal(owed) > 0:
        blockers.append({"code": "wallet_balance", "amount": str(Decimal(owed))})

    for b in blockers:
        b["message"] = BLOCKER_MESSAGES[b["code"]]
    return blockers


def delete_account(db: Session, user: User) -> dict:
    """
    Anonymise ``user`` (caller has locked the row, checked blockers and re-authenticated).
    Commits. Returns ``{"image_urls": [...], "notify": [(user_id, title, body, data), ...]}`` so the
    caller can delete stored images and send notifications after the commit.
    """
    now = datetime.now(timezone.utc)
    uid = user.id
    notify: list = []

    # Pending requests hold no money: close them so the other side is not left waiting.
    pending = (
        db.query(Booking)
        .filter(
            (Booking.customer_id == uid) | (Booking.artisan_id == uid),
            Booking.status == BookingStatus.PENDING,
        )
        .all()
    )
    for b in pending:
        if b.customer_id == uid:
            b.status = BookingStatus.CANCELLED
            b.cancelled_at = now
            b.cancellation_reason = "The customer deleted their account"
            notify.append(
                (
                    b.artisan_id,
                    "Booking cancelled",
                    "A customer cancelled a booking request.",
                    {"booking_id": b.id, "event": "booking_cancelled"},
                )
            )
        else:
            b.status = BookingStatus.REJECTED
            b.rejection_reason = "The artisan is no longer available (account deleted)"
            notify.append(
                (
                    b.customer_id,
                    "Booking rejected",
                    "The artisan is no longer available.",
                    {"booking_id": b.id, "event": "booking_rejected"},
                )
            )

    image_urls = [u for (u,) in db.query(Portfolio.image_url).filter(Portfolio.artisan_id == uid)]
    if user.profile_picture_url:
        image_urls.insert(0, user.profile_picture_url)

    # Personal / auxiliary rows that have no accounting value.
    for model, col in (
        (Portfolio, Portfolio.artisan_id),
        (PushDevice, PushDevice.user_id),
        (UserNotification, UserNotification.user_id),
        (OTP, OTP.user_id),
        (PasswordResetToken, PasswordResetToken.user_id),
        (UserService, UserService.user_id),
        (ArtisanVerificationRecord, ArtisanVerificationRecord.user_id),
    ):
        db.query(model).filter(col == uid).delete(synchronize_session=False)

    profile = db.query(ArtisanProfile).filter(ArtisanProfile.user_id == uid).first()
    if profile is not None:
        profile.location = None
        profile.location_address = None
        profile.specialization = None
        profile.verification_documents = None
        profile.nin_last4 = None
        profile.verification_reference = None
        profile.verification_failure_reason = None
        profile.availability_status = AvailabilityStatus.OFFLINE

    # Unique-safe placeholders (email and phone are unique columns; the real values are freed).
    placeholder_email = f"deleted+{uid.hex}@deleted.invalid"
    user.full_name = "Deleted User"
    user.email = placeholder_email
    user.phone_number = f"del_{uid.hex[:12]}"
    user.hashed_password = None
    user.google_id = None
    user.bio = None
    user.profile_picture_url = None
    user.location_address = None
    user.location_latitude = None
    user.location_longitude = None
    user.is_active = False
    user.is_email_verified = False
    user.deleted_at = now

    # Financial rows stay; only the personal details copied onto them are scrubbed.
    for payment in (
        db.query(Payment)
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(Booking.customer_id == uid)
    ):
        payment.customer_name = "Deleted User"
        payment.customer_email = placeholder_email
    db.query(Withdrawal).filter(Withdrawal.artisan_id == uid).update(
        {Withdrawal.account_name: None}, synchronize_session=False
    )

    # Actor is the user themself; details carry no personal data.
    db.add(
        AdminAuditLog(
            admin_id=uid,
            action="user.self_delete",
            target_type="user",
            target_id=str(uid),
            details={"user_type": user.user_type.value, "pending_bookings_closed": len(pending)},
        )
    )
    db.commit()
    logger.info(f"Account deleted user={uid}")
    return {"image_urls": image_urls, "notify": notify}
