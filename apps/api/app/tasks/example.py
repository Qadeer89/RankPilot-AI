"""A minimal task proving the worker/broker loop is wired up end to end.
See app/tasks/crawl.py and app/tasks/scheduler.py for the real jobs
(site_crawl, technical_audit, daily scheduling, reporting, usage
metering, retention) per SYSTEM_ARCHITECTURE.md #5.
"""

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.example.ping")
def ping() -> str:
    return "pong"
