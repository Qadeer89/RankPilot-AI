"""Finds conversational / question / long-tail queries in the Search Console data RankPilot already stores
(KeywordObservation), maps them to landing pages and scores them, with every factor listed.

Nothing is invented: no search volume, difficulty or CPC. CTR is compared with THIS site's own median CTR
at a similar position, never with an external benchmark."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.ai_search.classify import CATEGORIES, COMPARISON, CONVERSATIONAL, PROBLEM_SOLUTION, QUESTION, classify_query, validate_re2_regex
from app.ai_search.terms import coverage
from app.config import get_settings
from app.core.countries import normalize_country
from app.integrations.search_console_sync import REPORTING_LAG_DAYS
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.website import Website

WINDOW_PRESETS = {"7d": 7, "28d": 28, "3m": 90, "6m": 180}
MAX_QUERIES = 20000
CANNIBALIZATION_SHARE = 0.25
LOW_COVERAGE = 0.4

HIGH_OPPORTUNITY = "high_opportunity"
CONTENT_GAP = "content_gap"
RANKING_IMPROVEMENT = "ranking_improvement"
LOW_PRIORITY = "low_priority"
TIERS = (HIGH_OPPORTUNITY, CONTENT_GAP, RANKING_IMPROVEMENT, LOW_PRIORITY)


class RangeError(ValueError):
    pass


def resolve_window(preset: str | None, start: date | None, end: date | None, *, today: date | None = None) -> tuple[date, date]:
    """(start, end) inclusive. The newest days are left out because Search Console reports with a lag."""
    today = today or date.today()
    latest = today - timedelta(days=REPORTING_LAG_DAYS)
    if preset in (None, ""):
        preset = "28d" if start is None else "custom"
    if preset == "custom":
        if start is None or end is None:
            raise RangeError("A custom range needs a start and an end date.")
        if end < start:
            raise RangeError("The end date is before the start date.")
        if (end - start).days > 540:
            raise RangeError("Search Console keeps about 16 months; the range is too long.")
        return start, end
    if preset not in WINDOW_PRESETS:
        raise RangeError(f"Unknown range '{preset}'. Use one of: {', '.join(WINDOW_PRESETS)}, custom.")
    return latest - timedelta(days=WINDOW_PRESETS[preset] - 1), latest


@dataclass
class PageShare:
    page_id: object
    url: str | None
    impressions: int
    clicks: int
    ctr: float
    position: float


@dataclass
class Opportunity:
    query: str
    categories: tuple[str, ...]
    signals: tuple[str, ...]
    word_count: int
    country: str | None  # the single country filtered on, else the country with the most impressions
    countries: dict[str, int]
    impressions: int
    clicks: int
    ctr: float
    position: float
    page: PageShare | None
    other_pages: list[PageShare]
    needs_review: bool
    coverage: float | None
    trend: str  # growing | stable | declining | unknown
    score: int
    tier: str
    factors: list[dict] = field(default_factory=list)


def _bucket(position: float) -> str:
    for upper, name in ((1.5, "1"), (2.5, "2"), (3.5, "3"), (5.5, "4-5"), (10.5, "6-10"), (20.5, "11-20")):
        if position < upper:
            return name
    return "21+"


def _ctr_benchmarks(rows: list[tuple[float, float, int]], min_impr: int, min_samples: int) -> dict[str, float]:
    """Median CTR per position bucket from THIS site's own queries (position, ctr, impressions)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for position, ctr, impressions in rows:
        if impressions >= min_impr:
            buckets[_bucket(position)].append(ctr)
    return {name: statistics.median(vals) for name, vals in buckets.items() if len(vals) >= min_samples}


