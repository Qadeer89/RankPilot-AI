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


@dataclass(frozen=True)
class NewQuery:
    query: str
    page_id: uuid.UUID | None
    impressions: int
    clicks: int
    average_position: float
    country: str | None


CLICKS_GROWTH_THRESHOLD = 0.3
IMPRESSIONS_GROWTH_THRESHOLD = 0.3
POSITION_IMPROVEMENT_THRESHOLD = 3.0
NEW_QUERY_WINDOW_DAYS = 14
MIN_IMPRESSIONS_FOR_NEW_QUERY = 3


def _country_filter(country: str | None):
    return KeywordObservation.country == country if country else True


def _aggregate_by_page(
    db: Session, website_id: uuid.UUID, start: date, end: date, *, country: str | None = None
) -> dict[uuid.UUID, WindowStats]:
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
            _country_filter(country),
        )
        .group_by(KeywordObservation.page_id)
        .all()
    )
    return {
        page_id: WindowStats(clicks=int(clicks or 0), impressions=int(impressions or 0), average_position=float(position or 0.0))
        for page_id, clicks, impressions, position in rows
    }


def detect_page_trend_signals(db: Session, website: Website, *, country: str | None = None) -> list[PageTrendSignal]:
    """Compare each page's most recent TREND_WINDOW_DAYS of Search
    Console data against the TREND_WINDOW_DAYS before that, and flag
    pages whose clicks, impressions or average position meaningfully
    worsened -- or, symmetrically, meaningfully improved
    ("clicks_growing"/"impressions_growing"/"position_improving").
    Pass `country` (GSC's own alpha-3 code) to scope the comparison to
    one target market instead of the site's worldwide traffic.
    """
    end = date.today()
    recent_start = end - timedelta(days=TREND_WINDOW_DAYS)
    prior_start = recent_start - timedelta(days=TREND_WINDOW_DAYS)

    recent_by_page = _aggregate_by_page(db, website.id, recent_start, end, country=country)
    prior_by_page = _aggregate_by_page(db, website.id, prior_start, recent_start, country=country)

    empty = WindowStats(clicks=0, impressions=0, average_position=0.0)
    results: list[PageTrendSignal] = []

    for page_id, prior in prior_by_page.items():
        if prior.impressions < MIN_PRIOR_IMPRESSIONS_FOR_TREND:
            continue
        recent = recent_by_page.get(page_id, empty)

        signals: list[str] = []
        if prior.clicks > 0:
            clicks_change = (recent.clicks - prior.clicks) / prior.clicks
            if clicks_change <= -CLICKS_DECLINE_THRESHOLD:
                signals.append("clicks_declining")
            elif clicks_change >= CLICKS_GROWTH_THRESHOLD:
                signals.append("clicks_growing")
        if prior.impressions > 0:
            impressions_change = (recent.impressions - prior.impressions) / prior.impressions
            if impressions_change <= -IMPRESSIONS_DECLINE_THRESHOLD:
                signals.append("impressions_declining")
            elif impressions_change >= IMPRESSIONS_GROWTH_THRESHOLD:
                signals.append("impressions_growing")
        if recent.impressions > 0 and prior.average_position > 0:
            position_change = recent.average_position - prior.average_position
            if position_change >= POSITION_WORSENING_THRESHOLD:
                signals.append("position_worsening")
            elif position_change <= -POSITION_IMPROVEMENT_THRESHOLD:
                signals.append("position_improving")

        if signals:
            results.append(PageTrendSignal(page_id=page_id, signals=signals, prior=prior, recent=recent))

    return results


def detect_new_queries(db: Session, website: Website, *, country: str | None = None) -> list[NewQuery]:
    """Queries that earned real impressions in the last
    NEW_QUERY_WINDOW_DAYS but never appeared before that -- genuine new
    search visibility discovered from GSC's own impression data (SEO
    Growth Engine spec section 3A.10: "New query discovery from actual
    search impressions"), not an AI guess.
    """
    end = date.today()
    recent_start = end - timedelta(days=NEW_QUERY_WINDOW_DAYS)

    seen_before = {
        row[0]
        for row in db.query(KeywordObservation.query)
        .filter(
            KeywordObservation.website_id == website.id,
            KeywordObservation.date < recent_start,
            _country_filter(country),
        )
        .distinct()
        .all()
    }

    rows = (
        db.query(
            KeywordObservation.query,
            KeywordObservation.page_id,
            KeywordObservation.country,
            func.sum(KeywordObservation.impressions),
            func.sum(KeywordObservation.clicks),
            func.avg(KeywordObservation.average_position),
        )
        .filter(
            KeywordObservation.website_id == website.id,
            KeywordObservation.date >= recent_start,
            _country_filter(country),
        )
        .group_by(KeywordObservation.query, KeywordObservation.page_id, KeywordObservation.country)
        .all()
    )

    new_queries = [
        NewQuery(
            query=query,
            page_id=page_id,
            impressions=int(impressions or 0),
            clicks=int(clicks or 0),
            average_position=float(avg_position or 0.0),
            country=observed_country,
        )
        for query, page_id, observed_country, impressions, clicks, avg_position in rows
        if query not in seen_before and int(impressions or 0) >= MIN_IMPRESSIONS_FOR_NEW_QUERY
    ]
    return sorted(new_queries, key=lambda q: q.impressions, reverse=True)


def detect_ranking_improvement_opportunities(
    db: Session, website: Website, *, country: str | None = None
) -> list[RankingOpportunity]:
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
        .filter(
            KeywordObservation.website_id == website.id,
            KeywordObservation.date >= start,
            _country_filter(country),
        )
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


def detect_keyword_cannibalization(
    db: Session, website: Website, *, country: str | None = None
) -> list[CannibalizationCandidate]:
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
            _country_filter(country),
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
