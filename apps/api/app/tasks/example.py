"""Placeholder background jobs proving the worker/scheduler loop end-to-end.

Real job types (site_crawl, technical_audit, search_console_sync, ai_proposal,
etc.) land in Phase 2+ per SYSTEM_ARCHITECTURE.md #5; every one of them must
carry tenant/site scope, an idempotency key, a retry policy, and a timeout.
"""

import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.example.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="app.tasks.example.retention_cleanup")
def retention_cleanup() -> None:
    """Daily no-op placeholder for RP-0807 (retention and cleanup jobs)."""
    logger.info("retention_cleanup placeholder ran; no retention policy implemented yet")
