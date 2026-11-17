"""Query-level before/after measurement for an implemented AI-search recommendation.

Numbers are sums of stored Search Console rows. A window with no rows is None, never zero. A difference
between two periods is a correlation: seasonality, demand, Google updates and other edits also move it, so the
result never says the change caused anything."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.ai_search_finding import AiSearchFinding
from app.models.change_record import ChangeRecord
from app.models.keyword_observation import KeywordObservation

ALLOWED_WINDOWS = (7, 28, 90)
CAVEAT = (
    "Search Console data is delayed and aggregated. Seasonality, changes in demand, Google updates, indexing "
    "delays and other edits also move these numbers, so a difference before and after a change does not show "
    "that the change caused it."
)


def _stats(db: Session, website_id, query: str, page_id, start: date, end: date, country: str | None = None) -> dict | None:
    q = db.query(
        func.count(KeywordObservation.id), func.sum(KeywordObservation.clicks), func.sum(KeywordObservation.impressions),
        func.sum(KeywordObservation.average_position * KeywordObservation.impressions),
    ).filter(KeywordObservation.website_id == website_id, KeywordObservation.query == query,
             KeywordObservation.date >= start, KeywordObservation.date < end)
    if page_id is not None:
        q = q.filter(KeywordObservation.page_id == page_id)
    if country:
        q = q.filter(KeywordObservation.country == country)
    rows, clicks, impressions, weighted = q.one()
    if not rows:
        return None
    clicks, impressions = int(clicks or 0), int(impressions or 0)
    return {"clicks": clicks, "impressions": impressions, "ctr": round(clicks / impressions, 4) if impressions else None,
            "average_position": round(float(weighted) / impressions, 1) if impressions else None}


def _page_queries(db: Session, website_id, page_id, start: date, end: date) -> int | None:
    if page_id is None:
        return None
    n = (db.query(func.count(func.distinct(KeywordObservation.query)))
         .filter(KeywordObservation.website_id == website_id, KeywordObservation.page_id == page_id,
                 KeywordObservation.date >= start, KeywordObservation.date < end, KeywordObservation.impressions > 0).scalar())
    return int(n or 0) or None


def windows(implemented_on: date, window_days: int) -> tuple[date, date, date, date]:
    return implemented_on - timedelta(days=window_days), implemented_on, implemented_on + timedelta(days=1), implemented_on + timedelta(days=1 + window_days)


def baseline(db: Session, finding: AiSearchFinding, implemented_on: date, window_days: int = 28) -> dict:
    b0, b1, _, _ = windows(implemented_on, window_days)
    return {"window_days": window_days, "start": b0.isoformat(), "end": b1.isoformat(),
            "query": _stats(db, finding.website_id, finding.query, finding.page_id, b0, b1),
            "page_queries": _page_queries(db, finding.website_id, finding.page_id, b0, b1)}


def build(db: Session, finding: AiSearchFinding, *, window_days: int = 28, today: date | None = None) -> dict:
    if window_days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOWS}.")
    if finding.implemented_at is None:
        raise ValueError("This recommendation has not been implemented yet.")
    today = today or date.today()
    day = finding.implemented_at.date()
    b0, b1, a0, a1 = windows(day, window_days)
    before = _stats(db, finding.website_id, finding.query, finding.page_id, b0, b1)
    after = _stats(db, finding.website_id, finding.query, finding.page_id, a0, a1)
    countries = {}
    for (code,) in (db.query(KeywordObservation.country).filter(KeywordObservation.website_id == finding.website_id, KeywordObservation.query == finding.query,
                    KeywordObservation.date >= b0, KeywordObservation.date < a1).distinct()):
        if code:
            countries[code] = {"before": _stats(db, finding.website_id, finding.query, finding.page_id, b0, b1, code),
                               "after": _stats(db, finding.website_id, finding.query, finding.page_id, a0, a1, code)}
    changes = (
        db.query(ChangeRecord).filter(ChangeRecord.website_id == finding.website_id, ChangeRecord.page_id == finding.page_id,
                                      ChangeRecord.executed_at >= finding.implemented_at - timedelta(days=window_days),
                                      ChangeRecord.executed_at <= finding.implemented_at + timedelta(days=window_days)).all()
        if finding.page_id else []
    )
    others = (
        db.query(AiSearchFinding).filter(AiSearchFinding.website_id == finding.website_id, AiSearchFinding.page_id == finding.page_id,
                                         AiSearchFinding.id != finding.id, AiSearchFinding.implemented_at.isnot(None),
                                         AiSearchFinding.implemented_at >= finding.implemented_at - timedelta(days=window_days),
                                         AiSearchFinding.implemented_at <= finding.implemented_at + timedelta(days=window_days)).all()
        if finding.page_id else []
    )
    confounders = [{"kind": "cms_change", "at": c.executed_at.isoformat()} for c in changes] + \
                  [{"kind": "other_ai_search_change", "query": o.query, "at": o.implemented_at.isoformat()} for o in others]
    delta = None
    if before and after:
        delta = {"clicks": after["clicks"] - before["clicks"], "impressions": after["impressions"] - before["impressions"],
                 "ctr": None if before["ctr"] is None or after["ctr"] is None else round(after["ctr"] - before["ctr"], 4),
                 "average_position": None if before["average_position"] is None or after["average_position"] is None
                 else round(after["average_position"] - before["average_position"], 1)}
    complete = a1 + timedelta(days=REPORTING_LAG_DAYS) <= today
    return {
        "implemented_on": day.isoformat(), "window_days": window_days, "caveat": CAVEAT,
        "before": before, "after": after, "change": delta, "after_window_complete": complete,
        "frozen_baseline": finding.baseline_json, "country_breakdown": countries,
        "page_query_coverage": {"before": _page_queries(db, finding.website_id, finding.page_id, b0, b1),
                                "after": _page_queries(db, finding.website_id, finding.page_id, a0, a1)},
        "other_changes_in_window": confounders,
        "note": ("Other changes touched this page in the same period, so the difference cannot be attributed to this one." if confounders
                 else "A before/after difference is a correlation, not proof that this change caused it."),
    }
