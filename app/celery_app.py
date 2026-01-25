"""
Celery application instance and configuration.
"""
from celery import Celery
from app.core.config import settings

# Create Celery instance
celery_app = Celery(
    "workchop",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.email_tasks",
        "app.tasks.notification_tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    task_soft_time_limit=270,  # 4.5 minutes
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result backend settings
    result_expires=3600,  # 1 hour
    result_backend_transport_options={"master_name": "mymaster"},
)

# Optional: Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    # Example: Clean up expired OTPs every hour
    "cleanup-expired-otps": {
        "task": "app.tasks.email_tasks.cleanup_expired_otps",
        "schedule": 3600.0,  # Every hour
    },
}
