"""Creating and back-filling immutable project snapshots.

A snapshot records the state of a project's SEO at one moment: the health score and its breakdown, how many pages
were discovered and crawled, the open issues (kept as a compact list so "what was wrong then" survives), and which
data sources were available. Nothing is defaulted: an unavailable source is recorded as "not available" with its
reason, never as zero."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deployment import crawler_user_agent
from app.history import activity
from app.history.versions import ANALYSIS_VERSION, SCORING_VERSION
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.history import ProjectMetricHistory, ProjectSnapshot, SnapshotFindings
from app.models.keyword_idea import KeywordIdea
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.site_health_score import SiteHealthScore
from app.models.website import Website
from app.models.website_connection import WebsiteConnection, WebsiteConnectionStatus

logger = logging.getLogger(__name__)

SEARCH_WINDOW_DAYS = 28


def _num(value) -> float | None:
    return None if value is None else round(float(value), 2)


def _health_block(score: SiteHealthScore | None) -> dict:
    if score is None:
        return {"available": False, "reason": "No health score was computed for this run."}
    return {
        "available": True, "overall": _num(score.overall_score), "technical": _num(score.technical_score), "on_page": _num(score.on_page_score),
        "content": _num(score.content_score), "performance": _num(score.performance_score),
        "critical": score.critical_count, "warning": score.warning_count, "info": score.info_count, "passed": score.passed_count,
    }


def _search_block(db: Session, website: Website, today: date) -> dict:
    """Google performance at snapshot time. Only real stored data; the reason is stated when there is none."""
    end = today - timedelta(days=3)
    start = end - timedelta(days=SEARCH_WINDOW_DAYS - 1)
    totals = (
        db.query(func.count(ProjectMetricHistory.id), func.sum(ProjectMetricHistory.clicks), func.sum(ProjectMetricHistory.impressions))
        .filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console",
                ProjectMetricHistory.scope_type == "property", ProjectMetricHistory.metric_date >= start, ProjectMetricHistory.metric_date <= end)
        .one()
    )
    if totals[0]:
        clicks, impressions = int(totals[1] or 0), int(totals[2] or 0)
        return {"available": True, "source": "google_search_console (property totals)", "period_start": start.isoformat(), "period_end": end.isoformat(),
                "days_with_data": int(totals[0]), "clicks": clicks, "impressions": impressions, "ctr": round(clicks / impressions, 4) if impressions else None}
    rows = db.query(func.count(KeywordObservation.id)).filter(KeywordObservation.website_id == website.id).scalar() or 0
    if rows:
        return {"available": True, "source": "google_search_console (query rows; excludes anonymised queries)", "period_start": start.isoformat(),
                "period_end": end.isoformat(), "stored_rows": int(rows)}
    if not website.search_console_site_url:
        return {"available": False, "reason": "Search Console is not connected, so there is no Google performance baseline yet. It starts when it is connected."}
    return {"available": False, "reason": "Search Console is connected but no performance data has been stored yet."}


def _ga4_block(db: Session, website: Website, today: date) -> dict:
    end = today - timedelta(days=2)
    start = end - timedelta(days=SEARCH_WINDOW_DAYS - 1)
    rows = (
        db.query(func.count(Ga4DailyMetric.id), func.sum(Ga4DailyMetric.sessions), func.sum(Ga4DailyMetric.conversions))
        .filter(Ga4DailyMetric.website_id == website.id, Ga4DailyMetric.date >= start, Ga4DailyMetric.date <= end).one()
    )
    if rows[0]:
        return {"available": True, "source": "ga4", "period_start": start.isoformat(), "period_end": end.isoformat(), "days_with_data": int(rows[0]),
                "sessions": int(rows[1] or 0), "conversions": int(rows[2] or 0)}
    if not website.ga4_property_id:
        return {"available": False, "reason": "Google Analytics is not connected."}
    return {"available": False, "reason": "Google Analytics is connected but no data has been stored yet."}


def _open_findings(db: Session, website: Website) -> list[SEOFinding]:
    return db.query(SEOFinding).filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open).all()


def findings_payload(findings: list[SEOFinding]) -> list[list]:
    return [[str(f.page_id) if f.page_id else None, f.rule_code, f.severity.value] for f in findings]


def _crawl_summary(db: Session, website: Website, crawl_job: CrawlJob, findings: list[SEOFinding], today: date) -> dict:
    score = db.query(SiteHealthScore).filter(SiteHealthScore.crawl_job_id == crawl_job.id).one_or_none()
    by_severity: dict[str, int] = {}
    by_rule: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
        by_rule[f.rule_code] = by_rule.get(f.rule_code, 0) + 1
    connectors = [c.connector_type.value for c in db.query(WebsiteConnection).filter(WebsiteConnection.website_id == website.id,
                  WebsiteConnection.status == WebsiteConnectionStatus.connected)]
    return {
        "health": _health_block(score),
        "pages": {"discovered": db.query(Page).filter(Page.website_id == website.id).count(), "requested": crawl_job.pages_requested,
                  "crawled": crawl_job.pages_fetched},
        "issues": {"open_total": len(findings), "by_severity": by_severity, "by_rule": by_rule},
        "ai_keyword_ideas": db.query(KeywordIdea).filter(KeywordIdea.website_id == website.id).count(),
        "search": _search_block(db, website, today),
        "analytics": _ga4_block(db, website, today),
        "integrations": {"google_search_console": bool(website.search_console_site_url), "ga4": bool(website.ga4_property_id), "cms": connectors},
    }


def _crawl_config(website: Website, crawl_job: CrawlJob) -> dict:
    return {"trigger": crawl_job.trigger.value, "crawl_budget": website.crawl_budget, "crawl_frequency_hours": website.crawl_frequency_hours,
            "pages_requested": crawl_job.pages_requested, "respects_robots_txt": True, "user_agent": crawler_user_agent()}


def _insert(db: Session, snapshot: ProjectSnapshot, findings_rows: list[list] | None) -> tuple[ProjectSnapshot, bool]:
    """Inserts, tolerating the two races: the same run reported twice (returns the existing row) and two projects'
    first runs finishing together (the loser simply is not the baseline)."""
    for attempt in range(2):
        try:
            with db.begin_nested():
                db.add(snapshot)
                db.flush()
                if findings_rows is not None:
                    db.add(SnapshotFindings(snapshot_id=snapshot.id, open_count=len(findings_rows), findings_json=findings_rows))
                    db.flush()
            return snapshot, True
        except IntegrityError:
            existing = db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == snapshot.website_id,
                                                        ProjectSnapshot.idempotency_key == snapshot.idempotency_key).one_or_none()
            if existing is not None:
                return existing, False
            if snapshot.is_baseline and attempt == 0:
                snapshot = ProjectSnapshot(**{c: getattr(snapshot, c) for c in (
                    "website_id", "organization_id", "snapshot_type", "status", "partial_reason", "reconstructed", "idempotency_key", "crawl_job_id",
                    "analysis_version", "scoring_version", "crawl_config", "data_sources", "period_start", "period_end", "summary_json", "created_at")},
                    is_baseline=False)
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


def has_baseline(db: Session, website_id) -> bool:
    return db.query(ProjectSnapshot.id).filter(ProjectSnapshot.website_id == website_id, ProjectSnapshot.is_baseline.is_(True)).first() is not None


def record_crawl_snapshot(db: Session, website: Website, crawl_job: CrawlJob, *, today: date | None = None) -> tuple[ProjectSnapshot | None, bool]:
    """Snapshot of a COMPLETED full crawl, after its findings and health score exist. Returns (snapshot, created).
    Post-change verification crawls only re-check one URL and are not project snapshots."""
    if crawl_job.status != CrawlStatus.completed or crawl_job.trigger == CrawlTrigger.post_change:
        return None, False
    today = today or date.today()
    findings = _open_findings(db, website)
    partial = bool(crawl_job.error_summary)
    snapshot = ProjectSnapshot(
        website_id=website.id, organization_id=website.organization_id, snapshot_type="crawl", is_baseline=not has_baseline(db, website.id),
        status="partial" if partial else "completed", partial_reason=(crawl_job.error_summary or None) if partial else None, reconstructed=False,
        idempotency_key=f"crawl:{crawl_job.id}", crawl_job_id=crawl_job.id, analysis_version=ANALYSIS_VERSION, scoring_version=SCORING_VERSION,
        crawl_config=_crawl_config(website, crawl_job), data_sources=["crawler"], summary_json=_crawl_summary(db, website, crawl_job, findings, today),
        created_at=crawl_job.completed_at or datetime.now(timezone.utc),
    )
    # the previous crawl snapshot, read BEFORE inserting this one, to describe what changed
    previous = latest_crawl_snapshot(db, website.id)
    saved, created = _insert(db, snapshot, findings_payload(findings))
    if created:
        _announce(db, website, saved, previous)
    return saved, created


def latest_crawl_snapshot(db: Session, website_id, *, with_findings: bool = False) -> ProjectSnapshot | None:
    return (db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == website_id, ProjectSnapshot.snapshot_type == "crawl")
            .order_by(ProjectSnapshot.created_at.desc(), ProjectSnapshot.id.desc()).first())


def baseline_snapshot(db: Session, website_id) -> ProjectSnapshot | None:
    return db.query(ProjectSnapshot).filter(ProjectSnapshot.website_id == website_id, ProjectSnapshot.is_baseline.is_(True)).one_or_none()


def snapshot_findings(db: Session, snapshot_id) -> set[tuple[str | None, str]] | None:
    """(page id, rule) pairs open at that snapshot, or None when the detail was not kept for it."""
    row = db.get(SnapshotFindings, snapshot_id)
    if row is None:
        return None
    return {(page_id, rule) for page_id, rule, _severity in row.findings_json}


def diff_findings(before: set | None, after: set | None) -> dict | None:
    """New and resolved issues between two snapshots; None when either side has no per-issue detail."""
    if before is None or after is None:
        return None
    return {"new": sorted(after - before, key=str), "resolved": sorted(before - after, key=str), "persisting": len(before & after)}


def _announce(db: Session, website: Website, snapshot: ProjectSnapshot, previous: ProjectSnapshot | None) -> None:
    when = snapshot.created_at
    health = snapshot.summary_json.get("health", {})
    activity.record_event(db, website, "crawl", "crawl_completed", f"Crawl completed: {snapshot.summary_json['pages']['crawled']} pages checked",
                          detail={"snapshot_id": str(snapshot.id), "crawl_job_id": str(snapshot.crawl_job_id), "partial": snapshot.status == "partial"},
                          occurred_at=when, dedupe_key=f"crawl_completed:{snapshot.crawl_job_id}")
    if snapshot.is_baseline:
        activity.record_event(db, website, "snapshot", "baseline_established", "Baseline established: where this project started",
                              detail={"snapshot_id": str(snapshot.id), "health": health.get("overall"), "open_issues": snapshot.summary_json["issues"]["open_total"]},
                              occurred_at=when, dedupe_key=f"baseline:{snapshot.id}")
    else:
        activity.record_event(db, website, "snapshot", "snapshot_created", "New SEO snapshot saved", detail={"snapshot_id": str(snapshot.id)},
                              occurred_at=when, dedupe_key=f"snapshot:{snapshot.id}")
    if previous is not None:
        change = diff_findings(snapshot_findings(db, previous.id), snapshot_findings(db, snapshot.id))
        if change and change["new"]:
            activity.record_event(db, website, "issue", "new_issues_detected", f"{len(change['new'])} new SEO issue(s) detected",
                                  detail={"snapshot_id": str(snapshot.id), "count": len(change["new"])}, occurred_at=when, dedupe_key=f"new_issues:{snapshot.id}")
        if change and change["resolved"]:
            activity.record_event(db, website, "issue", "issues_resolved", f"{len(change['resolved'])} SEO issue(s) no longer detected",
                                  detail={"snapshot_id": str(snapshot.id), "count": len(change["resolved"])}, occurred_at=when, dedupe_key=f"resolved:{snapshot.id}")


def ensure_history(db: Session, website: Website, *, today: date | None = None) -> int:
    """Back-fills snapshots for completed crawls that predate this feature (or whose hook failed), from the health
    score each one stored at the time. Per-issue detail for those runs was not kept, so they are `reconstructed` and
    `partial`; the earliest becomes the baseline. Idempotent and cheap when nothing is missing."""
    today = today or date.today()
    have = {k for (k,) in db.query(ProjectSnapshot.idempotency_key).filter(ProjectSnapshot.website_id == website.id, ProjectSnapshot.snapshot_type == "crawl")}
    crawls = (
        db.query(CrawlJob).filter(CrawlJob.website_id == website.id, CrawlJob.status == CrawlStatus.completed, CrawlJob.trigger != CrawlTrigger.post_change)
        .order_by(CrawlJob.completed_at.asc().nullslast(), CrawlJob.created_at.asc()).all()
    )
    created = 0
    for crawl in crawls:
        if f"crawl:{crawl.id}" in have:
            continue
        score = db.query(SiteHealthScore).filter(SiteHealthScore.crawl_job_id == crawl.id).one_or_none()
        if score is None:
            continue
        pages_known = crawl.pages_fetched
        summary = {
            "health": _health_block(score),
            "pages": {"discovered": None, "requested": crawl.pages_requested, "crawled": pages_known},
            "issues": {"open_total": None, "by_severity": {"critical": score.critical_count, "warning": score.warning_count, "info": score.info_count},
                       "by_rule": None, "detail": "not available: the list of issues for this run was not kept"},
            "search": {"available": False, "reason": "Performance data for this date was not recorded."},
            "analytics": {"available": False, "reason": "Performance data for this date was not recorded."},
        }
        snapshot = ProjectSnapshot(
            website_id=website.id, organization_id=website.organization_id, snapshot_type="crawl", is_baseline=not has_baseline(db, website.id),
            status="partial", partial_reason="Rebuilt from the health score stored at the time; the per-issue detail of this run was not kept.",
            reconstructed=True, idempotency_key=f"crawl:{crawl.id}", crawl_job_id=crawl.id, analysis_version="unknown", scoring_version=SCORING_VERSION,
            crawl_config=_crawl_config(website, crawl), data_sources=["crawler"], summary_json=summary, created_at=crawl.completed_at or score.created_at,
        )
        saved, was_created = _insert(db, snapshot, None)
        if was_created:
            created += 1
            have.add(snapshot.idempotency_key)
            if saved.is_baseline:
                activity.record_event(db, website, "snapshot", "baseline_established", "Baseline established: where this project started",
                                      detail={"snapshot_id": str(saved.id), "reconstructed": True}, occurred_at=saved.created_at, dedupe_key=f"baseline:{saved.id}")
    return created
