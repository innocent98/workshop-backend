"""
Admin business logic: dispute resolution and manual artisan verification override.

Every state-changing action writes an ``admin_audit_logs`` row in the SAME transaction
as the change, so there is never an unaudited admin mutation.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logger import logger
from app.db.models.admin import AdminAuditLog, DisputeResolution, DisputeResolutionType
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.booking import Booking, BookingStatus
from app.db.models.payment import Payment, PaymentStatus
from app.db.models.user import User, UserType
from app.schemas.admin import AdminArtisanVerificationResponse, ResolveDisputeResponse
from app.services.notify import notify_user
from app.services.paystack import PaystackError, PaystackService


def _err(code: str, message: str, http_status: int) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def audit(
    db: Session,
    admin: User,
    action: str,
    target_type: str,
    target_id,
    details: Optional[dict] = None,
):
    db.add(
        AdminAuditLog(
            admin_id=admin.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            details=details,
        )
    )
    logger.info(f"admin_action admin={admin.id} action={action} target={target_type}:{target_id}")


def _resolution_response(
    res: DisputeResolution, booking: Booking, already: bool
) -> ResolveDisputeResponse:
    accepted = res.refund_status if res.refund_status in ACCEPTED_REFUND_STATUSES else None
    return ResolveDisputeResponse(
        booking_id=booking.id,
        booking_status=booking.status.value,
        resolution=res.resolution,
        note=res.note,
        resolved_by=str(res.admin_id),
        resolved_at=res.created_at,
        payment_status=booking.payment.status.value if booking.payment else None,
        refund_reference=res.refund_reference,
        refund_status=accepted,
        already_resolved=already,
    )


# Paystack refund states. "requested" is OUR state: the intent is committed but Paystack's outcome
# is unknown. Accepted = Paystack has the refund (money is, or is on its way, back to the customer).
ACCEPTED_REFUND_STATUSES = ("pending", "processing", "processed", "needs-attention")
_REFUND_RANK = {"requested": 0, "pending": 1, "processing": 2, "needs-attention": 3, "processed": 4}


def _normalise_refund_status(raw) -> str:
    value = str(raw or "pending").lower()
    return value if value in ACCEPTED_REFUND_STATUSES or value == "failed" else "pending"


def _find_refund(refunds) -> Optional[dict]:
    """First non-failed refund in a Paystack refund list (None if there is none)."""
    for item in refunds or []:
        if isinstance(item, dict) and _normalise_refund_status(item.get("status")) != "failed":
            return item
    return None


def _release(booking: Booking, now: datetime) -> None:
    # Admin override of the client's confirmation: the unchanged payout flow now sees
    # "confirmed and not disputed" and makes the money available.
    booking.completion_confirmed_by_client_at = now
    booking.completion_disputed_at = None
    booking.completion_dispute_reason = None
    booking.status = BookingStatus.COMPLETED


def _notify_release(booking: Booking) -> None:
    notify_user(
        booking.artisan_id,
        "Dispute resolved",
        "Support resolved the dispute in your favour. Your payment is now available.",
        {"booking_id": booking.id, "event": "dispute_resolved"},
    )
    notify_user(
        booking.customer_id,
        "Dispute resolved",
        "Support reviewed your dispute and released the payment to the artisan.",
        {"booking_id": booking.id, "event": "dispute_resolved"},
    )


def resolve_dispute(
    db: Session,
    admin: User,
    booking_id: int,
    resolution: str,
    note: str,
) -> ResolveDisputeResponse:
    """
    Resolve a disputed booking.

    release_to_artisan: one transaction (see ``_release``).

    refund_customer is a two-phase, intent-first flow so money can never be both refunded and paid
    out, whatever goes wrong with Paystack or the database:
      1. (txn, booking locked) validate and COMMIT a resolution row with refund_status='requested'.
         From here ``release_to_artisan`` is refused, and the booking stays disputed, so no payout
         path opens.
      2. Call Paystack with no lock held. On any error, reconcile with ``GET /refund`` instead of
         guessing: a refund found there is adopted; nothing found + a definite 4xx rejection rolls
         the intent back; anything else leaves the intent in place (``refund_unconfirmed``) and the
         admin retries (which reconciles first).
      3. (txn) mark payment refunded / booking cancelled and store Paystack's refund status.
    Paystack's async refund.* events then advance or revert it (``handle_refund_event``).

    Idempotent: repeating an accepted resolution returns it (``already_resolved=true``) without
    touching Paystack again. ``dispute_resolutions.booking_id`` is UNIQUE.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).with_for_update().first()
    if booking is None:
        raise _err("booking_not_found", "Booking not found", status.HTTP_404_NOT_FOUND)

    existing = (
        db.query(DisputeResolution).filter(DisputeResolution.booking_id == booking.id).first()
    )
    if existing:
        return _resolve_existing(db, admin, booking, existing, resolution, note)

    if booking.status != BookingStatus.DISPUTED or booking.completion_disputed_at is None:
        raise _err("not_disputed", "Booking has no open dispute.", status.HTTP_409_CONFLICT)

    record = DisputeResolution(
        booking_id=booking.id,
        admin_id=admin.id,
        resolution=resolution,
        note=note,
        disputed_at=booking.completion_disputed_at,
        dispute_reason=booking.completion_dispute_reason,
    )

    if resolution == DisputeResolutionType.RELEASE_TO_ARTISAN.value:
        _release(booking, _now())
        db.add(record)
        audit(db, admin, f"dispute.{resolution}", "booking", booking.id)
        return _commit_resolution(db, booking, record, resolution, release=True)

    _check_refundable(booking)
    record.refund_status = "requested"
    db.add(record)
    audit(db, admin, "dispute.refund_requested", "booking", booking.id)
    _commit_resolution(db, booking, record, resolution, release=False)
    return _run_refund(db, admin, booking.id)


