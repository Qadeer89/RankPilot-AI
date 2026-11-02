"""Pull GA4 data for a website and store it as Ga4DailyMetric rows.

GA4's standard data-freshness window is roughly the last 24-48 hours, so
(like Search Console) the sync window ends a few days before "today".
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.integrations import token_store
from app.integrations.google_analytics import refresh_access_token, run_report
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.oauth_connection import OAuthProvider
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