def score_opportunity(
    *, impressions: int, position: float, ctr: float, has_page: bool, coverage_value: float | None, trend: str,
    categories: tuple[str, ...], benchmark: float | None, min_impressions: int, needs_review: bool,
) -> tuple[int, str, list[dict]]:
    factors: list[dict] = []

    def add(name: str, points: float, maximum: float, note: str) -> None:
        factors.append({"factor": name, "points": round(points, 1), "max": maximum, "note": note})

    demand = min(30.0, 30.0 * math.log10(max(impressions, 1)) / math.log10(1000)) if impressions else 0.0
    add("Demand", demand, 30, f"{impressions} impressions in the period")

    if position <= 3:
        pos_pts, note = 5, "already in the top 3: little headroom"
    elif position <= 10:
        pos_pts, note = 25, "on page one below the top 3: a better answer can move it"
    elif position <= 20:
        pos_pts, note = 22, "page two: close enough to reach page one"
    elif position <= 30:
        pos_pts, note = 15, "pages three to four"
    elif position <= 50:
        pos_pts, note = 8, "far down the results"
    else:
        pos_pts, note = 2, "very far down the results"
    add("Position headroom", pos_pts, 25, f"average position {position:.1f}: {note}")

    if benchmark is None:
        add("CTR vs this site", 0, 15, "not scored: too few comparable queries on this site to form a benchmark")
        ctr_ratio = None
    else:
        ctr_ratio = ctr / benchmark if benchmark else None
        if ctr_ratio is not None and ctr_ratio <= 0.5:
            pts = 15
        elif ctr_ratio is not None and ctr_ratio < 0.8:
            pts = 8
        else:
            pts = 0
        add("CTR vs this site", pts, 15, f"CTR {ctr * 100:.1f}% vs this site's median {benchmark * 100:.1f}% at a similar position")

    add("Page relevance", 10 if has_page else 0, 10, "a crawled landing page receives this query" if has_page else "no crawled landing page is known for this query")

    if not has_page:
        cov_pts, note = 15, "no page to cover the query"
    elif coverage_value is None:
        cov_pts, note = 0, "page title/headings not available"
    else:
        cov_pts, note = (1 - coverage_value) * 15, f"{coverage_value * 100:.0f}% of the query's terms appear in the page title/headings"
    add("Answer coverage gap", cov_pts, 15, note)

    add("Trend", 5 if trend == "growing" else 0, 5, {"growing": "impressions grew within the period", "declining": "impressions fell within the period",
                                                    "stable": "impressions steady", "unknown": "not enough days to judge"}[trend])
    intent_pts = 5 if (QUESTION in categories or CONVERSATIONAL in categories) else 3 if (COMPARISON in categories or PROBLEM_SOLUTION in categories) else 1
    add("Intent fit", intent_pts, 5, "question / conversational wording" if intent_pts == 5 else "comparison or problem wording" if intent_pts == 3 else "long-tail only")
    score = int(min(100, round(sum(f["points"] for f in factors))))

    # Tier. Low CTR alone never makes an opportunity.
    ctr_low = ctr_ratio is not None and ctr_ratio < 0.8
    if impressions < min_impressions:
        tier = LOW_PRIORITY
        factors.append({"factor": "Tier", "points": 0, "max": 0, "note": f"fewer than {min_impressions} impressions: not enough evidence"})
    elif not has_page or (coverage_value is not None and coverage_value < LOW_COVERAGE):
        tier = CONTENT_GAP
    elif ctr_low and position <= 20:
        tier = HIGH_OPPORTUNITY
    elif 4 <= position <= 30:
        tier = RANKING_IMPROVEMENT
    else:
        tier = LOW_PRIORITY
    if needs_review:
        factors.append({"factor": "Review", "points": 0, "max": 0, "note": "several of this site's pages receive this query: decide which one should own it before changing anything"})
    return score, tier, factors


def data_coverage(db: Session, website_id) -> dict:
    first, last, rows = db.query(func.min(KeywordObservation.date), func.max(KeywordObservation.date), func.count(KeywordObservation.id)).filter(
        KeywordObservation.website_id == website_id).one()
    return {"first_day": first.isoformat() if first else None, "last_day": last.isoformat() if last else None, "rows": int(rows or 0)}


