"""Search-performance trend signals, derived purely from already-synced
KeywordObservation rows (RankPilot AI Phase 5 "Search Performance
Intelligence").

Unlike search_console_signals.py's CTR opportunities, these are
report-only: there is no existing AI fix operation for "this page is
losing clicks" or "two pages compete for the same query" -- the
correct response is strategic (content, internal linking, consolidation
decisions a human makes), not a title/meta rewrite. So these are never
turned into SEOOpportunity rows and never enter the auto-execute
pipeline (app/opportunities/auto_pipeline.py) -- that would either
waste an AI call on an opportunity with nothing sensible to draft, or
worse, produce a plausible-looking "fix" for a signal AI has no real
mechanism to address.

Every number here comes straight from aggregated KeywordObservation
rows already synced from Google (search_console_sync.py) -- nothing is
estimated or inferred (MASTER_SPEC.md: "Never fabricate keyword
rankings, search volumes or Google performance data").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.keyword_observation import KeywordObservation
from app.models.website import Website

TREND_WINDOW_DAYS = 14
# A page needs at least this many impressions in the prior window before
# a decline is reported -- otherwise near-zero-traffic noise (e.g. 1
# impression dropping to 0) would dominate the list.
MIN_PRIOR_IMPRESSIONS_FOR_TREND = 10
CLICKS_DECLINE_THRESHOLD = 0.3
IMPRESSIONS_DECLINE_THRESHOLD = 0.3
POSITION_WORSENING_THRESHOLD = 3.0

RANKING_OPPORTUNITY_WINDOW_DAYS = 28
NEAR_PAGE_ONE_MIN_POSITION = 11.0
NEAR_PAGE_ONE_MAX_POSITION = 20.0
MIN_IMPRESSIONS_FOR_RANKING_OPPORTUNITY = 10

CANNIBALIZATION_WINDOW_DAYS = 28
MIN_IMPRESSIONS_PER_PAGE_FOR_CANNIBALIZATION = 5


@dataclass(frozen=True)
class WindowStats:
    clicks: int
    impressions: int
    average_position: float


@dataclass(frozen=True)
class PageTrendSignal:
    page_id: uuid.UUID
    signals: list[str]
    prior: WindowStats
    recent: WindowStats


@dataclass(frozen=True)
class RankingOpportunity:
    query: str
    page_id: uuid.UUID | None
    average_position: float
    impressions: int


@dataclass(frozen=True)
class CannibalizationCandidate:
    query: str
    pages: list[dict] = field(default_factory=list)


def _aggregate_by_page(db: Session, website_id: uuid.UUID, start: date, end: date) -> dict[uuid.UUID, WindowStats]:
    rows = (
        db.query(
            KeywordObservation.page_id,
            func.sum(KeywordObservation.clicks),
            func.sum(KeywordObservation.impressions),
            func.avg(KeywordObservation.average_position),
        )
        .filter(
            KeywordObservation.website_id == website_id,
            KeywordObservation.page_id.isnot(None),
            KeywordObservation.date >= start,
            KeywordObservation.date < end,
        )
        .group_by(KeywordObservation.page_id)
        .all()
    )
    return {
        page_id: WindowStats(clicks=int(clicks or 0), impressions=int(impressions or 0), average_position=float(position or 0.0))
        for page_id, clicks, impressions, position in rows
    }


def detect_page_trend_signals(db: Session, website: Website) -> list[PageTrendSignal]:
    """Compare each page's most recent TREND_WINDOW_DAYS of Search
    Console data against the TREND_WINDOW_DAYS before that, and flag
    pages whose clicks, impressions or average position meaningfully
    worsened.
    """
    end = date.today()
    recent_start = end - timedelta(days=TREND_WINDOW_DAYS)
    prior_start = recent_start - timedelta(days=TREND_WINDOW_DAYS)

    recent_by_page = _aggregate_by_page(db, website.id, recent_start, end)
    prior_by_page = _aggregate_by_page(db, website.id, prior_start, recent_start)

    empty = WindowStats(clicks=0, impressions=0, average_position=0.0)
    results: list[PageTrendSignal] = []

    for page_id, prior in prior_by_page.items():
        if prior.impressions < MIN_PRIOR_IMPRESSIONS_FOR_TREND:
            continue
        recent = recent_by_page.get(page_id, empty)

        signals: list[str] = []
        if prior.clicks > 0 and (recent.clicks - prior.clicks) / prior.clicks <= -CLICKS_DECLINE_THRESHOLD:
            signals.append("clicks_declining")
        if (recent.impressions - prior.impressions) / prior.impressions <= -IMPRESSIONS_DECLINE_THRESHOLD:
            signals.append("impressions_declining")
        if (
            recent.impressions > 0
            and prior.average_position > 0
            and (recent.average_position - prior.average_position) >= POSITION_WORSENING_THRESHOLD
        ):
            signals.append("position_worsening")

        if signals:
            results.append(PageTrendSignal(page_id=page_id, signals=signals, prior=prior, recent=recent))

    return results


def detect_ranking_improvement_opportunities(db: Session, website: Website) -> list[RankingOpportunity]:
    """Queries ranking on page 2 of Google (positions 11-20) with
    meaningful impression volume -- close enough to page 1 that a
    content/internal-linking push is a plausible way to close the gap.
    """
    start = date.today() - timedelta(days=RANKING_OPPORTUNITY_WINDOW_DAYS)
    rows = (
        db.query(
            KeywordObservation.query,
            KeywordObservation.page_id,
            func.sum(KeywordObservation.impressions),
            func.avg(KeywordObservation.average_position),
        )
        .filter(KeywordObservation.website_id == website.id, KeywordObservation.date >= start)
        .group_by(KeywordObservation.query, KeywordObservation.page_id)
        .all()
    )

    opportunities: list[RankingOpportunity] = []
    for query, page_id, impressions, avg_position in rows:
        impressions = int(impressions or 0)
        avg_position = float(avg_position or 0.0)
        if impressions < MIN_IMPRESSIONS_FOR_RANKING_OPPORTUNITY:
            continue
        if NEAR_PAGE_ONE_MIN_POSITION <= avg_position <= NEAR_PAGE_ONE_MAX_POSITION:
            opportunities.append(
                RankingOpportunity(query=query, page_id=page_id, average_position=avg_position, impressions=impressions)
            )

    return sorted(opportunities, key=lambda o: o.impressions, reverse=True)


def detect_keyword_cannibalization(db: Session, website: Website) -> list[CannibalizationCandidate]:
    """A query that multiple distinct pages earn meaningful impressions
    for is a cannibalization candidate -- Google is unsure which of the
    site's own pages should rank for it, which usually splits authority
    across both instead of concentrating it on one.
    """
    start = date.today() - timedelta(days=CANNIBALIZATION_WINDOW_DAYS)
    rows = (
        db.query(
            KeywordObservation.query,
            KeywordObservation.page_id,
            func.sum(KeywordObservation.impressions),
            func.avg(KeywordObservation.average_position),
        )
        .filter(
            KeywordObservation.website_id == website.id,
            KeywordObservation.page_id.isnot(None),
            KeywordObservation.date >= start,
        )
        .group_by(KeywordObservation.query, KeywordObservation.page_id)
        .all()
    )

    by_query: dict[str, list[dict]] = {}
    for query, page_id, impressions, avg_position in rows:
        impressions = int(impressions or 0)
        if impressions < MIN_IMPRESSIONS_PER_PAGE_FOR_CANNIBALIZATION:
            continue
        by_query.setdefault(query, []).append(
            {"page_id": page_id, "impressions": impressions, "average_position": float(avg_position or 0.0)}
        )

    return [
        CannibalizationCandidate(query=query, pages=sorted(pages, key=lambda p: p["impressions"], reverse=True))
        for query, pages in by_query.items()
        if len(pages) > 1
    ]
