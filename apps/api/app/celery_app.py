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
    include=["app.tasks.example", "app.tasks.crawl", "app.tasks.scheduler"],
)

celery_app.conf.update(
    task_default_queue="rankpilot",
    task_track_started=True,
    # Concurrency 1 on the shared pilot VPS until load-tested
    # (SYSTEM_ARCHITECTURE.md #6).
    worker_concurrency=1,
)

celery_app.conf.beat_schedule = {
    "daily-crawl-all-active-websites": {
        "task": "app.tasks.scheduler.daily_crawl_all_active_websites",
        "schedule": crontab(hour=2, minute=0),
    },
    "daily-sync-search-signals": {
        "task": "app.tasks.scheduler.daily_sync_search_signals_for_all_websites",
        "schedule": crontab(hour=1, minute=30),
    },
    "daily-usage-metering": {
        "task": "app.tasks.scheduler.record_daily_usage_for_all_websites",
        "schedule": crontab(hour=4, minute=0),
    },
    "weekly-reports-monday": {
        "task": "app.tasks.scheduler.generate_weekly_reports",
        "schedule": crontab(hour=5, minute=0, day_of_week=1),
    },
    "retention-cleanup-daily": {
        "task": "app.tasks.scheduler.run_retention_cleanup",
        "schedule": crontab(hour=3, minute=0),
    },
}
