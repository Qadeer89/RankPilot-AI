"""Ranking Opportunity Score: which real Search Console queries are worth working on first.

Not search volume, not keyword difficulty, not a ranking prediction. It ranks queries the site ALREADY appears for, using only the
site's own Search Console rows (stored as KeywordObservation), so every input is Verified first-party data.

Formula `ranking-opportunity-v1`, per (query, page) over the last 28 days, 0-100:
  demand   (50%)  log10(1+impressions) / log10(1+max impressions in the set)
  headroom (35%)  how much room there is to move: 0 at position <= 3, rising linearly to 1 at 8, flat to 15, then falling to 0.3 by 40
  ctr_gap  (15%)  (typical CTR of this site's own queries in the same position band - this query's CTR) / typical CTR, clamped 0..1;
                  needs >= 5 other queries in the band, otherwise this part is "not available" and the other weights are re-normalised
Queries with fewer than 10 impressions are not scored (too little evidence). Position and CTR are impression-weighted averages.
Limitations: ignores seasonality, intent and difficulty; small sites have few rows; the band CTR is the site's own, not an industry curve."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.website import Website

FORMULA_VERSION = "ranking-opportunity-v1"
WINDOW_DAYS = 28
MIN_IMPRESSIONS = 10
MIN_BAND_PEERS = 5
WEIGHTS = {"demand": 0.50, "headroom": 0.35, "ctr_gap": 0.15}
BANDS = [(1, 3), (3, 6), (6, 10), (10, 15), (15, 20), (20, 30), (30, 100)]


def _band(pos: float) -> int:
    for i, (lo, hi) in enumerate(BANDS):
        if pos <= hi:
            return i
    return len(BANDS) - 1


def headroom(position: float) -> float:
    if position <= 3:
        return 0.0
    if position < 8:
        return (position - 3) / 5
    if position <= 15:
        return 1.0
    return max(0.3, 1 - 0.7 * (position - 15) / 25)


def score_rows(rows: list[dict]) -> list[dict]:
    """rows: {query, page_id, impressions, clicks, position}. Pure, so the score can be re-derived from stored inputs."""
    rows = [r for r in rows if r["impressions"] >= MIN_IMPRESSIONS]
    if not rows:
        return []
    max_log = math.log10(1 + max(r["impressions"] for r in rows))
    ctrs: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        ctrs[_band(r["position"])].append(r["clicks"] / r["impressions"])
    out = []
    for r in rows:
        b = _band(r["position"])
        ctr = r["clicks"] / r["impressions"]
        peers = len(ctrs[b]) - 1
        parts = {"demand": math.log10(1 + r["impressions"]) / max_log if max_log else 0.0, "headroom": headroom(r["position"]), "ctr_gap": None}
        typical = None
        if peers >= MIN_BAND_PEERS:
            typical = median(ctrs[b])
            parts["ctr_gap"] = max(0.0, min(1.0, (typical - ctr) / typical)) if typical > 0 else 0.0
        have = {k: v for k, v in parts.items() if v is not None}
        total_w = sum(WEIGHTS[k] for k in have)
        score = 100 * sum(WEIGHTS[k] * v for k, v in have.items()) / total_w
        out.append({**r, "ctr": round(ctr, 4), "score": round(score, 1), "components": {k: None if v is None else round(v, 3) for k, v in parts.items()},
                    "band_typical_ctr": None if typical is None else round(typical, 4), "confidence": "medium" if r["impressions"] >= 100 and parts["ctr_gap"] is not None else "low",
                    "data_source": "Verified (Google Search Console) + RankPilot calculated"})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def ranking_opportunities(db: Session, website: Website, *, limit: int = 50) -> dict:
    end = db.query(func.max(KeywordObservation.date)).filter(KeywordObservation.website_id == website.id).scalar()
    if end is None:
        return {"available": False, "formula_version": FORMULA_VERSION, "reason": "No Search Console query data yet. Connect Search Console and sync to see opportunities.", "items": []}
    start = end - timedelta(days=WINDOW_DAYS - 1)
    agg = (db.query(KeywordObservation.query, KeywordObservation.page_id, func.sum(KeywordObservation.impressions), func.sum(KeywordObservation.clicks),
                    func.sum(KeywordObservation.average_position * KeywordObservation.impressions))
           .filter(KeywordObservation.website_id == website.id, KeywordObservation.date >= start)
           .group_by(KeywordObservation.query, KeywordObservation.page_id).all())
    rows = [{"query": q, "page_id": pid, "impressions": int(i or 0), "clicks": int(c or 0), "position": round(float(wp or 0) / i, 2)} for q, pid, i, c, wp in agg if i]
    scored = score_rows(rows)
    urls = {p.id: p.canonical_url for p in db.query(Page).filter(Page.website_id == website.id, Page.id.in_([r["page_id"] for r in scored[:limit] if r["page_id"]])).all()}
    items = [{**r, "page_id": str(r["page_id"]) if r["page_id"] else None, "page_url": urls.get(r["page_id"])} for r in scored[:limit]]
    return {"available": bool(items), "formula_version": FORMULA_VERSION, "window": {"from": start.isoformat(), "to": end.isoformat()}, "weights": WEIGHTS,
            "scored_queries": len(scored), "items": items,
            "reason": None if items else f"No query has {MIN_IMPRESSIONS}+ impressions in the last {WINDOW_DAYS} days, so nothing can be scored honestly yet.",
            "label": "Ranks queries your site already appears for, from your own Search Console data. It is not search volume, keyword difficulty or a ranking prediction."}
