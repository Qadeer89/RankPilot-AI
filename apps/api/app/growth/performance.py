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

from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.change_record import ChangeRecord
from app.models.ga4_daily_metric import Ga4DailyMetric
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


def build_performance_timeline(db: Session, website: Website, *, window_days: int = 28) -> dict:
    if window_days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOWS}.")

    changes = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.website_id == website.id, ChangeRecord.page_id.isnot(None))
        .order_by(ChangeRecord.executed_at.desc())
        .limit(MAX_CHANGES)
        .all()
    )
    urls = dict(db.query(Page.id, Page.canonical_url).filter(Page.website_id == website.id).all()) if changes else {}
    today = date.today()

    entries = []
    for change in changes:
        changed_on = change.executed_at.date()
        before_start = changed_on - timedelta(days=window_days)
        after_start = changed_on + timedelta(days=1)
        after_end = after_start + timedelta(days=window_days)
        entries.append(
            {
                "change_id": change.id,
                "page_id": change.page_id,
                "page_url": urls.get(change.page_id),
                "operation": change.seo_task.task_type if change.seo_task else None,
                "implemented_at": change.executed_at,
                "validation_status": change.validation_status.value,
                "before": _search_stats(db, website.id, change.page_id, before_start, changed_on),
                "after": _search_stats(db, website.id, change.page_id, after_start, after_end),
                # False while Search Console has not yet reported the
                # whole "after" window -- the after numbers are partial.
                "after_window_complete": after_end + timedelta(days=REPORTING_LAG_DAYS) <= today,
                "site_ga4_before": _ga4_stats(db, website.id, before_start, changed_on),
                "site_ga4_after": _ga4_stats(db, website.id, after_start, after_end),
            }
        )

    return {"window_days": window_days, "caveat": CAVEAT, "entries": entries}
