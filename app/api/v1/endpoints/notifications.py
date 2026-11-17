from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.models.push_device import PushDevice, PushPlatform
from app.db.models.user import User
from app.db.models.user_notification import UserNotification
from app.db.session import get_db
from app.schemas.notification import (
    PushDeviceResponse,
    RegisterPushDeviceRequest,
    UnregisterPushDeviceRequest,
    UserNotificationActionResponse,
    UserNotificationListResponse,
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
    device = (
        db.query(PushDevice)
        .filter(
            PushDevice.user_id == current_user.id,
            PushDevice.fcm_token == request.fcm_token,
            PushDevice.is_active.is_(True),
        )
        .first()
    )
    if device:
        device.is_active = False
        device.last_seen_at = datetime.now(timezone.utc)
        db.commit()

    return {"success": True, "message": "Push device unregistered"}


@router.get("", response_model=UserNotificationListResponse)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(UserNotification).filter(UserNotification.user_id == current_user.id)
    total = query.count()
    unread_count = query.filter(UserNotification.is_read.is_(False)).count()
    notifications = (
        query.order_by(UserNotification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "notifications": notifications,
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/{notification_id}/read", response_model=UserNotificationActionResponse)
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    notification = (
        db.query(UserNotification)
        .filter(
            UserNotification.id == notification_id,
            UserNotification.user_id == current_user.id,
        )
        .first()
    )
    if notification and not notification.is_read:
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)
        db.commit()

    return {"success": True, "message": "Notification marked as read"}


@router.patch("/read-all", response_model=UserNotificationActionResponse)
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.query(UserNotification).filter(
        UserNotification.user_id == current_user.id,
        UserNotification.is_read.is_(False),
    ).update(
        {
            UserNotification.is_read: True,
            UserNotification.read_at: datetime.now(timezone.utc),
        },
        synchronize_session=False,
    )
    db.commit()
    return {"success": True, "message": "All notifications marked as read"}