def _check_refundable(booking: Booking) -> None:
    payment = booking.payment
    if payment is None or not payment.paystack_reference:
        raise _err(
            "payment_not_refundable",
            "Booking has no refundable payment.",
            status.HTTP_409_CONFLICT,
        )
    if payment.status != PaymentStatus.SUCCESS:
        raise _err(
            "payment_not_refundable",
            f"Payment is '{payment.status.value}'; only held funds can be refunded.",
            status.HTTP_409_CONFLICT,
        )


def _commit_resolution(db, booking, record, resolution, release: bool):
    booking_id = booking.id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = (
            db.query(DisputeResolution).filter(DisputeResolution.booking_id == booking_id).first()
        )
        booking = db.get(Booking, booking_id)
        if raced and raced.resolution == resolution and release:
            return _resolution_response(raced, booking, already=True)
        raise _err(
            "already_resolved",
            "This dispute was just resolved by someone else.",
            status.HTTP_409_CONFLICT,
        )
    if release:
        db.refresh(record)
        db.refresh(booking)
        _notify_release(booking)
        return _resolution_response(record, booking, already=False)
    return None


def _resolve_existing(
    db: Session,
    admin: User,
    booking: Booking,
    existing: DisputeResolution,
    resolution: str,
    note: str,
) -> ResolveDisputeResponse:
    release = resolution == DisputeResolutionType.RELEASE_TO_ARTISAN.value
    existing_is_release = existing.resolution == DisputeResolutionType.RELEASE_TO_ARTISAN.value

    if existing_is_release:
        db.rollback()
        if release:
            return _resolution_response(existing, booking, already=True)
        raise _err(
            "already_resolved",
            "This dispute was already resolved as 'release_to_artisan'.",
            status.HTTP_409_CONFLICT,
        )

    # existing resolution is a refund
    if release:
        if existing.refund_status != "failed":
            db.rollback()
            raise _err(
                "refund_in_progress",
                "A refund exists for this booking (confirmed, or its outcome is still being "
                "reconciled), so the payment cannot be released to the artisan.",
                status.HTTP_409_CONFLICT,
            )
        # Paystack confirmed the refund FAILED, so the money is still held: allow releasing.
        _release(booking, _now())
        existing.resolution = DisputeResolutionType.RELEASE_TO_ARTISAN.value
        existing.note = note
        existing.admin_id = admin.id
        existing.refund_status = None
        audit(db, admin, "dispute.release_after_failed_refund", "booking", booking.id)
        return _commit_resolution(db, booking, existing, existing.resolution, release=True)

    if existing.refund_status in ("requested", "failed"):
        # Retry: back to "requested" (intent), then reconcile-first inside _run_refund.
        existing.refund_status = "requested"
        existing.note = note
        audit(db, admin, "dispute.refund_retry", "booking", booking.id)
        db.commit()
        return _run_refund(db, admin, booking.id)

    db.rollback()
    return _resolution_response(existing, booking, already=True)


