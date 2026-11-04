"""Daily/weekly scheduled jobs (RP-0801, SYSTEM_ARCHITECTURE.md #5).

Each task opens its own DB session and commits per-website, so one
website's failure doesn't roll back work already done for others in the
same run.
"""

from __future__ import annotations

import logging

from app.celery_app import celery_app
from app.crawler.orchestrator import CrawlTrigger, create_crawl_job
from app.db.session import SessionLocal
from app.integrations.ga4_sync import sync_ga4_metrics
from app.integrations.search_console_sync import sync_search_performance
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.opportunities.search_console_signals import refresh_ctr_opportunities
from app.reporting.weekly_report import generate_weekly_report
from app.tasks.retention import cleanup_old_data
from app.usage.metering import record_daily_usage

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.scheduler.daily_crawl_all_active_websites")
def daily_crawl_all_active_websites() -> int:
    """RP-0801/RP-0802: enqueue a scheduled crawl for every verified,
    active website. Each crawl still runs through the same crawl_budget
    and risk-tier gates as a manual crawl — a daily schedule means daily
    checks, not forced daily changes (SYSTEM_ARCHITECTURE.md #9).
    """
    from app.tasks.crawl import run_site_crawl

    db = SessionLocal()
    enqueued = 0
    try:
        websites = (
            db.query(Website)
            .filter(Website.status == WebsiteStatus.active, Website.verification_status == VerificationStatus.verified)
            .all()
        )
        for website in websites:
            try:
                crawl_job = create_crawl_job(db, website, trigger=CrawlTrigger.scheduled)
                db.commit()
            except Exception:
                logger.exception("Failed to create scheduled crawl job for website %s", website.id)
                db.rollback()
                continue
            run_site_crawl.delay(str(website.id), str(crawl_job.id))
            enqueued += 1
        return enqueued
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.daily_sync_search_signals_for_all_websites")
def daily_sync_search_signals_for_all_websites() -> int:
    """Pull fresh Search Console / GA4 data for every connected website
    and re-derive CTR opportunities from it (app/opportunities/
    search_console_signals.py), so "well-ranked but nobody clicks"
    queries surface on their own instead of only after someone manually
    hits Sync now.
    """
    db = SessionLocal()
    synced = 0
    try:
        websites = db.query(Website).filter(Website.status != WebsiteStatus.deleted).all()
        for website in websites:
            if website.search_console_site_url:
                try:
                    sync_search_performance(db, website)
                    refresh_ctr_opportunities(db, website)
                    db.commit()
                    synced += 1
                except Exception:
                    logger.exception("Failed to sync Search Console data for website %s", website.id)
                    db.rollback()
            if website.ga4_property_id:
                try:
                    sync_ga4_metrics(db, website)
                    db.commit()
                except Exception:
                    logger.exception("Failed to sync GA4 data for website %s", website.id)
                    db.rollback()
        return synced
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.generate_weekly_reports")
def generate_weekly_reports() -> int:
    """RP-0805: one report per active website. Does not email by itself —
    pair with a notification call once report delivery preferences exist
    per-organization (not yet modeled)."""
    db = SessionLocal()
    generated = 0
    try:
        websites = db.query(Website).filter(Website.status != WebsiteStatus.deleted).all()
        for website in websites:
            try:
                generate_weekly_report(db, website)
                db.commit()
                generated += 1
            except Exception:
                logger.exception("Failed to generate weekly report for website %s", website.id)
                db.rollback()
        return generated
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.record_daily_usage_for_all_websites")
def record_daily_usage_for_all_websites() -> int:
    """RP-0806."""
    db = SessionLocal()
    recorded = 0
    try:
        websites = db.query(Website).filter(Website.status != WebsiteStatus.deleted).all()
        for website in websites:
            try:
                record_daily_usage(db, website)
                db.commit()
                recorded += 1
            except Exception:
                logger.exception("Failed to record usage for website %s", website.id)
                db.rollback()
        return recorded
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.run_retention_cleanup")
def run_retention_cleanup() -> dict[str, int]:
    """RP-0807."""
    db = SessionLocal()
    try:
        result = cleanup_old_data(db)
        db.commit()
        return result
    except Exception:
        logger.exception("Retention cleanup failed")
        db.rollback()
        raise
    finally:
        db.close()
