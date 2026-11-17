"""Fire-and-forget push notification helper shared by services and endpoints."""

from typing import Optional

from app.core.logger import logger
from app.tasks.notification_tasks import send_push_notification


def notify_user(user_id, title: str, body: str, data: Optional[dict] = None) -> None:
    """Queue a push notification. Never raises: notifications must not break money flows."""
    try:
        send_push_notification.delay(
            user_id=str(user_id),
            title=title,
            body=body,
            data=data or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not queue notification for user {user_id}: {exc}")