def _run_refund(db: Session, admin: User, booking_id: int) -> ResolveDisputeResponse:
    """Phase 2+3. The intent row (refund_status='requested') is already committed."""
    booking = db.get(Booking, booking_id)
    payment = booking.payment
    reference = payment.paystack_reference
    booking_ref = booking.booking_reference
    db.rollback()  # no transaction / lock held across the HTTP calls below

    data: Optional[dict] = None
    try:
        data = PaystackService.refund(
            reference,
            customer_note="Refund for a disputed booking",
            merchant_note=f"Dispute resolution for booking {booking_ref}",
        )
    except PaystackError as exc:
        logger.error(f"Refund call failed booking={booking_id}: {exc.message[:200]}")
        definite = (
            exc.status_code is not None
            and 400 <= exc.status_code < 500
            and exc.status_code not in (408, 429)
        )
        try:
            data = _find_refund(PaystackService.list_refunds(reference))
        except PaystackError:
            raise _err(
                "refund_unconfirmed",
                "Could not confirm the refund with Paystack. The refund is recorded as requested, "
                "so the payment cannot be released; retry to reconcile.",
                status.HTTP_502_BAD_GATEWAY,
            )
        if data is None:
            if definite:
                _drop_refund_intent(db, booking_id)
                raise _err(
                    "refund_failed",
                    "Paystack rejected the refund. Nothing was refunded; you can try again.",
                    status.HTTP_502_BAD_GATEWAY,
                )
            raise _err(
                "refund_unconfirmed",
                "Paystack did not answer and no refund was found. The refund is recorded as "
                "requested, so the payment cannot be released; retry to reconcile.",
                status.HTTP_502_BAD_GATEWAY,
            )
    return _complete_refund(db, admin, booking_id, data)


def _drop_refund_intent(db: Session, booking_id: int) -> None:
    record = db.query(DisputeResolution).filter(DisputeResolution.booking_id == booking_id).first()
    if record is not None and record.refund_status in ("requested", "failed"):
        db.delete(record)
        db.commit()


def _complete_refund(
    db: Session, admin: User, booking_id: int, data: dict
) -> ResolveDisputeResponse:
    booking = db.query(Booking).filter(Booking.id == booking_id).with_for_update().first()
    record = db.query(DisputeResolution).filter(DisputeResolution.booking_id == booking_id).one()
    payment = booking.payment
    refund_status = _normalise_refund_status(data.get("status"))
    record.refund_reference = str(data["id"]) if data.get("id") is not None else None

    if refund_status == "failed":
        record.refund_status = "failed"
        db.commit()
        raise _err(
            "refund_failed",
            "Paystack reported the refund as failed. Nothing was refunded; you can retry.",
            status.HTTP_502_BAD_GATEWAY,
        )

    now = _now()
    if _REFUND_RANK.get(record.refund_status or "", -1) <= _REFUND_RANK[refund_status]:
        record.refund_status = refund_status
    payment.status = PaymentStatus.REFUNDED
    payment.refunded_at = payment.refunded_at or now
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = booking.cancelled_at or now
    booking.cancellation_reason = f"Refunded after dispute: {record.note}"
    audit(
        db,
        admin,
        "dispute.refund_customer",
        "booking",
        booking_id,
        {"refund_reference": record.refund_reference, "refund_status": record.refund_status},
    )
    db.commit()
    db.refresh(record)
    db.refresh(booking)
    notify_user(
        booking.customer_id,
        "Refund issued",
        "Your dispute was resolved and your payment is being refunded.",
        {"booking_id": booking.id, "event": "dispute_refunded"},
    )
    notify_user(
        booking.artisan_id,
        "Dispute resolved",
        "Support resolved the dispute and refunded the customer.",
        {"booking_id": booking.id, "event": "dispute_refunded"},
    )
    return _resolution_response(record, booking, already=False)


