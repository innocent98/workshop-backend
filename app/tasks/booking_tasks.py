"""Booking lifecycle background tasks."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.core.logger import logger
from app.db.models.booking import Booking, BookingStatus
from app.db.models.booking_progress_log import BookingProgressLog
from app.db.session import SessionLocal
from app.services.notify import notify_user

AUTO_CONFIRM_LOG_NOTE = (
    "Completion automatically confirmed: the client did not confirm or dispute "
    "within the dispute window."
)
BATCH_SIZE = 200


def auto_confirm_due_bookings(db: Session, now: Optional[datetime] = None) -> int:
    """
    Confirm COMPLETED bookings whose dispute window has elapsed with no client response.

    Idempotent: only bookings that are COMPLETED, unconfirmed and undisputed are touched,
    and each one is confirmed exactly once (rows are claimed with FOR UPDATE SKIP LOCKED,
    so overlapping runs never process the same booking twice).
    The automatic nature is recorded as a BookingProgressLog entry.
    Returns the number of bookings confirmed.
    """
    now = now or datetime.now(timezone.utc)
    confirmed_total = 0

    while True:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.status == BookingStatus.COMPLETED,
                Booking.completion_confirmed_by_client_at.is_(None),
                Booking.completion_disputed_at.is_(None),
                Booking.completion_confirmation_deadline_at.is_not(None),
                Booking.completion_confirmation_deadline_at <= now,
            )
            .order_by(Booking.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .all()
        )
        if not bookings:
            break

        notifications = []
        for booking in bookings:
            booking.completion_confirmed_by_client_at = now
            db.add(
                BookingProgressLog(
                    booking_id=booking.id,
                    artisan_id=booking.artisan_id,
                    description=AUTO_CONFIRM_LOG_NOTE,
                )
            )
            notifications.append((booking.id, booking.artisan_id, booking.customer_id))
        db.commit()
        confirmed_total += len(bookings)

        for booking_id, artisan_id, customer_id in notifications:
            data = {"booking_id": str(booking_id), "event": "completion_auto_confirmed"}
            notify_user(
                artisan_id,
                "Completion confirmed",
                "The client did not respond within the dispute window, so the job was "
                "automatically confirmed. Your earnings are now available to withdraw.",
                data,
            )
            notify_user(
                customer_id,
                "Job automatically confirmed",
                "The dispute window for your completed job has ended, so it was "
                "automatically confirmed.",
                data,
            )

    return confirmed_total


@celery_app.task(name="app.tasks.booking_tasks.auto_confirm_completed_bookings")
def auto_confirm_completed_bookings() -> dict:
    """Hourly beat task: auto-confirm completed bookings past their dispute window."""
    db = SessionLocal()
    try:
        count = auto_confirm_due_bookings(db)
        if count:
            logger.info(f"Auto-confirmed {count} completed booking(s)")
        return {"status": "success", "confirmed": count}
    except Exception:
        db.rollback()
        logger.exception("auto_confirm_completed_bookings failed")
        raise
    finally:
        db.close()
