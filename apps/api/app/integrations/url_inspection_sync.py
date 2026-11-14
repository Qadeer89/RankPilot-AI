"""Pull Google's own indexing view for a website's pages via the Search
Console URL Inspection API and store it as PageIndexingStatus rows
(RankPilot AI Phase 5 "Google Search Intelligence").

Reuses the same OAuth connection as search_console_sync.py -- no
separate consent. Bounded per run like performance_sync.py, since each
inspection is a real API call against Google's own quota.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import token_store
from app.integrations.google_search_console import (
    GoogleApiError,
    inspect_url,
    refresh_access_token,
)
from app.models.oauth_connection import OAuthProvider
from app.models.page import Page
from app.models.page_indexing_status import PageIndexingStatus
from app.models.website import Website

logger = logging.getLogger(__name__)


def _parse_crawl_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)


def sync_url_inspection_status(db: Session, website: Website) -> int:
    if not website.search_console_site_url:
        raise LookupError("No Search Console property is selected for this website yet.")

    settings = get_settings()
    access_token = token_store.get_valid_access_token(
        db, website.organization_id, OAuthProvider.google_search_console, refresh_fn=refresh_access_token
    )

    pages = (
        db.query(Page)
        .filter(Page.website_id == website.id, Page.last_status_code == 200)
        .order_by(Page.last_seen_at.desc())
        .limit(settings.url_inspection_max_pages_per_sync)
        .all()
    )

    synced = 0
    for page in pages:
        try:
            result = inspect_url(access_token, website.search_console_site_url, page.canonical_url)
        except GoogleApiError as exc:
            logger.info("url_inspection_sync: skipping page %s (%s)", page.id, exc)
            continue

        index_status = result.get("indexStatusResult", {})
        mobile_usability = result.get("mobileUsabilityResult", {})

        existing = db.query(PageIndexingStatus).filter(PageIndexingStatus.page_id == page.id).one_or_none()
        if existing is None:
            existing = PageIndexingStatus(page_id=page.id, verdict="VERDICT_UNSPECIFIED")
            db.add(existing)

        existing.verdict = index_status.get("verdict", "VERDICT_UNSPECIFIED")
        existing.coverage_state = index_status.get("coverageState")
        existing.robots_txt_state = index_status.get("robotsTxtState")
        existing.indexing_state = index_status.get("indexingState")
        existing.page_fetch_state = index_status.get("pageFetchState")
        existing.last_crawl_time = _parse_crawl_time(index_status.get("lastCrawlTime"))
        existing.google_canonical_url = index_status.get("googleCanonicalUrl") or index_status.get("googleCanonical")
        existing.user_canonical_url = index_status.get("userCanonicalUrl") or index_status.get("userCanonical")
        existing.crawled_as = index_status.get("crawledAs")
        existing.mobile_usability_verdict = mobile_usability.get("verdict")
        existing.mobile_usability_issues_json = mobile_usability.get("issues", [])
        synced += 1

    db.flush()
    return synced
