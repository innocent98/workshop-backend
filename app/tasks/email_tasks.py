"""
Email-related background tasks using Celery.
"""
from datetime import datetime, timezone
from typing import Dict, Any
from celery import shared_task
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.logger import logger
from app.db.session import SessionLocal
from app.db.models.otp import OTP
from app.utils.email import (
    send_otp_email as sync_send_otp_email,
    send_password_reset_email as sync_send_password_reset_email,
    send_welcome_email as sync_send_welcome_email,
)


@celery_app.task(name="app.tasks.email_tasks.send_otp_email", bind=True, max_retries=3)
def send_otp_email(
    self,
    email: str,
    otp_code: str,
    purpose: str = "verification"
) -> Dict[str, Any]:
    """
    Send OTP email asynchronously.

    Args:
        email: Recipient email address
        otp_code: 6-digit OTP code
        purpose: Purpose of OTP (verification or password_reset)

    Returns:
        Dict with status and message
    """
    try:
        logger.info(f"Sending OTP email to {email} for {purpose}")
        result = sync_send_otp_email(email, otp_code, purpose)

        if result:
            logger.info(f"OTP email sent successfully to {email}")
            return {"status": "success", "email": email, "purpose": purpose}
        else:
            logger.error(f"Failed to send OTP email to {email}")
            raise Exception(f"Failed to send OTP email to {email}")

    except Exception as exc:
        logger.error(f"Error sending OTP email to {email}: {str(exc)}")
        # Retry with exponential backoff: 60s, 120s, 180s
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(name="app.tasks.email_tasks.send_password_reset_email", bind=True, max_retries=3)
def send_password_reset_email(
    self,
    email: str,
    reset_token: str
) -> Dict[str, Any]:
    """
    Send password reset email asynchronously.

    Args:
        email: Recipient email address
        reset_token: Password reset token

    Returns:
        Dict with status and message
    """
    try:
        logger.info(f"Sending password reset email to {email}")
        result = sync_send_password_reset_email(email, reset_token)

        if result:
            logger.info(f"Password reset email sent successfully to {email}")
            return {"status": "success", "email": email}
        else:
            logger.error(f"Failed to send password reset email to {email}")
            raise Exception(f"Failed to send password reset email to {email}")

    except Exception as exc:
        logger.error(f"Error sending password reset email to {email}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(name="app.tasks.email_tasks.send_welcome_email", bind=True, max_retries=3)
def send_welcome_email(
    self,
    email: str,
    full_name: str
) -> Dict[str, Any]:
    """
    Send welcome email asynchronously.

    Args:
        email: Recipient email address
        full_name: User's full name

    Returns:
        Dict with status and message
    """
    try:
        logger.info(f"Sending welcome email to {email}")
        result = sync_send_welcome_email(email, full_name)

        if result:
            logger.info(f"Welcome email sent successfully to {email}")
            return {"status": "success", "email": email}
        else:
            logger.error(f"Failed to send welcome email to {email}")
            raise Exception(f"Failed to send welcome email to {email}")

    except Exception as exc:
        logger.error(f"Error sending welcome email to {email}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(name="app.tasks.email_tasks.cleanup_expired_otps")
def cleanup_expired_otps() -> Dict[str, Any]:
    """
    Periodic task to clean up expired OTPs from the database.
    Runs every hour via Celery Beat.

    Returns:
        Dict with count of deleted OTPs
    """
    try:
        logger.info("Starting cleanup of expired OTPs")
        db: Session = SessionLocal()

        # Find and delete expired OTPs
        now = datetime.now(timezone.utc)
        expired_otps = db.query(OTP).filter(OTP.expires_at < now).all()
        count = len(expired_otps)

        for otp in expired_otps:
            db.delete(otp)

        db.commit()
        db.close()

        logger.info(f"Cleaned up {count} expired OTPs")
        return {"status": "success", "deleted_count": count}

    except Exception as exc:
        logger.error(f"Error cleaning up expired OTPs: {str(exc)}")
        if db:
            db.rollback()
            db.close()
        return {"status": "error", "message": str(exc)}
