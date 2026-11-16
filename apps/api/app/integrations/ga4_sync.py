"""Pull GA4 data for a website and store it as Ga4DailyMetric rows.

GA4's standard data-freshness window is roughly the last 24-48 hours, so
(like Search Console) the sync window ends a few days before "today".
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urljoin

from sqlalchemy.orm import Session

from app.integrations import token_store
from app.crawler.orchestrator import normalize_frontier_url
from app.integrations.google_analytics import refresh_access_token, run_landing_page_report, run_report
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.ga4_landing_page_metric import Ga4LandingPageMetric
from app.models.oauth_connection import OAuthProvider
from app.models.page import Page
from app.models.website import Website

REPORTING_LAG_DAYS = 2
DEFAULT_WINDOW_DAYS = 28


def sync_ga4_metrics(db: Session, website: Website, *, window_days: int = DEFAULT_WINDOW_DAYS) -> int:
    if not website.ga4_property_id:
        raise LookupError("No GA4 property is selected for this website yet.")

    access_token = token_store.get_valid_access_token(
        db, website.organization_id, OAuthProvider.google_analytics, refresh_fn=refresh_access_token
    )

    end_date = date.today() - timedelta(days=REPORTING_LAG_DAYS)
    start_date = end_date - timedelta(days=window_days)

    rows = run_report(access_token, website.ga4_property_id, start_date=start_date, end_date=end_date)

    synced = 0
    for row in rows:
        (date_str,) = row["dimension_values"]
        sessions_str, users_str, conversions_str = row["metric_values"]
        # GA4 returns the date dimension as "YYYYMMDD" (ISO 8601 basic
        # format), which date.fromisoformat() has accepted since Python 3.11.
        observation_date = date.fromisoformat(date_str)

        existing = (
            db.query(Ga4DailyMetric)
            .filter(Ga4DailyMetric.website_id == website.id, Ga4DailyMetric.date == observation_date)
            .one_or_none()
        )
        if existing is None:
            existing = Ga4DailyMetric(website_id=website.id, date=observation_date)
            db.add(existing)

        existing.sessions = int(float(sessions_str))
        existing.total_users = int(float(users_str))
        existing.conversions = int(float(conversions_str))
        synced += 1

    db.flush()
    return synced


def sync_ga4_landing_pages(db: Session, website: Website, *, window_days: int = DEFAULT_WINDOW_DAYS) -> int:
    """Organic-search sessions per landing page, linked to the crawled
    Page whose URL matches the landing path. A path with no matching
    page is still stored, with page_id left empty.
    """
    if not website.ga4_property_id:
        raise LookupError("No GA4 property is selected for this website yet.")

    access_token = token_store.get_valid_access_token(
        db, website.organization_id, OAuthProvider.google_analytics, refresh_fn=refresh_access_token
    )
    end_date = date.today() - timedelta(days=REPORTING_LAG_DAYS)
    start_date = end_date - timedelta(days=window_days)
    rows = run_landing_page_report(access_token, website.ga4_property_id, start_date=start_date, end_date=end_date)

    pages_by_url = {p.normalized_url: p.id for p in db.query(Page).filter(Page.website_id == website.id).all()}

    # GA4 separates the same path by query string; merge those per day.
    merged: dict[tuple[str, date], list[int]] = {}
    for row in rows:
        date_str, landing = row["dimension_values"]
        if not landing.startswith("/"):
            continue  # "(not set)" and similar placeholders
        path = landing.split("?", 1)[0]
        totals = merged.setdefault((path, date.fromisoformat(date_str)), [0, 0, 0])
        for index, value in enumerate(row["metric_values"]):
            totals[index] += int(float(value))

    for (path, observation_date), (sessions, engaged, conversions) in merged.items():
        existing = (
            db.query(Ga4LandingPageMetric)
            .filter(
                Ga4LandingPageMetric.website_id == website.id,
                Ga4LandingPageMetric.landing_page == path,
                Ga4LandingPageMetric.date == observation_date,
            )
            .one_or_none()
        )
        if existing is None:
            existing = Ga4LandingPageMetric(website_id=website.id, landing_page=path, date=observation_date)
            db.add(existing)
        existing.page_id = pages_by_url.get(normalize_frontier_url(urljoin(website.canonical_url, path)))
        existing.sessions = sessions
        existing.engaged_sessions = engaged
        existing.conversions = conversions

    db.flush()
    return len(merged)
