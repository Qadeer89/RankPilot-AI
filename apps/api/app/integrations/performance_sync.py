"""Pull Core Web Vitals for a website's pages and store them as
PerformanceMetric rows (RankPilot AI Phase 4).

No OAuth, unlike GA4/Search Console -- just an API key
(settings.pagespeed_api_key). Bounded per run
(settings.pagespeed_max_pages_per_sync) since each PageSpeed Insights
call runs a real Lighthouse audit and takes several seconds; pages
past the cap are picked up on a later sync, same spirit as
MAX_AUTO_TASKS_PER_CRAWL / MAX_EXTERNAL_LINKS_VERIFIED_PER_CRAWL.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.pagespeed import PageSpeedApiError, fetch_core_web_vitals
from app.models.page import Page
from app.models.performance_metric import PerformanceMetric, PerformanceStrategy
from app.models.website import Website

logger = logging.getLogger(__name__)


class PageSpeedNotConfigured(RuntimeError):
    pass


def sync_performance_metrics(
    db: Session, website: Website, *, strategy: PerformanceStrategy = PerformanceStrategy.mobile
) -> int:
    settings = get_settings()
    if not settings.pagespeed_api_key:
        raise PageSpeedNotConfigured("No PageSpeed Insights API key is configured (RANKPILOT_PAGESPEED_API_KEY).")

    pages = (
        db.query(Page)
        .filter(Page.website_id == website.id, Page.last_status_code == 200)
        .order_by(Page.last_seen_at.desc())
        .limit(settings.pagespeed_max_pages_per_sync)
        .all()
    )

    synced = 0
    for page in pages:
        try:
            result = fetch_core_web_vitals(
                page.canonical_url,
                api_key=settings.pagespeed_api_key,
                strategy=strategy.value,
                timeout_seconds=settings.pagespeed_request_timeout_seconds,
            )
        except PageSpeedApiError as exc:
            logger.info("performance_sync: skipping page %s (%s)", page.id, exc)
            continue

        existing = (
            db.query(PerformanceMetric)
            .filter(PerformanceMetric.page_id == page.id, PerformanceMetric.strategy == strategy)
            .one_or_none()
        )
        if existing is None:
            existing = PerformanceMetric(page_id=page.id, strategy=strategy)
            db.add(existing)

        existing.lab_performance_score = result.lab_performance_score
        existing.lab_lcp_ms = result.lab_lcp_ms
        existing.lab_cls = result.lab_cls
        existing.lab_tbt_ms = result.lab_tbt_ms
        existing.field_lcp_ms = result.field_lcp_ms
        existing.field_cls = result.field_cls
        existing.field_inp_ms = result.field_inp_ms
        existing.opportunities_json = [
            {"audit_id": o.audit_id, "title": o.title, "savings_ms": o.savings_ms} for o in result.opportunities
        ]
        synced += 1

    db.flush()
    return synced
