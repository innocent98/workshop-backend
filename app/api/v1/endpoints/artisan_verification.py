"""
Artisan identity verification endpoints (Dojah hosted Identity widget, NIN + selfie).

``router``         -> mounted at /profiles/artisans/me/verification  (JWT, artisans only)
``webhook_router`` -> mounted at /verification                       (Dojah -> us, HMAC-signed)
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.logger import logger
from app.db.models.user import User, UserType
from app.db.models.verification_record import ArtisanVerificationRecord as Record
from app.db.session import get_db
from app.integrations.dojah.client import DojahClient, get_dojah_client
from app.integrations.dojah.signature import verify_dojah_signature
from app.schemas.verification import (
    VerificationConfigResponse,
    VerificationConfirmRequest,
    VerificationStartResponse,
    VerificationStatusResponse,
)
from app.services import artisan_verification as svc

router = APIRouter()
webhook_router = APIRouter()

# These endpoints are plain ``def`` (FastAPI runs them in its threadpool) because both the Dojah
# call and SQLAlchemy are blocking. The Dojah round trip is bounded so the app's request never
# outlives the client's own timeout: on a timeout the verification stays pending and is
# reconciled by the status poll and the webhook.
CONFIRM_TIMEOUT_S = 6.0
CONFIRM_MAX_ATTEMPTS = 2
STATUS_TIMEOUT_S = 4.0
STATUS_MAX_ATTEMPTS = 1
STATUS_RECONFIRM_WINDOW = timedelta(minutes=15)


def require_artisan(current_user: User = Depends(get_current_user)) -> User:
    if current_user.user_type != UserType.ARTISAN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only artisans can access this endpoint",
        )
    return current_user


def _provider_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "provider_error",
            "message": "Could not reach the verification provider. Please try again shortly.",
        },
    )


@router.get("/config", response_model=VerificationConfigResponse)
def get_verification_config(user: User = Depends(require_artisan)):
    """Values to initialise the Dojah widget in the app."""
    return svc.get_config()


@router.post("/start", response_model=VerificationStartResponse)
def start_verification(user: User = Depends(require_artisan), db: Session = Depends(get_db)):
    """Mint a reference_id for the widget and record a pending attempt (counts toward the limit)."""
    return svc.start_verification(db, user)


@router.post("/confirm", response_model=VerificationStatusResponse)
def confirm_verification(
    body: VerificationConfirmRequest,
    user: User = Depends(require_artisan),
    db: Session = Depends(get_db),
    dojah: Optional[DojahClient] = Depends(get_dojah_client),
):
    """Ask Dojah for the authoritative result of ``reference_id`` and return the status object."""
    try:
        svc.confirm_verification(
            db,
            body.reference_id,
            dojah,
            "api",
            user.id,
            timeout=CONFIRM_TIMEOUT_S,
            max_attempts=CONFIRM_MAX_ATTEMPTS,
        )
    except svc.UnknownReference:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "unknown_reference",
                "message": "No verification found for that reference",
            },
        )
    except svc.ProviderError as exc:
        if dojah is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "verification_unavailable",
                    "message": "Identity verification is temporarily unavailable. Try again later.",
                },
            )
        if not exc.timed_out:
            raise _provider_error()
        db.rollback()  # Dojah was slow: leave it pending and answer now (poll /status)
    return svc.build_status(db, user)


@router.get("/status", response_model=VerificationStatusResponse)
def get_verification_status(
    user: User = Depends(require_artisan),
    db: Session = Depends(get_db),
    dojah: Optional[DojahClient] = Depends(get_dojah_client),
):
    """Current state. Re-checks Dojah for the latest still-fresh pending attempt (bounded)."""
    cutoff = datetime.now(timezone.utc) - STATUS_RECONFIRM_WINDOW
    pending = (
        db.query(Record)
        .filter(Record.user_id == user.id, Record.status == "pending", Record.created_at >= cutoff)
        .order_by(Record.created_at.desc())
        .first()
    )
    if pending is not None and dojah is not None:
        reference = pending.provider_reference
        try:
            svc.confirm_verification(
                db,
                reference,
                dojah,
                "status",
                user.id,
                timeout=STATUS_TIMEOUT_S,
                max_attempts=STATUS_MAX_ATTEMPTS,
            )
        except (svc.ProviderError, svc.UnknownReference) as exc:
            db.rollback()
            logger.info(
                f"verification status: re-confirm skipped ref={reference}: {type(exc).__name__}"
            )
    return svc.build_status(db, user)


@webhook_router.post("/webhook")
async def dojah_webhook(
    request: Request,
    db: Session = Depends(get_db),
    dojah: Optional[DojahClient] = Depends(get_dojah_client),
):
    """
    Dojah -> us. Signature-checked against the RAW body. The payload itself is not trusted:
    only ``reference_id`` is read, and the result is re-fetched from Dojah.
    """
    raw = await request.body()
    if not verify_dojah_signature(raw, request.headers.get("x-dojah-signature")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_signature", "message": "Bad or missing x-dojah-signature"},
        )
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return {"status": "ok"}
    reference = (
        payload.get("reference_id") or payload.get("referenceId")
        if isinstance(payload, dict)
        else None
    )
    if not reference:
        return {"status": "ok"}
    try:
        await run_in_threadpool(svc.confirm_verification, db, str(reference), dojah, "webhook")
    except svc.UnknownReference:
        return {"status": "ok"}  # not ours / nothing to reconcile: don't make Dojah retry forever
    except svc.ProviderError:
        logger.error(f"verification webhook: provider error ref={reference}")
        raise _provider_error()  # non-2xx so Dojah retries
    return {"status": "ok"}
