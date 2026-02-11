from __future__ import annotations

from typing import Dict, Optional

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import settings
from app.core.logger import logger


_firebase_initialized = False


def _init_firebase() -> bool:
    global _firebase_initialized
    if _firebase_initialized:
        return True

    if not settings.FCM_ENABLED:
        logger.warning("FCM is disabled via configuration")
        return False

    if not settings.FCM_SERVICE_ACCOUNT_FILE:
        logger.warning("FCM service account file is not configured")
        return False

    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(settings.FCM_SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        return True
    except Exception as exc:
        logger.error(f"Failed to initialize Firebase Admin SDK: {exc}")
        return False


def send_to_token(
    *,
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
) -> bool:
    if not _init_firebase():
        return False

    payload = {str(k): str(v) for k, v in (data or {}).items()}
    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data=payload,
    )

    try:
        messaging.send(message)
        return True
    except Exception as exc:
        logger.warning(f"Failed to send FCM to token: {exc}")
        return False
