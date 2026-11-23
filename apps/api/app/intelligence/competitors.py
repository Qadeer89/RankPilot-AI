"""Competitor structure comparison from public pages RankPilot already crawled (CompetitorPageSnapshot) against this site's own crawl.
Only what is observable on public pages: page counts crawled, typical word count, share of pages with structured data, headings per page,
and topic terms the competitor uses that this site's titles/headings do not. It never reports competitor traffic, rankings, backlinks or
keyword volumes, which cannot be known without paid data."""

from __future__ import annotations

import statistics
from collections import Counter

from sqlalchemy.orm import Session

from app.ai_search.terms import content_terms
from app.intelligence.common import store
from app.keywords.seed_generation import _latest_snapshots
from app.models.competitor import CompetitorDomain, CompetitorPageSnapshot
from app.models.website import Website

VERSION = "competitor-structure-v1"


def _stats(rows) -> dict:
    ok = [r for r in rows if r["words"] is not None]
    if not ok:
        return {"pages": 0}
    return {"pages": len(ok), "median_words": statistics.median(r["words"] for r in ok), "structured_data_share": round(sum(1 for r in ok if r["schema"]) / len(ok), 2),
            "avg_h2_per_page": round(sum(r["h2"] for r in ok) / len(ok), 1)}


def analyze(db: Session, website: Website, *, save: bool = True) -> dict:
    own_rows, own_terms = [], set()
    for s in _latest_snapshots(db, website.id):
        if not 200 <= (s.status_code or 0) < 300:
            continue
        h = s.headings_json or {}
        own_rows.append({"words": s.word_count, "schema": any(b.get("parsed") for b in (s.schema_json or [])), "h2": len(h.get("h2", []))})
        own_terms |= content_terms(" ".join([s.title or "", *h.get("h1", []), *h.get("h2", [])]))
    comps = db.query(CompetitorDomain).filter_by(website_id=website.id).all()
    out = []
    for c in comps:
        pages = db.query(CompetitorPageSnapshot).filter_by(competitor_domain_id=c.id).filter(CompetitorPageSnapshot.fetch_error.is_(None)).all()
        rows, terms = [], Counter()
        for p in pages:
            h = p.headings_json or {}
            rows.append({"words": p.word_count, "schema": p.has_structured_data, "h2": len(h.get("h2", []))})
            terms.update(content_terms(" ".join([p.title or "", *h.get("h1", []), *h.get("h2", [])])))
        gaps = [t for t, _ in terms.most_common(60) if t not in own_terms][:15]
        out.append({"domain": c.domain, "last_analyzed_at": c.last_analyzed_at.isoformat() if c.last_analyzed_at else None, **_stats(rows),
                    "topic_terms_missing_from_your_site": gaps, "status": "analyzed" if rows else "not_available"})
    res = {"available": bool(out), "data_source": "Verified from public competitor pages RankPilot crawled", "yours": _stats(own_rows), "competitors": out,
           "reason": None if out else "No competitors added yet. Add a competitor domain and run its analysis.",
           "not_available": ["Competitor traffic", "Competitor rankings", "Competitor backlinks", "Keyword volume and difficulty"]}
    if save and out:
        row = store(db, website, "competitor_structure", VERSION, None, None, res)
        res = {"id": str(row.id), "computed_at": row.computed_at.isoformat(), "formula_version": VERSION, **res}
    return res