def handle_refund_event(db: Session, event: str, data: dict) -> Optional[str]:
    """
    Apply a Paystack ``refund.*`` webhook event (pending / processing / processed / failed) to the
    matching dispute resolution. Returns the resulting refund_status, or None if the event is not
    one of ours. The webhook route (payments.py) must verify the Paystack signature and then call
    this; that wiring is intentionally left to the payments rebase.

    * Never moves a refund backwards (a late ``pending`` after ``processed`` is ignored) and a
      ``processed`` refund is final.
    * ``failed`` means the money did not go back: payment -> success, booking -> disputed again, so
      the admin can retry the refund or release instead.

    Event payload keys are taken from Paystack's refund object (``transaction_reference`` or
    ``transaction.reference``, ``id``, ``status``); NOT VERIFIED against a live webhook.
    """
    if not event or not event.startswith("refund."):
        return None
    new = _normalise_refund_status(event.split(".", 1)[1] or (data or {}).get("status"))
    data = data or {}
    tx = data.get("transaction_reference") or (data.get("transaction") or {}).get("reference")
    if not tx:
        return None

    payment = db.query(Payment).filter(Payment.paystack_reference == str(tx)).first()
    if payment is None:
        return None
    booking = db.query(Booking).filter(Booking.id == payment.booking_id).with_for_update().first()
    record = (
        db.query(DisputeResolution)
        .filter(
            DisputeResolution.booking_id == payment.booking_id,
            DisputeResolution.resolution == DisputeResolutionType.REFUND_CUSTOMER.value,
        )
        .first()
    )
    if record is None:
        db.rollback()
        return None

    current = record.refund_status
    if current == "processed" or (current == "failed" and new != "failed"):
        db.rollback()
        return current
    if new == "failed":
        record.refund_status = "failed"
        payment.status = PaymentStatus.SUCCESS
        payment.refunded_at = None
        booking.status = BookingStatus.DISPUTED
        booking.cancelled_at = None
        booking.cancellation_reason = None
        db.add(
            AdminAuditLog(
                admin_id=record.admin_id,
                action="refund.failed_event",
                target_type="booking",
                target_id=str(booking.id),
                details={"refund_reference": record.refund_reference},
            )
        )
        logger.warning(f"Refund failed event booking={booking.id}: dispute reopened")
    elif _REFUND_RANK.get(current or "", -1) <= _REFUND_RANK[new]:
        record.refund_status = new
    if data.get("id") is not None and not record.refund_reference:
        record.refund_reference = str(data["id"])
    result = record.refund_status
    db.commit()
    return result


def _artisan_profile(db: Session, user_id: UUID) -> ArtisanProfile:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.user_type != UserType.ARTISAN:
        raise _err("artisan_not_found", "Artisan not found", status.HTTP_404_NOT_FOUND)
    profile = (
        db.query(ArtisanProfile).filter(ArtisanProfile.user_id == user.id).with_for_update().first()
    )
    if profile is None:
        profile = ArtisanProfile(user_id=user.id)
        db.add(profile)
        db.flush()
    return profile


def _verification_response(profile: ArtisanProfile) -> AdminArtisanVerificationResponse:
    return AdminArtisanVerificationResponse(
        user_id=str(profile.user_id),
        is_verified=profile.is_verified,
        verification_status=profile.verification_status,
        verification_method=profile.verification_method,
        verified_at=profile.verified_at,
        verification_failure_reason=profile.verification_failure_reason,
    )


def admin_verify_artisan(db: Session, admin: User, user_id: UUID, note: Optional[str]):
    profile = _artisan_profile(db, user_id)
    profile.is_verified = True
    profile.verified_at = _now()
    profile.verified_by = admin.id
    profile.verification_status = "verified"
    profile.verification_method = "admin"
    profile.verification_failure_reason = None
    audit(db, admin, "artisan.verify", "user", user_id, {"note": note})
    db.commit()
    db.refresh(profile)
    notify_user(
        user_id,
        "You're verified",
        "Your artisan account has been verified.",
        {"event": "verification_approved"},
    )
    return _verification_response(profile)


def admin_reject_artisan(db: Session, admin: User, user_id: UUID, note: str):
    profile = _artisan_profile(db, user_id)
    profile.is_verified = False
    profile.verified_at = None
    profile.verified_by = admin.id
    profile.verification_status = "failed"
    profile.verification_method = "admin"
    profile.verification_failure_reason = note
    audit(db, admin, "artisan.reject", "user", user_id, {"note": note})
    db.commit()
    db.refresh(profile)
    notify_user(
        user_id,
        "Verification declined",
        "Your verification was declined. Open the app to see why and retry.",
        {"event": "verification_rejected"},
    )
    return _verification_response(profile)
