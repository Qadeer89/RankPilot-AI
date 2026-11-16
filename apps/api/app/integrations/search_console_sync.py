"""Pull Search Console data for a website and store it as
KeywordObservation rows (RP-0503, RP-0504).

GSC data is reported with a multi-day lag, so the sync window deliberately
ends a few days before "today" rather than pretending the most recent days
are complete.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.countries import UNKNOWN_COUNTRY, normalize_country
from app.crawler.orchestrator import normalize_frontier_url
from app.integrations import token_store
from app.integrations.google_search_console import query_search_analytics, refresh_access_token
from app.models.keyword_observation import KeywordObservation
from app.models.oauth_connection import OAuthProvider
from app.models.page import Page
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

    # "page" is included so each observation can be attributed to a
    # crawled Page (page_id below) -- without it, a downstream opportunity
    # derived from this data (app/opportunities/search_console_signals.py)
    # has no page to hand the AI content agent for a title/meta fix.
    # "country"/"device" support the SEO Growth Engine's country-based
    # intelligence (never fabricated -- exactly what GSC itself reports).
    rows = query_search_analytics(
        access_token,
        website.search_console_site_url,
        start_date=start_date,
        end_date=end_date,
        dimensions=["query", "page", "date", "country", "device"],
    )

    pages_by_normalized_url = {
        p.normalized_url: p.id for p in db.query(Page).filter(Page.website_id == website.id).all()
    }

    # Normalize Search Console's country codes to the internal form, then
    # merge any rows that land on the same identity (several codes
    # Search Console cannot place all become the "unknown region" bucket).
    merged: dict[tuple, dict] = {}
    for row in rows:
        query, page_url, date_str, raw_country, device = row["keys"]
        key = (
            query,
            pages_by_normalized_url.get(normalize_frontier_url(page_url)),
            date.fromisoformat(date_str),
            normalize_country(raw_country) or UNKNOWN_COUNTRY,
            device,
        )
        clicks = int(row.get("clicks", 0))
        impressions = int(row.get("impressions", 0))
        position = float(row.get("position", 0.0))
        bucket = merged.setdefault(key, {"clicks": 0, "impressions": 0, "weighted_position": 0.0, "rows": 0, "position_sum": 0.0})
        bucket["clicks"] += clicks
        bucket["impressions"] += impressions
        bucket["weighted_position"] += position * impressions
        bucket["position_sum"] += position
        bucket["rows"] += 1

    synced = 0
    for (query, page_id, observation_date, country, device), totals in merged.items():
        page_filter = (
            KeywordObservation.page_id.is_(None) if page_id is None else KeywordObservation.page_id == page_id
        )
        existing = (
            db.query(KeywordObservation)
            .filter(
                KeywordObservation.website_id == website.id,
                KeywordObservation.query == query,
                KeywordObservation.date == observation_date,
                KeywordObservation.country == country,
                KeywordObservation.device == device,
                page_filter,
            )
            .one_or_none()
        )
        if existing is None:
            existing = KeywordObservation(
                website_id=website.id,
                query=query,
                page_id=page_id,
                date=observation_date,
                country=country,
                device=device,
                source="google_search_console",
            )
            db.add(existing)

        impressions = totals["impressions"]
        existing.clicks = totals["clicks"]
        existing.impressions = impressions
        existing.ctr = (totals["clicks"] / impressions) if impressions else 0.0
        existing.average_position = (
            totals["weighted_position"] / impressions if impressions else totals["position_sum"] / totals["rows"]
        )
        synced += 1

    db.flush()
    return synced
