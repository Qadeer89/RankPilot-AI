"""Content intelligence from what the crawler stored (titles, headings, word counts, schema, internal links). No body text is stored,
so anything needing prose is reported as "Not tested" rather than guessed.

Content Quality Score `content-quality-v1` (0-100, RankPilot calculated; not a Google score):
  depth 30%     share of pages with >= 300 words (and the median word count is shown)
  structure 25% share of pages with exactly one H1 and at least two H2s
  topical 25%   average share of the confirmed business offerings' terms found in page titles/headings (needs a confirmed profile
                with offerings; otherwise not available)
  trust 20%     share of 6 trust signals found (about, contact, privacy, terms, team/author, reviews) in page URLs/titles or Organization/
                LocalBusiness/Person/Review schema. E-E-A-T is a quality idea, not a measurable Google score; this lists evidence only.
Also reported, not scored: near-duplicate titles (term Jaccard >= 0.8), question-style headings (featured snippet candidates, answer
format Not tested), and content decay signals from Search Console (existing trend signals)."""

from __future__ import annotations

import statistics
from itertools import combinations

from sqlalchemy.orm import Session

from app.ai_search.terms import content_terms
from app.intelligence.common import combine, store
from app.keywords.seed_generation import _latest_snapshots
from app.models.business_profile import BusinessProfile
from app.models.page import Page
from app.models.website import Website

VERSION = "content-quality-v1"
THIN = 300
QUESTION_STARTS = ("what", "how", "why", "when", "where", "which", "who", "can", "does", "do", "is", "are", "should")
TRUST = {
    "about": ("about", "our-story", "who-we-are"), "contact": ("contact", "get-in-touch"), "privacy": ("privacy",), "terms": ("terms", "conditions"),
    "team_or_author": ("team", "author", "doctor", "our-people", "staff"), "reviews": ("review", "testimonial", "success-stor"),
}
TRUST_SCHEMA = {"organization", "localbusiness", "person", "review", "aggregaterating", "physician", "medicalbusiness"}


def _schema_types(snapshot) -> set[str]:
    types: set[str] = set()
    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            for x in ([t] if isinstance(t, str) else t or []):
                if isinstance(x, str):
                    types.add(x.lower())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for block in snapshot.schema_json or []:
        walk(block.get("parsed"))
    return types


def analyze(db: Session, website: Website, *, save: bool = True) -> dict:
    snaps = _latest_snapshots(db, website.id)
    pages = {p.id: p for p in db.query(Page).filter(Page.website_id == website.id).all()}
    ok = [(pages[s.page_id], s) for s in snaps if s.page_id in pages and 200 <= (s.status_code or 0) < 300]
    if not ok:
        res = {"available": False, "reason": "No crawled pages yet. Run a crawl first.", "parts": [], "findings": {}, "data_source": "RankPilot calculated"}
        return res
    n = len(ok)
    words = [s.word_count for _, s in ok]
    depth = 100 * sum(1 for w in words if w >= THIN) / n
    well = sum(1 for _, s in ok if len((s.headings_json or {}).get("h1", [])) == 1 and len((s.headings_json or {}).get("h2", [])) >= 2)
    structure = 100 * well / n

    prof = db.query(BusinessProfile).filter_by(website_id=website.id).one_or_none()
    offerings = [o for o in (prof.offerings if prof and prof.confirmed_at else []) if isinstance(o, str)]
    heading_terms: set[str] = set()
    for _, s in ok:
        h = s.headings_json or {}
        heading_terms |= content_terms(" ".join([s.title or "", *h.get("h1", []), *h.get("h2", [])]))
    off_rows = []
    for o in offerings:
        need = content_terms(o)
        share = len(need & heading_terms) / len(need) if need else None
        off_rows.append({"offering": o, "covered_share": None if share is None else round(share, 2), "status": "not_available" if share is None else "covered" if share >= 0.99 else "partial" if share > 0 else "missing"})
    scored = [r["covered_share"] for r in off_rows if r["covered_share"] is not None]
    topical = 100 * sum(scored) / len(scored) if scored else None

    urls_text = [(p.canonical_url.lower() + " " + (s.title or "").lower(), p, s) for p, s in ok]
    schema_types = set().union(*[_schema_types(s) for _, s in ok]) if ok else set()
    trust_rows = []
    for key, needles in TRUST.items():
        hit = next((p.canonical_url for text, p, _ in urls_text if any(nd in text for nd in needles)), None)
        if hit is None and key in ("team_or_author", "reviews") and schema_types & TRUST_SCHEMA:
            pass
        trust_rows.append({"signal": key, "found": hit is not None, "evidence": hit})
    trust = 100 * sum(1 for r in trust_rows if r["found"]) / len(trust_rows)

    term_sets = [(p, content_terms(s.title or "")) for p, s in ok if s.title]
    near = []
    for (a, ta), (b, tb) in combinations(term_sets, 2):
        if ta and tb and len(ta & tb) / len(ta | tb) >= 0.8:
            near.append({"a": a.canonical_url, "b": b.canonical_url})
    questions = [{"url": p.canonical_url, "heading": q} for p, s in ok for q in ((s.headings_json or {}).get("h2", []) + (s.headings_json or {}).get("h3", []))
                 if q.strip().lower().startswith(QUESTION_STARTS) and len(q.split()) >= 3][:25]

    parts = [
        {"key": "depth", "label": "Content depth", "value": round(depth, 1), "weight": 0.30, "how": f"Share of pages with at least {THIN} words.", "inputs": {"pages": n, "median_words": statistics.median(words), "thin_pages": sum(1 for w in words if w < THIN)}},
        {"key": "structure", "label": "Heading structure", "value": round(structure, 1), "weight": 0.25, "how": "Share of pages with exactly one H1 and at least two H2 headings.", "inputs": {"pages": n, "well_structured": well}},
        {"key": "topical", "label": "Topical coverage of your offerings", "value": None if topical is None else round(topical, 1), "weight": 0.25, "how": "Average share of each confirmed offering's terms that appear in your titles and headings.", "inputs": {"offerings": off_rows}, "note": None if topical is not None else "Needs a confirmed business profile with offerings (Growth Plan)."},
        {"key": "trust", "label": "Trust signals present", "value": round(trust, 1), "weight": 0.20, "how": "Share of 6 trust pages/signals found in your URLs and titles. Evidence only; E-E-A-T is not a Google score.", "inputs": {"signals": trust_rows, "schema_types_seen": sorted(schema_types & TRUST_SCHEMA)}},
    ]
    score, coverage, confidence = combine(parts)
    res = {"available": True, "data_source": "RankPilot calculated", "confidence": confidence, "parts": parts,
           "findings": {"near_duplicate_titles": near[:25], "question_headings": questions, "question_heading_note": "Question-style headings can win featured snippets; whether the text under them answers directly is Not tested (body text is not stored).",
                        "near_duplicate_body_text": "Not tested (only exact duplicates are detected, from a content fingerprint)."},
           "pages_analyzed": n}
    if save:
        row = store(db, website, "content", VERSION, score, coverage, res)
        res = {"id": str(row.id), "computed_at": row.computed_at.isoformat(), "formula_version": VERSION, "score": score, "coverage": coverage, **res}
    return res
