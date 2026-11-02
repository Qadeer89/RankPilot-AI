"""Weekly activity report generation (RP-0805).

Summarizes what happened — crawls, findings, opportunities, executed
changes, and (when connected) Search Console trends — over the last
7 days. Never attributes a search-performance change to a specific
RankPilot action without a longer observation window
(QA_TEST_STRATEGY.md #5): this report states what happened, not what
caused what.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.change_record import ChangeRecord, ValidationStatus
from app.models.crawl_job import CrawlJob
from app.models.keyword_observation import KeywordObservation
from app.models.report import Report, ReportType
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website

DEFAULT_PERIOD_DAYS = 7


def generate_weekly_report(db: Session, website: Website, *, period_end: date | None = None) -> Report:
    period_end = period_end or date.today()
    period_start = period_end - timedelta(days=DEFAULT_PERIOD_DAYS)
    start_dt = datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc)
    end_dt = datetime(period_end.year, period_end.month, period_end.day, tzinfo=timezone.utc) + timedelta(days=1)

    crawl_jobs = (
        db.query(CrawlJob)
        .filter(CrawlJob.website_id == website.id, CrawlJob.created_at >= start_dt, CrawlJob.created_at < end_dt)
        .all()
    )

    findings_opened = (
        db.query(func.count(SEOFinding.id))
        .filter(
            SEOFinding.website_id == website.id,
            SEOFinding.first_detected_at >= start_dt,
            SEOFinding.first_detected_at < end_dt,
        )
        .scalar()
    )
    findings_open_now = (
        db.query(func.count(SEOFinding.id))
        .filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open)
        .scalar()
    )

    opportunities_open_now = (
        db.query(func.count(SEOOpportunity.id))
        .filter(SEOOpportunity.website_id == website.id, SEOOpportunity.status == OpportunityStatus.open)
        .scalar()
    )

    changes = (
        db.query(ChangeRecord)
        .filter(
            ChangeRecord.website_id == website.id,
            ChangeRecord.executed_at >= start_dt,
            ChangeRecord.executed_at < end_dt,
        )
        .all()
    )
    changes_passed = sum(1 for c in changes if c.validation_status == ValidationStatus.passed)
    changes_failed = sum(1 for c in changes if c.validation_status == ValidationStatus.failed)

    search_performance = None
    if website.search_console_site_url:
        totals = (
            db.query(
                func.coalesce(func.sum(KeywordObservation.clicks), 0),
                func.coalesce(func.sum(KeywordObservation.impressions), 0),
            )
            .filter(
                KeywordObservation.website_id == website.id,
                KeywordObservation.date >= period_start,
                KeywordObservation.date <= period_end,
            )
            .one()
        )
        search_performance = {"clicks": int(totals[0]), "impressions": int(totals[1])}

    content = {
        "crawls": {
            "count": len(crawl_jobs),
            "pages_fetched_total": sum(j.pages_fetched for j in crawl_jobs),
        },
        "findings": {
            "opened_this_period": findings_opened or 0,
            "open_now": findings_open_now or 0,
        },
        "opportunities": {"open_now": opportunities_open_now or 0},
        "changes": {
            "executed": len(changes),
            "passed_validation": changes_passed,
            "failed_validation": changes_failed,
        },
        "search_performance": search_performance,
        "disclaimer": (
            "Search performance figures are delayed/aggregated Search Console data and are "
            "not attributed to any specific change in this report."
        ),
    }

    report = Report(
        organization_id=website.organization_id,
        website_id=website.id,
        period_start=period_start,
        period_end=period_end,
        report_type=ReportType.weekly,
        content_json=content,
    )
    db.add(report)
    db.flush()
    return report
