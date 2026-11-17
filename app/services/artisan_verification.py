"""
Artisan identity verification via Dojah's hosted Identity widget (NIN + selfie).

Flow: ``start`` mints a backend-owned reference and records a pending attempt (counts toward the
rolling attempt limit) -> the app launches the widget with that reference -> ``confirm`` (app) and
the webhook (Dojah) both call ``confirm_verification``, which asks Dojah for the authoritative
result and applies it. The NIN and the selfie never touch this backend; at most the last 4 NIN
digits are stored, and only if Dojah returns them.

Locking: no row lock is held across the Dojah HTTP call. After the fetch the record is re-locked and
re-checked, so ``confirm`` and the webhook racing on one reference apply exactly one result.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import logger
from app.db.models.artisan_profile import ArtisanProfile
from app.db.models.user import User
from app.db.models.verification_record import ArtisanVerificationRecord as Record
from app.integrations.dojah.client import DojahClient, DojahError
from app.schemas.verification import (
    VerificationConfigResponse,
    VerificationStartResponse,
    VerificationStatusResponse,
)
from app.services.notify import notify_user

REASON_INVALID_NIN = "We could not verify this NIN. Check the number and try again."
REASON_SELFIE = (
    "Your selfie did not match the photo on record for this NIN. "
    "Retake it in good light, facing the camera, with no hat or glasses."
)
REASON_ABANDONED = "Verification was not completed. Please try again."
REASON_GENERIC = "Verification could not be completed. Please try again."
REASON_SUPERSEDED = "superseded"


class UnknownReference(Exception):
    pass


class ProviderError(Exception):
    """Dojah call failed; the record stays pending and is safe to retry."""

    def __init__(self, message: str, timed_out: bool = False):
        super().__init__(message)
        self.timed_out = timed_out


def _err(code: str, message: str, http_status: int, **extra) -> HTTPException:
    return HTTPException(
        status_code=http_status, detail={"code": code, "message": message, **extra}
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_configured() -> bool:
    return bool(settings.DOJAH_API_KEY and settings.DOJAH_NIN_WIDGET_ID)


def get_config() -> VerificationConfigResponse:
    return VerificationConfigResponse(
        configured=is_configured(),
        app_id=settings.DOJAH_APP_ID,
        public_key=settings.DOJAH_PUBLIC_KEY,
        widget_id=settings.DOJAH_NIN_WIDGET_ID,
        environment=settings.DOJAH_ENVIRONMENT,
    )


def _profile(db: Session, user_id, lock: bool = False) -> ArtisanProfile:
    q = db.query(ArtisanProfile).filter(ArtisanProfile.user_id == user_id)
    if lock:
        q = q.with_for_update()
    profile = q.first()
    if profile is None:
        profile = ArtisanProfile(user_id=user_id)
        db.add(profile)
        db.flush()
    return profile


def _window_records(db: Session, user_id, now: datetime):
    cutoff = now - timedelta(hours=settings.VERIFICATION_WINDOW_HOURS)
    return (
        db.query(Record)
        .filter(Record.user_id == user_id, Record.created_at >= cutoff)
        .order_by(Record.created_at.asc())
        .all()
    )


def build_status(db: Session, user: User) -> VerificationStatusResponse:
    now = _now()
    profile = _profile(db, user.id)
    used_rows = _window_records(db, user.id, now)
    used = len(used_rows)
    remaining = max(settings.VERIFICATION_MAX_ATTEMPTS - used, 0)
    retry_at = None
    if remaining == 0 and used_rows:
        retry_at = used_rows[0].created_at + timedelta(hours=settings.VERIFICATION_WINDOW_HOURS)
    latest = (
        db.query(Record)
        .filter(Record.user_id == user.id)
        .order_by(Record.created_at.desc())
        .first()
    )
    return VerificationStatusResponse(
        verification_status=profile.verification_status,
        is_verified=profile.is_verified,
        verified_at=profile.verified_at,
        verification_method=profile.verification_method,
        failure_reason=profile.verification_failure_reason,
        nin_last4=profile.nin_last4,
        reference_id=latest.provider_reference if latest else None,
        attempts_used=used,
        attempts_remaining=remaining,
        max_attempts=settings.VERIFICATION_MAX_ATTEMPTS,
        window_hours=settings.VERIFICATION_WINDOW_HOURS,
        retry_available_at=retry_at,
    )


def start_verification(db: Session, user: User) -> VerificationStartResponse:
    if not is_configured():
        raise _err(
            "verification_unavailable",
            "Identity verification is temporarily unavailable. Please try again later.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    now = _now()
    profile = _profile(db, user.id, lock=True)  # serialises concurrent starts for this artisan
    if profile.is_verified:
        db.rollback()
        raise _err(
            "already_verified", "Your account is already verified.", status.HTTP_409_CONFLICT
        )

    in_window = _window_records(db, user.id, now)
    if len(in_window) >= settings.VERIFICATION_MAX_ATTEMPTS:
        retry_at = in_window[0].created_at + timedelta(hours=settings.VERIFICATION_WINDOW_HOURS)
        db.rollback()
        raise _err(
            "attempts_exhausted",
            "Too many verification attempts. Please try again later.",
            status.HTTP_429_TOO_MANY_REQUESTS,
            retry_available_at=retry_at.isoformat(),
        )

    for old in db.query(Record).filter(Record.user_id == user.id, Record.status == "pending"):
        old.status = "failed"
        old.failure_reason = REASON_SUPERSEDED

    reference = f"WC-NIN-{secrets.token_hex(8)}"
    db.add(Record(user_id=user.id, provider_reference=reference, status="pending"))
    profile.verification_status = "pending"
    profile.verification_method = None
    profile.verification_failure_reason = None
    db.commit()
    return VerificationStartResponse(
        reference_id=reference,
        widget_id=settings.DOJAH_NIN_WIDGET_ID,
        email=user.email,
        attempts_remaining=settings.VERIFICATION_MAX_ATTEMPTS - len(in_window) - 1,
    )


def _failure_reason(result) -> str:
    if result.dojah_status == "Abandoned":
        return REASON_ABANDONED
    if not result.id_verified:
        return REASON_INVALID_NIN
    if not result.selfie_passed:
        return REASON_SELFIE
    return REASON_GENERIC


def confirm_verification(
    db: Session,
    reference_id: str,
    client: Optional[DojahClient],
    source: str = "api",
    expected_user_id: Optional[UUID] = None,
    timeout: float = 15.0,
    max_attempts: int = 3,
) -> Record:
    """Fetch Dojah's authoritative result for ``reference_id`` and apply it. Idempotent."""
    record = db.execute(
        select(Record).where(Record.provider_reference == reference_id)
    ).scalar_one_or_none()
    if record is None or (expected_user_id is not None and record.user_id != expected_user_id):
        raise UnknownReference(reference_id)  # another user's reference looks unknown
    if record.status == "success" or record.failure_reason == REASON_SUPERSEDED:
        return record
    if client is None:
        raise ProviderError("Dojah is not configured")

    try:
        result = client.fetch_verification(reference_id, timeout=timeout, max_attempts=max_attempts)
    except DojahError as exc:
        raise ProviderError(str(exc), timed_out=exc.timed_out) from exc

    # Lock only now: the network call above ran with no lock held.
    db.rollback()  # end the read transaction so the lock below sees fresh data
    record = db.execute(
        select(Record).where(Record.provider_reference == reference_id).with_for_update()
    ).scalar_one_or_none()
    if record is None:
        raise UnknownReference(reference_id)
    if record.status == "success" or record.failure_reason == REASON_SUPERSEDED:
        db.rollback()
        return record

    record.id_verified = result.id_verified
    record.selfie_passed = result.selfie_passed
    if result.nin_last4:
        record.nin_last4 = result.nin_last4

    if result.status == "pending":
        db.commit()
        return record

    was_pending = record.status == "pending"
    passed = result.status == "success" and result.id_verified and result.selfie_passed
    record.status = "success" if passed else "failed"
    record.failure_reason = None if passed else _failure_reason(result)

    profile = _profile(db, record.user_id, lock=True)
    # An admin decision (verify/reject) wins over a late Dojah result, as does an existing pass.
    admin_decided = profile.verification_method == "admin"
    applied = False
    if not admin_decided and not profile.is_verified:
        applied = True
        if passed:
            profile.is_verified = True
            profile.verified_at = _now()
            profile.verified_by = None
            profile.verification_status = "verified"
            profile.verification_method = "dojah"
            profile.verification_reference = reference_id
            profile.verification_failure_reason = None
            if result.nin_last4:
                profile.nin_last4 = result.nin_last4
        else:
            profile.verification_status = "failed"
            profile.verification_failure_reason = record.failure_reason
    db.commit()
    logger.info(
        f"Artisan verification {record.status} user={record.user_id} "
        f"ref={reference_id} src={source}"
    )

    if applied and was_pending:
        if passed:
            notify_user(
                record.user_id,
                "You're verified",
                "Your identity has been verified.",
                {"event": "verification_approved"},
            )
        else:
            notify_user(
                record.user_id,
                "Verification failed",
                "We couldn't verify your identity. Open the app to see why and retry.",
                {"event": "verification_failed"},
            )
    return record
