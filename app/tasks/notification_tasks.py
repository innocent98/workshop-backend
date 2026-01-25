"""
Notification-related background tasks using Celery.
TODO: Implement when FCM integration is added.
"""
from typing import Dict, Any, List
from celery import shared_task

from app.celery_app import celery_app
from app.core.logger import logger


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
    try:
        logger.info(f"Sending push notification to user {user_id}: {title}")

        # TODO: Implement FCM notification sending
        # This is a placeholder for future implementation

        logger.warning("Push notification sending not yet implemented - FCM integration pending")

        return {
            "status": "pending",
            "user_id": user_id,
            "message": "FCM not yet integrated"
        }

    except Exception as exc:
        logger.error(f"Error sending push notification to user {user_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


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

        # TODO: Implement bulk FCM notification sending
        # This is a placeholder for future implementation

        return {
            "status": "pending",
            "user_count": len(user_ids),
            "message": "FCM not yet integrated"
        }

    except Exception as exc:
        logger.error(f"Error sending bulk notifications: {str(exc)}")
        return {"status": "error", "message": str(exc)}
