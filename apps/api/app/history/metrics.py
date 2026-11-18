"""Daily Search Console totals, kept as their own time series with their provenance.

The first run back-fills whatever history Google makes available (about 16 months) and marks those days
"imported". Every later run collects recent days and marks new days "collected". A day Google has no data for is
simply absent: it is never stored as zero."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.countries import UNKNOWN_COUNTRY, normalize_country
from app.history import activity
from app.history.sync_log import SyncRun
from app.integrations import token_store
from app.integrations.google_search_console import query_search_analytics_paged, refresh_access_token
from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.history import ProjectMetricHistory
from app.models.oauth_connection import OAuthProvider
from app.models.website import Website

logger = logging.getLogger(__name__)

SOURCE = "google_search_console"
BACKFILL_DAYS = 480  # a little over Search Console's 16 months
REFRESH_DAYS = 14
DIMENSION_SETS = (("date",), ("date", "country"), ("date", "device"))


def _scope(dimensions: tuple[str, ...], keys: list[str]) -> tuple[str, str]:
    if dimensions == ("date",):
        return "property", ""
    if dimensions[1] == "country":
        return "country", normalize_country(keys[1]) or UNKNOWN_COUNTRY
    return "device", (keys[1] or "").upper()


def _merge(rows: list[dict], dimensions: tuple[str, ...]) -> dict[tuple, dict]:
    """Several raw country codes can normalise to the same value; merge them (position weighted by impressions)."""
    merged: dict[tuple, dict] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "weighted": 0.0, "position_sum": 0.0, "n": 0})
    for row in rows:
        keys = row["keys"]
        scope_type, scope_value = _scope(dimensions, keys)
        bucket = merged[(scope_type, scope_value, date.fromisoformat(keys[0]))]
        impressions = int(row.get("impressions", 0))
        bucket["clicks"] += int(row.get("clicks", 0))
        bucket["impressions"] += impressions
        bucket["weighted"] += float(row.get("position", 0.0)) * impressions
        bucket["position_sum"] += float(row.get("position", 0.0))
        bucket["n"] += 1
    return merged


def sync_search_history(db: Session, website: Website, *, today: date | None = None, fetch=query_search_analytics_paged) -> dict:
    """Never raises: history bookkeeping must not break the regular sync. Returns {"status", "rows", ...}."""
    today = today or date.today()
    if not website.search_console_site_url:
        return {"status": "skipped", "rows": 0, "reason": "Search Console is not connected."}
    end = today - timedelta(days=REPORTING_LAG_DAYS)
    first_run = db.query(ProjectMetricHistory.id).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == SOURCE).first() is None
    start = end - timedelta(days=BACKFILL_DAYS if first_run else REFRESH_DAYS)
    run = SyncRun(db, website, SOURCE, range_start=start, range_end=end)
    try:
        token = token_store.get_valid_access_token(db, website.organization_id, OAuthProvider.google_search_console, refresh_fn=refresh_access_token)
        stored, truncated = 0, False
        now = datetime.now(timezone.utc)
        for dimensions in DIMENSION_SETS:
            rows, cut = fetch(token, website.search_console_site_url, start_date=start, end_date=end, dimensions=list(dimensions))
            truncated = truncated or cut
            for (scope_type, scope_value, day), totals in _merge(rows, dimensions).items():
                impressions = totals["impressions"]
                position = totals["weighted"] / impressions if impressions else (totals["position_sum"] / totals["n"] if totals["n"] else None)
                row = (db.query(ProjectMetricHistory).filter(
                    ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == SOURCE, ProjectMetricHistory.scope_type == scope_type,
                    ProjectMetricHistory.scope_value == scope_value, ProjectMetricHistory.metric_date == day).one_or_none())
                if row is None:
                    row = ProjectMetricHistory(website_id=website.id, source=SOURCE, scope_type=scope_type, scope_value=scope_value, metric_date=day,
                                               origin="imported" if first_run else "collected", clicks=0, impressions=0, fetched_at=now)
                    db.add(row)
                row.clicks, row.impressions, row.fetched_at = totals["clicks"], impressions, now
                row.ctr = round(totals["clicks"] / impressions, 6) if impressions else None
                row.position = round(position, 3) if position is not None else None
                stored += 1
        db.flush()
        run.success(rows=stored, truncated=truncated, detail={"first_run": first_run, "origin": "imported" if first_run else "collected"})
        if first_run and stored:
            activity.record_event(db, website, "integration", "search_history_imported", "Search Console history imported",
                                  detail={"days_from": start.isoformat(), "days_to": end.isoformat(), "rows": stored}, dedupe_key=f"gsc_imported:{website.id}")
        return {"status": "partial" if truncated else "success", "rows": stored, "first_run": first_run}
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        logger.warning("Search Console history sync failed for website %s: %s", website.id, exc)
        run.failed(exc)
        activity.record_event(db, website, "integration", "integration_error", "Search Console data could not be refreshed",
                              detail={"reason": str(exc)[:300]}, dedupe_key=f"gsc_error:{today.isoformat()}")
        return {"status": "failed", "rows": 0, "error": str(exc)[:300]}
