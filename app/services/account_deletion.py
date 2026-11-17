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

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import logger
from app.db.models.admin import AdminAuditLog, DisputeResolution, DisputeResolutionType
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
# A dispute refund Paystack has accepted is not final until it is processed: a later refund.failed
# puts the payment back to success and the booking back to disputed (see services/admin.py).
IN_FLIGHT_REFUND_STATES = ("requested", "pending", "processing", "needs-attention")
UNFINISHED_WITHDRAWAL_STATES = (WithdrawalStatus.PROCESSING, WithdrawalStatus.NEEDS_REVIEW)

# Keys removed from the raw Paystack JSON kept on payment rows (customer identity, card/bank,
# device/IP). Amounts, references, status, channel, fees and ids stay for accounting.
_PII_KEYS = frozenset(
    {
        "customer",
        "authorization",
        "log",
        "ip_address",
        "recipient",
        "details",
        "email",
        "first_name",
        "last_name",
        "phone",
        "account_name",
        "account_number",
    }
)


def scrub_raw_json(raw: Any):
    """Return ``raw`` (a JSON string) without PII keys, or None if it cannot be parsed."""
    if not raw:
        return raw

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _PII_KEYS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    try:
        return json.dumps(strip(json.loads(raw)))
    except (TypeError, ValueError):
        return None


BLOCKER_MESSAGES = {
    "active_bookings": "Finish or cancel your accepted, paid, in-progress and disputed bookings.",
    "unfinished_withdrawal": "A withdrawal is still being processed. Wait for it to finish first.",
    "refund_pending": "A refund on one of your bookings is still being processed. Please wait.",
    "wallet_balance": "Withdraw your earnings first (money awaiting confirmation counts too).",
}


class DeletionBlocked(Exception):
    def __init__(self, blockers: List[dict]):
        super().__init__("account deletion blocked")
        self.blockers = blockers


_UPLOAD_SUBFOLDERS = ("profile_pictures", "portfolio")


def is_own_upload(url: str, user_id) -> bool:
    """
    True only for an image THIS app uploaded for THIS user. Uploads are named ``<user_id>_<uuid>``
    inside ``<CLOUDINARY_FOLDER>/(profile_pictures|portfolio)`` (Cloudinary) or under
    ``/static/(profile_pictures|portfolio)/`` (local). Anything else (a Google profile picture, a
    foreign URL, a path with ``..``) is never passed to the storage delete.
    """
    if not url or ".." in url or "\\" in url:
        return False
    parsed = urlparse(url)
    segments = [seg for seg in parsed.path.split("/") if seg]
    if parsed.scheme in ("http", "https"):
        cloud = settings.CLOUDINARY_CLOUD_NAME
        if (
            parsed.netloc != "res.cloudinary.com"
            or not cloud
            or not segments
            or segments[0] != cloud
        ):
            return False
        folder = settings.CLOUDINARY_FOLDER
        if folder not in segments:
            return False
        after = segments[segments.index(folder) + 1 :]
        if len(after) < 2 or after[0] not in _UPLOAD_SUBFOLDERS:
            return False
    elif not parsed.scheme and not parsed.netloc and url.startswith("/static/"):
        if len(segments) < 3 or segments[1] not in _UPLOAD_SUBFOLDERS:
            return False
    else:
        return False
    stem = segments[-1].rsplit(".", 1)[0]
    return stem.startswith(f"{user_id}_")


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

    # Money we still owe back to this customer (e.g. a duplicate or late payment): keep the account
    # so support can reach them. (The refund itself works by Paystack reference either way.)
    owed_refunds = (
        db.query(func.count(Payment.id))
        .join(Booking, Booking.id == Payment.booking_id)
        .filter(Booking.customer_id == user.id, Payment.needs_refund.is_(True))
        .scalar()
    )
    # Dispute refunds still in flight, on either side of the booking.
    in_flight_refunds = (
        db.query(func.count(DisputeResolution.id))
        .join(Booking, Booking.id == DisputeResolution.booking_id)
        .filter(
            (Booking.customer_id == user.id) | (Booking.artisan_id == user.id),
            DisputeResolution.resolution == DisputeResolutionType.REFUND_CUSTOMER.value,
            DisputeResolution.refund_status.in_(IN_FLIGHT_REFUND_STATES),
        )
        .scalar()
    )
    pending_refunds = (owed_refunds or 0) + (in_flight_refunds or 0)
    if pending_refunds:
        blockers.append({"code": "refund_pending", "count": pending_refunds})

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
    Anonymise ``user`` (caller has re-authenticated and locked the user row). Re-checks the blockers
    under row locks and raises ``DeletionBlocked`` (after a rollback) if any. Commits. Returns
    ``{"image_urls": [...], "notify": [(user_id, title, body, data), ...]}``: only images this app
    uploaded for the user (``is_own_upload``), and the notifications to send after the commit.
    """
    now = datetime.now(timezone.utc)
    uid = user.id
    notify: list = []

    # Lock the rows the blocker checks depend on, THEN check (READ COMMITTED sees whatever
    # committed up to now): writers that lock these rows (withdrawals lock the user and the
    # payments, payment settlement locks the booking) serialise with us, so nothing can slip
    # in between this check and the commit.
    db.query(Booking.id).filter(
        (Booking.customer_id == uid) | (Booking.artisan_id == uid)
    ).with_for_update().all()
    db.query(Withdrawal.id).filter(Withdrawal.artisan_id == uid).with_for_update().all()
    db.query(Payment.id).join(Booking, Booking.id == Payment.booking_id).filter(
        (Booking.customer_id == uid) | (Booking.artisan_id == uid)
    ).with_for_update(of=Payment).all()
    blockers = find_blockers(db, user)
    if blockers:
        db.rollback()
        raise DeletionBlocked(blockers)

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

    candidates = [u for (u,) in db.query(Portfolio.image_url).filter(Portfolio.artisan_id == uid)]
    if user.profile_picture_url:
        candidates.insert(0, user.profile_picture_url)
    image_urls = [u for u in candidates if is_own_upload(u, uid)]

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
        .filter((Booking.customer_id == uid) | (Booking.artisan_id == uid))
    ):
        if payment.booking.customer_id == uid:
            payment.customer_name = "Deleted User"
            payment.customer_email = placeholder_email
        payment.paystack_response = scrub_raw_json(payment.paystack_response)
        payment.payout_response = scrub_raw_json(payment.payout_response)
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
