from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models.push_device import PushDevice, PushPlatform
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.notification import (
    PushDeviceResponse,
    RegisterPushDeviceRequest,
    UnregisterPushDeviceRequest,
)

router = APIRouter()


@router.post("/devices/register", response_model=PushDeviceResponse)
async def register_push_device(
    request: RegisterPushDeviceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register or refresh the current user's FCM token."""
    existing = db.query(PushDevice).filter(PushDevice.fcm_token == request.fcm_token).first()
    if existing:
        existing.user_id = current_user.id
        existing.platform = PushPlatform(request.platform)
        existing.device_id = request.device_id
        existing.is_active = True
        existing.last_seen_at = datetime.now(timezone.utc)
    else:
        device = PushDevice(
            user_id=current_user.id,
            fcm_token=request.fcm_token,
            platform=PushPlatform(request.platform),
            device_id=request.device_id,
            is_active=True,
            last_seen_at=datetime.now(timezone.utc),
        )
        db.add(device)

    db.commit()
    return {"success": True, "message": "Push device registered"}


@router.post("/devices/unregister", response_model=PushDeviceResponse)
async def unregister_push_device(
    request: UnregisterPushDeviceRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark an FCM token inactive for the current user."""
    device = db.query(PushDevice).filter(
        PushDevice.user_id == current_user.id,
        PushDevice.fcm_token == request.fcm_token,
        PushDevice.is_active.is_(True),
    ).first()
    if device:
        device.is_active = False
        device.last_seen_at = datetime.now(timezone.utc)
        db.commit()

    return {"success": True, "message": "Push device unregistered"}
