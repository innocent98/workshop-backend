"""Withdrawal background tasks."""

from app.celery_app import celery_app
from app.core.logger import logger
from app.db.session import SessionLocal
from app.services.withdrawal_service import reconcile_processing_withdrawals


@celery_app.task(name="app.tasks.withdrawal_tasks.reconcile_withdrawals")
def reconcile_withdrawals() -> dict:
    """Hourly: settle withdrawals stuck in PROCESSING by asking Paystack for the transfer."""
    db = SessionLocal()
    try:
        summary = reconcile_processing_withdrawals(db)
        if summary["checked"]:
            logger.info(f"Withdrawal reconciliation: {summary}")
        return summary
    except Exception:
        db.rollback()
        logger.exception("reconcile_withdrawals failed")
        raise
    finally:
        db.close()
