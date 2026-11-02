"""Pull Search Console data for a website and store it as
KeywordObservation rows (RP-0503, RP-0504).

GSC data is reported with a multi-day lag, so the sync window deliberately
ends a few days before "today" rather than pretending the most recent days
are complete.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.integrations import token_store
from app.integrations.google_search_console import query_search_analytics, refresh_access_token
from app.models.keyword_observation import KeywordObservation
from app.models.oauth_connection import OAuthProvider
from app.models.website import Website

REPORTING_LAG_DAYS = 3
DEFAULT_WINDOW_DAYS = 28


def sync_search_performance(
    db: Session, website: Website, *, window_days: int = DEFAULT_WINDOW_DAYS
) -> int:
    if not website.search_console_site_url:
        raise LookupError("No Search Console property is selected for this website yet.")

    access_token = token_store.get_valid_access_token(
        db, website.organization_id, OAuthProvider.google_search_console, refresh_fn=refresh_access_token
    )

    end_date = date.today() - timedelta(days=REPORTING_LAG_DAYS)
    start_date = end_date - timedelta(days=window_days)

    rows = query_search_analytics(
        access_token,
        website.search_console_site_url,
        start_date=start_date,
        end_date=end_date,
        dimensions=["query", "date"],
    )

    synced = 0
    for row in rows:
        query, date_str = row["keys"]
        observation_date = date.fromisoformat(date_str)

        existing = (
            db.query(KeywordObservation)
            .filter(
                KeywordObservation.website_id == website.id,
                KeywordObservation.query == query,
                KeywordObservation.date == observation_date,
                KeywordObservation.page_id.is_(None),
            )
            .one_or_none()
        )
        if existing is None:
            existing = KeywordObservation(
                website_id=website.id,
                query=query,
                date=observation_date,
                source="google_search_console",
            )
            db.add(existing)

        existing.clicks = int(row.get("clicks", 0))
        existing.impressions = int(row.get("impressions", 0))
        existing.ctr = float(row.get("ctr", 0.0))
        existing.average_position = float(row.get("position", 0.0))
        synced += 1

    db.flush()
    return synced