def discover(
    db: Session, website: Website, *, start: date, end: date, country: str | None = None, device: str | None = None,
    page_id=None, include_plain: bool = False,
) -> dict:
    """Everything the dashboard needs, computed from stored rows. Returns {"items": [Opportunity], "warnings": [...], "coverage": {...}}."""
    settings = get_settings()
    min_impr = settings.ai_search_min_impressions
    regex = validate_re2_regex(settings.ai_search_long_query_regex)
    country_code = normalize_country(country) if country else None
    if country and country_code is None:
        raise ValueError(f"'{country}' is not a recognized country code.")

    base = [KeywordObservation.website_id == website.id, KeywordObservation.date >= start, KeywordObservation.date <= end]
    if country_code:
        base.append(KeywordObservation.country == country_code)
    if device:
        base.append(KeywordObservation.device == device.upper())
    if page_id is not None:
        base.append(KeywordObservation.page_id == page_id)

    midpoint = start + (end - start) / 2
    rows = (
        db.query(
            KeywordObservation.query, KeywordObservation.page_id,
            func.sum(KeywordObservation.impressions), func.sum(KeywordObservation.clicks),
            func.sum(KeywordObservation.average_position * KeywordObservation.impressions),
            func.sum(case((KeywordObservation.date <= midpoint, KeywordObservation.impressions), else_=0)),
            func.sum(case((KeywordObservation.date > midpoint, KeywordObservation.impressions), else_=0)),
            func.count(func.distinct(KeywordObservation.date)),
        )
        .filter(*base)
        .group_by(KeywordObservation.query, KeywordObservation.page_id)
        .all()
    )
    country_rows = (
        db.query(KeywordObservation.query, KeywordObservation.country, func.sum(KeywordObservation.impressions))
        .filter(*base).group_by(KeywordObservation.query, KeywordObservation.country).all()
    )
    countries: dict[str, dict[str, int]] = defaultdict(dict)
    for q, c, impr in country_rows:
        countries[q][c or "ZZ"] = int(impr or 0)

    per_query: dict[str, list[dict]] = defaultdict(list)
    bench_rows: list[tuple[float, float, int]] = []
    for q, pid, impr, clicks, wpos, first_half, second_half, days in rows:
        impr, clicks = int(impr or 0), int(clicks or 0)
        if impr <= 0:
            continue
        position = float(wpos or 0) / impr
        per_query[q].append({"page_id": pid, "impressions": impr, "clicks": clicks, "position": position,
                             "first": int(first_half or 0), "second": int(second_half or 0), "days": int(days or 0)})
        bench_rows.append((position, clicks / impr, impr))
    benchmarks = _ctr_benchmarks(bench_rows, min_impr, settings.ai_search_benchmark_min_samples)

    classified = {}
    for q in per_query:
        info = classify_query(q, long_query_regex=regex)
        if info.is_target or include_plain:
            classified[q] = info
    wanted_pages = {p["page_id"] for q in classified for p in per_query[q] if p["page_id"] is not None}
    page_info = _page_info(db, wanted_pages)

    items: list[Opportunity] = []
    for q, info in classified.items():
        pages = sorted(per_query[q], key=lambda p: p["impressions"], reverse=True)
        total_impr = sum(p["impressions"] for p in pages)
        total_clicks = sum(p["clicks"] for p in pages)
        position = sum(p["position"] * p["impressions"] for p in pages) / total_impr
        shares = [
            PageShare(p["page_id"], page_info.get(p["page_id"], {}).get("url"), p["impressions"], p["clicks"],
                      p["clicks"] / p["impressions"], p["position"]) for p in pages
        ]
        primary = shares[0] if shares[0].page_id is not None else None
        review = sum(1 for s in shares[1:] if s.page_id is not None and s.impressions >= min_impr and s.impressions / total_impr >= CANNIBALIZATION_SHARE) >= 1 and primary is not None
        first_half, second_half = sum(p["first"] for p in pages), sum(p["second"] for p in pages)
        days_seen = max(p["days"] for p in pages)
        if days_seen < 4 or first_half + second_half < min_impr:
            trend = "unknown"
        elif second_half >= first_half * 1.2:
            trend = "growing"
        elif second_half <= first_half * 0.8:
            trend = "declining"
        else:
            trend = "stable"
        cover = None
        if primary is not None:
            text = page_info.get(primary.page_id, {}).get("text")
            cover = coverage(q, text) if text else None
        ctr = total_clicks / total_impr
        score, tier, factors = score_opportunity(
            impressions=total_impr, position=position, ctr=ctr, has_page=primary is not None, coverage_value=cover, trend=trend,
            categories=info.categories, benchmark=benchmarks.get(_bucket(position)), min_impressions=min_impr, needs_review=review,
        )
        by_country = countries.get(q, {})
        top_country = country_code or (max(by_country, key=by_country.get) if by_country else None)
        items.append(Opportunity(
            query=q, categories=info.categories, signals=info.signals, word_count=info.word_count, country=top_country, countries=by_country,
            impressions=total_impr, clicks=total_clicks, ctr=ctr, position=position, page=primary,
            other_pages=[s for s in shares[1:] if s.page_id is not None], needs_review=review, coverage=cover, trend=trend,
            score=score, tier=tier, factors=factors,
        ))
        if len(items) >= MAX_QUERIES:
            break

    warnings = []
    cov = data_coverage(db, website.id)
    if cov["rows"] == 0:
        warnings.append("No Search Console data is stored for this project yet. Connect Search Console and sync first.")
    else:
        if cov["first_day"] and date.fromisoformat(cov["first_day"]) > start:
            warnings.append(f"Stored Search Console data starts on {cov['first_day']}; the requested period begins earlier, so results cover less than the full range.")
        if cov["last_day"] and date.fromisoformat(cov["last_day"]) < end:
            warnings.append(f"Stored data ends on {cov['last_day']}: the newest days are not synced yet (Search Console also reports with a delay of a few days).")
    warnings.append("Search Console does not return anonymised or very rare queries, so some long-tail searches never appear.")
    return {"items": items, "warnings": warnings, "coverage": cov, "benchmarks": {k: round(v, 4) for k, v in benchmarks.items()},
            "window": {"start": start.isoformat(), "end": end.isoformat()}}


