"""Background jobs for crawling and auditing a website
(SYSTEM_ARCHITECTURE.md #5: "site_crawl", "technical_audit").
"""

from __future__ import annotations

import logging
import uuid

from app.celery_app import celery_app
from app.crawler.orchestrator import run_crawl
from app.db.session import SessionLocal
from app.models.crawl_job import CrawlJob
from app.models.website import Website
from app.opportunities.scoring import refresh_opportunities_for_website
from app.seo_rules.engine import run_rules_for_crawl

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.crawl.run_site_crawl", bind=True, max_retries=2)
def run_site_crawl(self, website_id: str, crawl_job_id: str) -> str:
    """Run one crawl against an already-created (pending) CrawlJob row, then
    run the deterministic rule engine against what it found.

    The API layer creates the CrawlJob synchronously (so it can hand the
    caller an id immediately) and only enqueues this task to do the work.
    """
    db = SessionLocal()
    try:
        website = db.get(Website, uuid.UUID(website_id))
        crawl_job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
        if website is None or crawl_job is None:
            logger.error("run_site_crawl: website or crawl_job not found (%s, %s)", website_id, crawl_job_id)
            return "not_found"

        run_crawl(db, website, crawl_job)
        db.commit()

        run_rules_for_crawl(db, website, crawl_job)
        db.commit()

        # Folded into the same task for MVP simplicity rather than a
        # separate "opportunity_refresh" job (SYSTEM_ARCHITECTURE.md #5):
        # it's cheap, deterministic, and always needs to follow a rule run.
        refresh_opportunities_for_website(db, website)
        db.commit()
        return crawl_job.status.value
    except Exception:
        db.rollback()
        logger.exception("run_site_crawl failed for website %s", website_id)
        raise
    finally:
        db.close()
