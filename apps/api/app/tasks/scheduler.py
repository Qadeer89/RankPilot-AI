"""Daily/weekly scheduled jobs (RP-0801, SYSTEM_ARCHITECTURE.md #5).

Each task opens its own DB session and commits per-website, so one
website's failure doesn't roll back work already done for others in the
same run.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.celery_app import celery_app
from app.connectors import github_pr
from app.connectors.errors import ConnectorError
from app.billing.entitlement import allowed as billing_allowed
from app.crawler.orchestrator import CrawlTrigger, create_crawl_job
from app.db.session import SessionLocal
from app.config import get_settings
from app.execution.connections import get_github_credentials
from app.integrations.ga4_sync import sync_ga4_landing_pages, sync_ga4_metrics
from app.integrations.performance_sync import sync_performance_metrics
from app.integrations.search_console_sync import sync_search_performance
from app.integrations.url_inspection_sync import sync_url_inspection_status
from app.models.change_record import ChangeRecord
from app.models.crawl_job import CrawlJob, CrawlStatus
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.models.website_connection import ConnectorType, WebsiteConnection, WebsiteConnectionStatus
from app.opportunities.search_console_signals import refresh_ctr_opportunities
from app.reporting.weekly_report import generate_weekly_report
from app.tasks.retention import cleanup_old_data
from app.usage.metering import record_daily_usage

logger = logging.getLogger(__name__)


_ACTIVE_CRAWL_STATUSES = (CrawlStatus.pending, CrawlStatus.running)


@celery_app.task(name="app.tasks.scheduler.daily_crawl_all_active_websites")
def daily_crawl_all_active_websites() -> int:
    """Enqueue a scheduled crawl for every verified, active website whose
    own crawl_frequency_hours has actually elapsed since its last crawl
    (RankPilot AI Phase 8 "User Controls" -- configure crawl frequency;
    RP-0801/RP-0802's original one-fixed-cadence-for-everyone behavior).
    This task itself now runs hourly (celery_app.py's beat schedule) so a
    website configured for e.g. every 6 hours is actually checked on that
    cadence, not just once a day regardless of what it's set to. Each
    crawl still runs through the same crawl_budget and risk-tier gates as
    a manual crawl — a schedule means regular checks, not forced changes
    (SYSTEM_ARCHITECTURE.md #9).
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
        now = datetime.now(timezone.utc)
        for website in websites:
            if not billing_allowed(db, website, "scheduled_crawl"):
                continue
            last_crawl = (
                db.query(CrawlJob)
                .filter(CrawlJob.website_id == website.id, CrawlJob.trigger != CrawlTrigger.post_change)
                .order_by(CrawlJob.created_at.desc())
                .first()
            )
            if last_crawl is not None:
                if last_crawl.status in _ACTIVE_CRAWL_STATUSES:
                    continue
                reference_time = last_crawl.started_at or last_crawl.created_at
                if now - reference_time < timedelta(hours=website.crawl_frequency_hours):
                    continue

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
            if not billing_allowed(db, website, "scheduled_sync"):
                continue
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
                try:
                    sync_ga4_landing_pages(db, website)
                    db.commit()
                except Exception:
                    logger.exception("Failed to sync GA4 landing pages for website %s", website.id)
                    db.rollback()
        return synced
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.daily_sync_performance_metrics_for_all_websites")
def daily_sync_performance_metrics_for_all_websites() -> int:
    """Pull fresh Core Web Vitals (PageSpeed Insights) for every active,
    verified website's pages. A no-op across the board when
    RANKPILOT_PAGESPEED_API_KEY isn't configured -- performance_score
    then simply stays unmeasured, never a crash.
    """
    settings = get_settings()
    if not settings.pagespeed_api_key:
        return 0

    db = SessionLocal()
    synced = 0
    try:
        websites = (
            db.query(Website)
            .filter(Website.status == WebsiteStatus.active, Website.verification_status == VerificationStatus.verified)
            .all()
        )
        for website in websites:
            if not billing_allowed(db, website, "scheduled_sync"):
                continue
            try:
                sync_performance_metrics(db, website)
                db.commit()
                synced += 1
            except Exception:
                logger.exception("Failed to sync performance metrics for website %s", website.id)
                db.rollback()
        return synced
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.daily_sync_url_inspection_for_all_websites")
def daily_sync_url_inspection_for_all_websites() -> int:
    """Pull Google's own indexing view (URL Inspection API) for every
    website with a connected Search Console property. Reuses the same
    OAuth connection as daily_sync_search_signals_for_all_websites --
    no separate consent, no separate config flag; this is simply a
    no-op for a website with no Search Console property selected.
    """
    db = SessionLocal()
    synced = 0
    try:
        websites = (
            db.query(Website)
            .filter(Website.status == WebsiteStatus.active, Website.verification_status == VerificationStatus.verified)
            .all()
        )
        for website in websites:
            if not billing_allowed(db, website, "scheduled_sync"):
                continue
            if not website.search_console_site_url:
                continue
            try:
                sync_url_inspection_status(db, website)
                db.commit()
                synced += 1
            except Exception:
                logger.exception("Failed to sync URL inspection status for website %s", website.id)
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
            if not billing_allowed(db, website, "report"):
                continue
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


# How far back to keep re-checking an open PR before giving up on it --
# bounds the query below without needing a separate "gave up" flag; a
# human can always merge it manually, this just stops polling it.
_AUTO_MERGE_POLL_WINDOW = timedelta(days=7)


@celery_app.task(name="app.tasks.scheduler.poll_and_merge_github_prs")
def poll_and_merge_github_prs() -> int:
    """For websites that opted into GitHub "auto-merge on CI success"
    (PATCH .../connections/github/settings, config_json
    `auto_merge_on_ci_success`), re-checks each still-open
    RankPilot-authored PR's live CI status and merges it once CI
    reports a clean `"success"` -- never on `"failure"`, `"pending"`, or
    `"no_checks"` (a repo with no CI configured at all stays manually
    reviewed; see `github_pr.get_combined_status`'s docstring, which
    this task is the "scheduled re-check" it describes). A website
    without the opt-in is untouched no matter how long its PRs sit
    open.
    """
    db = SessionLocal()
    merged = 0
    try:
        cutoff = datetime.now(timezone.utc) - _AUTO_MERGE_POLL_WINDOW
        candidates = (
            db.query(ChangeRecord)
            .filter(
                ChangeRecord.connector_type == ConnectorType.github,
                ChangeRecord.auto_merged_at.is_(None),
                ChangeRecord.executed_at >= cutoff,
            )
            .all()
        )
        for record in candidates:
            pr_info = (record.after_state_json or {}).get("apply_result") or {}
            pr_number = pr_info.get("pr_number")
            if pr_number is None:
                continue

            website = db.get(Website, record.website_id)
            if website is None:
                continue

            connection = (
                db.query(WebsiteConnection)
                .filter(
                    WebsiteConnection.website_id == website.id,
                    WebsiteConnection.connector_type == ConnectorType.github,
                    WebsiteConnection.status == WebsiteConnectionStatus.connected,
                )
                .one_or_none()
            )
            if connection is None or not connection.config_json.get("auto_merge_on_ci_success"):
                continue

            try:
                credentials = get_github_credentials(db, website)
                pull_request = github_pr.get_pull_request(credentials, pr_number)
                if pull_request.get("state") != "open":
                    # Already merged (by a human, or an earlier run of
                    # this task) or closed outright -- either way,
                    # nothing left for this task to do; stop polling it.
                    if pull_request.get("merged"):
                        record.auto_merged_at = datetime.now(timezone.utc)
                        db.commit()
                    continue

                ci_status = github_pr.get_combined_status(credentials, pull_request["head"]["ref"])
                if ci_status != "success":
                    continue

                github_pr.merge_pull_request(credentials, pr_number)
                record.auto_merged_at = datetime.now(timezone.utc)
                db.commit()
                merged += 1
            except (ConnectorError, LookupError):
                logger.exception(
                    "Auto-merge check failed for change_record %s (PR #%s)", record.id, pr_number
                )
                db.rollback()
        return merged
    finally:
        db.close()


@celery_app.task(name="app.tasks.scheduler.run_billing_maintenance")
def run_billing_maintenance() -> dict[str, int]:
    """Hourly: expire finished subscriptions, remind about ending trials, retry events that were waiting for
    another event, and reconcile with the payment provider. Each step is independent and idempotent."""
    from app.billing import jobs

    db = SessionLocal()
    summary: dict[str, int] = {}
    try:
        for name, step in (
            ("expired", lambda: jobs.expire_finished(db)),
            ("trial_reminders", lambda: jobs.send_trial_reminders(db)),
            ("events_retried", lambda: jobs.retry_failed_events(db)),
        ):
            try:
                summary[name] = step()
            except Exception:
                logger.exception("billing maintenance step %s failed", name)
                db.rollback()
        try:
            summary.update({f"reconcile_{k}": v for k, v in jobs.reconcile_subscriptions(db).items()})
        except Exception:
            logger.exception("billing reconciliation failed")
            db.rollback()
        return summary
    finally:
        db.close()