def _page_info(db: Session, page_ids: set) -> dict:
    if not page_ids:
        return {}
    pages = {p.id: p for p in db.query(Page).filter(Page.id.in_(page_ids)).all()}
    latest = (
        db.query(PageSnapshot.page_id, func.max(PageSnapshot.fetched_at)).filter(PageSnapshot.page_id.in_(page_ids)).group_by(PageSnapshot.page_id).all()
    )
    out: dict = {}
    for pid, fetched in latest:
        snap = db.query(PageSnapshot).filter(PageSnapshot.page_id == pid, PageSnapshot.fetched_at == fetched).first()
        headings = " ".join(h for group in (snap.headings_json or {}).values() for h in group)
        out[pid] = {"url": pages[pid].canonical_url if pid in pages else None, "text": f"{snap.title or ''} {headings}".strip()}
    for pid, page in pages.items():
        out.setdefault(pid, {"url": page.canonical_url, "text": None})
    return out


def filter_and_sort(
    items: list[Opportunity], *, category: str | None = None, tier: str | None = None, min_impressions: int | None = None,
    max_ctr: float | None = None, max_position: float | None = None, min_position: float | None = None, min_score: int | None = None,
    search: str | None = None, sort: str = "score", descending: bool = True,
) -> list[Opportunity]:
    if category and category not in CATEGORIES:
        raise ValueError(f"Unknown category '{category}'.")
    if tier and tier not in TIERS:
        raise ValueError(f"Unknown tier '{tier}'.")
    out = [
        i for i in items
        if (not category or category in i.categories) and (not tier or i.tier == tier)
        and (min_impressions is None or i.impressions >= min_impressions) and (max_ctr is None or i.ctr <= max_ctr)
        and (max_position is None or i.position <= max_position) and (min_position is None or i.position >= min_position)
        and (min_score is None or i.score >= min_score) and (not search or search.lower() in i.query.lower())
    ]
    keys = {"score": lambda i: i.score, "impressions": lambda i: i.impressions, "clicks": lambda i: i.clicks, "ctr": lambda i: i.ctr,
            "position": lambda i: i.position, "query": lambda i: i.query}
    if sort not in keys:
        raise ValueError(f"Cannot sort by '{sort}'.")
    return sorted(out, key=keys[sort], reverse=descending)
