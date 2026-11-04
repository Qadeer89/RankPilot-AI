"""Search-Console-derived opportunities: flag queries that already rank
reasonably well but get essentially no clicks. This is a signal the
crawler's structural checks can never see (the page itself is fine) --
it's purely about what the search snippet (title/meta description)
looks like next to a real SERP position. Detection is deterministic
(MASTER_SPEC.md "Global implementation rules": AI only drafts fixes
afterwards, never decides whether something is an opportunity).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.keyword_observation import KeywordObservation
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website

LOOKBACK_DAYS = 28
MIN_IMPRESSIONS = 5
MAX_POSITION_FOR_GOOD_RANKING = 10.0
MAX_CLICKS_TO_FLAG = 0

_TITLE_PREFIX = "Improve click-through for"


def _title_for(query: str) -> str:
    return f'{_TITLE_PREFIX} "{query}"'


def _rationale_for(query: str, avg_position: float, impressions: int, clicks: int) -> str:
    return (
        f'"{query}" ranks at position {avg_position:.1f} with {impressions} impressions in the last '
        f"{LOOKBACK_DAYS} days, but got {clicks} clicks -- the ranking is doing its job, the title/"
        "description shown in the search result isn't earning the click."
    )


def refresh_ctr_opportunities(db: Session, website: Website) -> list[SEOOpportunity]:
    """Re-derive "good position, no clicks" opportunities from recently
    synced Search Console data (KeywordObservation rows, populated by
    search_console_sync.py, which attributes each query to the page it
    actually landed on). page_id is None only when that landing page
    hasn't been crawled yet, in which case the opportunity is still
    created but the AI content agent later gets no page evidence to draft
    a fix from (app/api/v1/endpoints/opportunities.py).
    """
    if not website.search_console_site_url:
        return []

    window_start = date.today() - timedelta(days=LOOKBACK_DAYS)
    rows = (
        db.query(
            KeywordObservation.query,
            KeywordObservation.page_id,
            func.sum(KeywordObservation.clicks),
            func.sum(KeywordObservation.impressions),
            func.avg(KeywordObservation.average_position),
        )
        .filter(KeywordObservation.website_id == website.id, KeywordObservation.date >= window_start)
        .group_by(KeywordObservation.query, KeywordObservation.page_id)
        .all()
    )

    existing_opportunities = {
        (o.page_id, o.title): o
        for o in db.query(SEOOpportunity).filter(SEOOpportunity.website_id == website.id).all()
        if o.title.startswith(_TITLE_PREFIX)
    }

    touched_keys: set[tuple[uuid.UUID | None, str]] = set()
    persisted: list[SEOOpportunity] = []

    for query, page_id, total_clicks, total_impressions, avg_position in rows:
        total_clicks = int(total_clicks or 0)
        total_impressions = int(total_impressions or 0)
        avg_position = float(avg_position or 0.0)

        qualifies = (
            total_impressions >= MIN_IMPRESSIONS
            and 0 < avg_position <= MAX_POSITION_FOR_GOOD_RANKING
            and total_clicks <= MAX_CLICKS_TO_FLAG
        )
        if not qualifies:
            continue

        title = _title_for(query)
        key = (page_id, title)
        touched_keys.add(key)
        rationale = _rationale_for(query, avg_position, total_impressions, total_clicks)
        evidence = {
            "query": query,
            "avg_position": round(avg_position, 1),
            "impressions": total_impressions,
            "clicks": total_clicks,
            "window_days": LOOKBACK_DAYS,
        }

        existing = existing_opportunities.get(key)
        if existing is None:
            opportunity = SEOOpportunity(
                website_id=website.id,
                page_id=page_id,
                category="content",
                title=title,
                rationale=rationale,
                impact_estimate=0.6,
                confidence=0.7,
                effort_estimate=0.3,
                risk_tier=1,
                evidence_json=evidence,
                status=OpportunityStatus.open,
            )
            db.add(opportunity)
        else:
            existing.rationale = rationale
            existing.evidence_json = evidence
            if existing.status in (OpportunityStatus.resolved, OpportunityStatus.completed):
                existing.status = OpportunityStatus.open
            opportunity = existing
        persisted.append(opportunity)

    db.flush()

    for key, opportunity in existing_opportunities.items():
        if key not in touched_keys and opportunity.status == OpportunityStatus.open:
            # The query no longer qualifies (clicks picked up, position
            # dropped, or it fell out of the lookback window) -- nobody
            # executed a fix for it here, so "resolved", not "completed"
            # (app/opportunities/scoring.py's same distinction).
            opportunity.status = OpportunityStatus.resolved

    db.flush()
    return sorted(persisted, key=lambda o: o.score, reverse=True)
