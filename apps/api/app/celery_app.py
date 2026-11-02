"""Celery application shared by the `rankpilot-worker` and `rankpilot-scheduler`
PM2 processes (SYSTEM_ARCHITECTURE.md #7). Run as:

    celery -A app.celery_app worker --concurrency 1
    celery -A app.celery_app beat
"""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "rankpilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.example"],
)

celery_app.conf.update(
    task_default_queue="rankpilot",
    task_track_started=True,
    # Concurrency 1 on the shared pilot VPS until load-tested
    # (SYSTEM_ARCHITECTURE.md #6).
    worker_concurrency=1,
)

celery_app.conf.beat_schedule = {
    "retention-cleanup-daily": {
        "task": "app.tasks.example.retention_cleanup",
        "schedule": crontab(hour=3, minute=0),
    },
}
