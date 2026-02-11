"""Notification-related background tasks using Celery."""
from typing import Dict, Any, List

from app.celery_app import celery_app
from app.core.logger import logger
from app.db.session import SessionLocal
from app.db.models.push_device import PushDevice
from app.services.fcm import send_to_token


@celery_app.task(name="app.tasks.notification_tasks.send_push_notification", bind=True, max_retries=3)
def send_push_notification(
    self,
    user_id: str,
    title: str,
    body: str,
    data: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Send push notification to a user's registered devices.

    Args:
        user_id: User UUID
        title: Notification title
        body: Notification body/message
        data: Optional additional data payload

    Returns:
        Dict with status and details
    """
    db = SessionLocal()
    try:
        logger.info(f"Sending push notification to user {user_id}: {title}")
        devices = db.query(PushDevice).filter(
            PushDevice.user_id == user_id,
            PushDevice.is_active.is_(True),
        ).all()
        if not devices:
            return {
                "status": "success",
                "user_id": user_id,
                "sent": 0,
                "message": "No active push devices",
            }

        sent = 0
        failed = 0
        for device in devices:
            ok = send_to_token(
                token=device.fcm_token,
                title=title,
                body=body,
                data={str(k): str(v) for k, v in (data or {}).items()},
            )
            if ok:
                sent += 1
            else:
                failed += 1
                # Disable token after consistent send failure; client will re-register on next login/app launch.
                device.is_active = False

        db.commit()
        return {
            "status": "success",
            "user_id": user_id,
            "sent": sent,
            "failed": failed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"Error sending push notification to user {user_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
    finally:
        db.close()


@celery_app.task(name="app.tasks.notification_tasks.send_bulk_notifications")
def send_bulk_notifications(
    user_ids: List[str],
    title: str,
    body: str,
    data: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Send push notifications to multiple users.

    Args:
        user_ids: List of user UUIDs
        title: Notification title
        body: Notification body/message
        data: Optional additional data payload

    Returns:
        Dict with status and count
    """
    try:
        logger.info(f"Sending bulk notifications to {len(user_ids)} users")
        sent = 0
        for user_id in user_ids:
            send_push_notification.delay(user_id=user_id, title=title, body=body, data=data)
            sent += 1
        return {"status": "queued", "user_count": sent}
    except Exception as exc:
        logger.error(f"Error sending bulk notifications: {str(exc)}")
        return {"status": "error", "message": str(exc)}
