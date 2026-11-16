"""SEO improvement timeline (SEO Growth Engine spec section 9): for
each change RankPilot applied to a page, the page's Search Console
numbers in an equal window before and after. Every figure is an
aggregate of stored rows; a window with no rows is reported as None,
never as zero. A before/after difference is not proof the change
caused it.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.crawler.orchestrator import normalize_frontier_url
from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.change_record import ChangeRecord
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.ga4_landing_page_metric import Ga4LandingPageMetric
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.website import Website

ALLOWED_WINDOWS = (7, 28, 90)
MAX_CHANGES = 100
CAVEAT = (
    "Search Console data is delayed and aggregated. Seasonality, indexing delays, competitors and "
    "Google updates also move these numbers, so a difference before and after a change does not "
    "show that the change caused it."
)


def _search_stats(db: Session, website_id, page_id, start: date, end: date) -> dict | None:
    rows, clicks, impressions, position = (
        db.query(
            func.count(KeywordObservation.id),
            func.sum(KeywordObservation.clicks),
            func.sum(KeywordObservation.impressions),
            func.avg(KeywordObservation.average_position),
        )
        .filter(
            KeywordObservation.website_id == website_id,
            KeywordObservation.page_id == page_id,
            KeywordObservation.date >= start,
            KeywordObservation.date < end,
        )
        .one()
    )
    if not rows:
        return None
    clicks, impressions = int(clicks or 0), int(impressions or 0)
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "average_position": round(float(position), 1) if position is not None else None,
    }


def _ga4_stats(db: Session, website_id, start: date, end: date) -> dict | None:
    rows, sessions, conversions = (
        db.query(func.count(Ga4DailyMetric.id), func.sum(Ga4DailyMetric.sessions), func.sum(Ga4DailyMetric.conversions))
        .filter(Ga4DailyMetric.website_id == website_id, Ga4DailyMetric.date >= start, Ga4DailyMetric.date < end)
        .one()
    )
    if not rows:
        return None
    return {"sessions": int(sessions or 0), "conversions": int(conversions or 0)}


def _organic_landing_stats(db: Session, website_id, page_id, start: date, end: date) -> dict | None:
    """GA4 organic-search sessions that landed on this page. Engagement
    data from Analytics -- shown next to, never mixed into, the Search
    Console figures.
    """
    rows, sessions, engaged, conversions = (
        db.query(
            func.count(Ga4LandingPageMetric.id),
            func.sum(Ga4LandingPageMetric.sessions),
            func.sum(Ga4LandingPageMetric.engaged_sessions),
            func.sum(Ga4LandingPageMetric.conversions),
        )
        .filter(
            Ga4LandingPageMetric.website_id == website_id,
            Ga4LandingPageMetric.page_id == page_id,
            Ga4LandingPageMetric.date >= start,
            Ga4LandingPageMetric.date < end,
        )
        .one()
    )
    if not rows:
        return None
    return {"sessions": int(sessions or 0), "engaged_sessions": int(engaged or 0), "conversions": int(conversions or 0)}


def build_performance_timeline(db: Session, website: Website, *, window_days: int = 28) -> dict:
    if window_days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOWS}.")

    changes = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.website_id == website.id)
        .order_by(ChangeRecord.executed_at.desc())
        .limit(MAX_CHANGES)
        .all()
    )
    pages = db.query(Page.id, Page.canonical_url, Page.normalized_url).filter(Page.website_id == website.id).all() if changes else []
    url_by_id = {page_id: canonical for page_id, canonical, _ in pages}
    id_by_normalized_url = {normalized: page_id for page_id, _, normalized in pages}
    today = date.today()

    entries = []
    for change in changes:
        # Not every connector records the page on the change itself
        # (WordPress stores its own post id instead), so fall back to the
        # URL the task targeted.
        target_url = change.seo_task.proposed_change_json.get("target_url") if change.seo_task else None
        page_id = change.page_id
        if page_id is None and target_url:
            page_id = id_by_normalized_url.get(normalize_frontier_url(target_url))

        changed_on = change.executed_at.date()
        before_start = changed_on - timedelta(days=window_days)
        after_start = changed_on + timedelta(days=1)
        after_end = after_start + timedelta(days=window_days)

        def window(fn, start, end):
            return fn(db, website.id, page_id, start, end) if page_id is not None else None

        entries.append(
            {
                "change_id": change.id,
                "page_id": page_id,
                "page_url": url_by_id.get(page_id) or target_url,
                "operation": change.seo_task.task_type if change.seo_task else None,
                "implemented_at": change.executed_at,
                "validation_status": change.validation_status.value,
                "before": window(_search_stats, before_start, changed_on),
                "after": window(_search_stats, after_start, after_end),
                # False while Search Console has not yet reported the
                # whole "after" window -- the after numbers are partial.
                "after_window_complete": after_end + timedelta(days=REPORTING_LAG_DAYS) <= today,
                "organic_landing_before": window(_organic_landing_stats, before_start, changed_on),
                "organic_landing_after": window(_organic_landing_stats, after_start, after_end),
                "site_ga4_before": _ga4_stats(db, website.id, before_start, changed_on),
                "site_ga4_after": _ga4_stats(db, website.id, after_start, after_end),
            }
        )

    return {"window_days": window_days, "caveat": CAVEAT, "entries": entries}
