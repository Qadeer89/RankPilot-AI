"""Keyword clusters and keyword-to-page map from the site's own Search Console queries (no volumes, no difficulty).

Clustering `keyword-cluster-v1`: queries whose stemmed meaningful terms overlap (Jaccard >= 0.5) are joined into one cluster (union-find),
so "back pain physio" and "physio for back pain" group while unrelated queries stay apart. Each query is mapped to the page that earned
the most impressions for it (Verified, Search Console). A cluster whose queries are split across 2+ pages, each with >= 20% of the
cluster's impressions, is reported as a possible cannibalization with the impression split as evidence; it is a lead to review, not proof
that rankings are being lost. Search intent per cluster uses the same deterministic intent rules as the keyword ideas (not AI)."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai_search.terms import content_terms
from app.intelligence.common import store
from app.models.keyword_observation import KeywordObservation
from app.models.page import Page
from app.models.website import Website

VERSION = "keyword-cluster-v1"
WINDOW_DAYS = 28
MIN_IMPRESSIONS = 3
SPLIT_SHARE = 0.20
INTENT_HINTS = [("transactional", ("buy", "price", "cost", "book", "appointment", "order", "near me", "hire")), ("commercial", ("best", "top", "review", "vs", "compare", "affordable")),
                ("informational", ("how", "what", "why", "when", "guide", "symptoms", "causes", "tips"))]


def intent(query: str) -> str:
    q = f" {query.lower()} "
    if query.lower().split()[:1] and query.lower().split()[0] in ("how", "what", "why", "when", "which", "who"):
        return "informational"  # a leading question word wins: "how much does X cost" is a question
    for name, words in INTENT_HINTS:
        if any(f" {w} " in q or (" " in w and w in q) for w in words):
            return name
    return "unclassified"


def cluster(rows: list[dict]) -> list[dict]:
    """rows: {query, page_id, impressions, clicks, position}; one per (query,page). Pure and deterministic."""
    queries = sorted({r["query"] for r in rows})
    terms = {q: content_terms(q) for q in queries}
    parent = {q: q for q in queries}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i, a in enumerate(queries):
        for b in queries[i + 1:]:
            ta, tb = terms[a], terms[b]
            if ta and tb and len(ta & tb) / len(ta | tb) >= 0.5:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = defaultdict(list)
    for q in queries:
        groups[find(q)].append(q)
    out = []
    for members in groups.values():
        mset = set(members)
        sub = [r for r in rows if r["query"] in mset]
        per_page: dict = defaultdict(lambda: {"impressions": 0, "clicks": 0, "wpos": 0.0})
        per_query: dict = defaultdict(lambda: {"impressions": 0, "clicks": 0, "pages": defaultdict(int)})
        for r in sub:
            pp = per_page[r["page_id"]]; pp["impressions"] += r["impressions"]; pp["clicks"] += r["clicks"]; pp["wpos"] += r["position"] * r["impressions"]
            pq = per_query[r["query"]]; pq["impressions"] += r["impressions"]; pq["clicks"] += r["clicks"]; pq["pages"][r["page_id"]] += r["impressions"]
        total = sum(v["impressions"] for v in per_page.values()) or 1
        pages = [{"page_id": pid, "impressions": v["impressions"], "clicks": v["clicks"], "share": round(v["impressions"] / total, 2), "avg_position": round(v["wpos"] / v["impressions"], 1) if v["impressions"] else None}
                 for pid, v in sorted(per_page.items(), key=lambda kv: -kv[1]["impressions"])]
        main = max(members, key=lambda m: per_query[m]["impressions"])
        competing = [p for p in pages if p["share"] >= SPLIT_SHARE and p["page_id"] is not None]
        out.append({"label": main, "intent": intent(main), "queries": [{"query": m, "impressions": per_query[m]["impressions"], "clicks": per_query[m]["clicks"],
                                                                      "mapped_page_id": max(per_query[m]["pages"], key=per_query[m]["pages"].get)} for m in sorted(members, key=lambda m: -per_query[m]["impressions"])],
                    "impressions": total, "clicks": sum(v["clicks"] for v in per_page.values()), "pages": pages, "possible_cannibalization": len(competing) >= 2})
    return sorted(out, key=lambda c: -c["impressions"])


def analyze(db: Session, website: Website, *, save: bool = True) -> dict:
    end = db.query(func.max(KeywordObservation.date)).filter(KeywordObservation.website_id == website.id).scalar()
    if end is None:
        return {"available": False, "reason": "No Search Console query data yet. Connect Search Console and sync.", "clusters": [], "data_source": "Verified (Google Search Console)"}
    agg = (db.query(KeywordObservation.query, KeywordObservation.page_id, func.sum(KeywordObservation.impressions), func.sum(KeywordObservation.clicks),
                    func.sum(KeywordObservation.average_position * KeywordObservation.impressions))
           .filter(KeywordObservation.website_id == website.id, KeywordObservation.date > end - timedelta(days=WINDOW_DAYS))
           .group_by(KeywordObservation.query, KeywordObservation.page_id).all())
    rows = [{"query": q, "page_id": pid, "impressions": int(i), "clicks": int(c or 0), "position": float(wp or 0) / i} for q, pid, i, c, wp in agg if i and i >= MIN_IMPRESSIONS]
    clusters = cluster(rows)
    urls = {p.id: p.canonical_url for p in db.query(Page).filter(Page.website_id == website.id).all()}
    def fix(c):
        c = dict(c)
        c["pages"] = [{**p, "url": urls.get(p["page_id"]), "page_id": str(p["page_id"]) if p["page_id"] else None} for p in c["pages"]]
        c["queries"] = [{**q, "mapped_page_url": urls.get(q["mapped_page_id"]), "mapped_page_id": str(q["mapped_page_id"]) if q["mapped_page_id"] else None} for q in c["queries"]]
        return c
    clusters = [fix(c) for c in clusters][:100]
    res = {"available": bool(clusters), "data_source": "Verified (Google Search Console) + RankPilot calculated", "window_days": WINDOW_DAYS, "clusters": clusters,
           "reason": None if clusters else f"No query reached {MIN_IMPRESSIONS} impressions in the last {WINDOW_DAYS} days.",
           "note": "Search volume and keyword difficulty are Not available without paid data; impressions here are real Google Search Console impressions for your site only. Possible cannibalization is a lead to review, not proof."}
    if save and clusters:
        row = store(db, website, "keyword_clusters", VERSION, None, None, res)
        res = {"id": str(row.id), "computed_at": row.computed_at.isoformat(), "formula_version": VERSION, **res}
    return res
