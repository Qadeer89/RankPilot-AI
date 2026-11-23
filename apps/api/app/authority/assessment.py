"""RankPilot Domain Quality Assessment and Authority Signals.

An original, transparent assessment computed ONLY from data RankPilot already holds (the crawl, the stored snapshots,
Search Console totals). It is not DR, DA, AS, TF or CF, it is not a Google score, and it knows nothing about links from
other websites. Every signal states how it was computed, from which inputs, and whether it could be computed at all; a
signal with no data is "not available" and is left out of the average rather than counted as zero.

Reproducibility: `compute()` is a pure function of the `inputs` it returns, and `score_from_inputs()` re-derives every
number from stored `inputs_json`, which the tests check."""

from __future__ import annotations

from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.ai_search.terms import content_terms
from app.history import snapshots as snap  # noqa: F401  (the history package owns the baseline rules)
from app.keywords.seed_generation import _latest_snapshots
from app.models.authority import AuthorityAssessment
from app.models.history import ProjectMetricHistory
from app.models.page import IndexabilityState, Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.website import Website

FORMULA_VERSION = "authority-v1"
THIN_WORDS = 300
WEIGHTS = {  # documented in docs/RANKPILOT_SCORING_METHODOLOGY.md; they sum to 1.0
    "internal_link_strength": 0.20, "content_coverage": 0.15, "topical_consistency": 0.10, "crawl_health": 0.15,
    "indexability_health": 0.15, "organic_visibility": 0.10, "structure_quality": 0.10, "content_freshness": 0.05,
}
LABELS = {
    "internal_link_strength": "Internal Link Strength", "content_coverage": "Content Coverage", "topical_consistency": "Topical Consistency",
    "crawl_health": "Crawl Health", "indexability_health": "Indexability Health", "organic_visibility": "Organic Visibility",
    "structure_quality": "Website Structure Quality", "content_freshness": "Content Freshness",
}


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, x))


def _norm(url: str) -> str:
    p = urlsplit(url)
    return f"{p.netloc.lower()}{p.path.rstrip('/') or '/'}"


def _graph(pages: list[Page], snaps: dict) -> dict:
    """Inbound counts and click depth from the stored internal links of each page's latest snapshot."""
    by_norm = {_norm(p.normalized_url): p.id for p in pages}
    inbound: Counter = Counter()
    out: dict = {p.id: set() for p in pages}
    for p in pages:
        s = snaps.get(p.id)
        for link in (s.internal_links_json if s else []) or []:
            target = by_norm.get(_norm(link if isinstance(link, str) else link.get("url", "")))
            if target and target != p.id and target not in out[p.id]:
                out[p.id].add(target)
                inbound[target] += 1
    home = next((p for p in pages if urlsplit(p.normalized_url).path in ("", "/")), None)
    depth: dict = {}
    if home is not None:
        depth[home.id] = 0
        queue = deque([home.id])
        while queue:
            cur = queue.popleft()
            for nxt in out[cur]:
                if nxt not in depth:
                    depth[nxt] = depth[cur] + 1
                    queue.append(nxt)
    return {"inbound": inbound, "depth": depth, "home": home.id if home else None}


def collect_inputs(db: Session, website: Website, *, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    pages = db.query(Page).filter(Page.website_id == website.id).all()
    snaps = {s.page_id: s for s in _latest_snapshots(db, website.id)}
    ok_pages = [p for p in pages if (p.last_status_code or 0) in range(200, 300)]
    g = _graph(pages, snaps)
    inbound, depth, home = g["inbound"], g["depth"], g["home"]
    indexable = [p for p in ok_pages if p.indexability_state == IndexabilityState.indexable]
    inputs: dict = {
        "pages_discovered": len(pages), "pages_ok": len(ok_pages), "pages_indexable": len(indexable),
        "pages_non_2xx": len(pages) - len(ok_pages), "pages_noindex": sum(1 for p in pages if p.indexability_state == IndexabilityState.noindex),
        "pages_blocked_by_robots": sum(1 for p in pages if p.indexability_state == IndexabilityState.blocked_by_robots),
    }
    # internal links
    judged = [p for p in ok_pages if p.id != home]
    orphans = [p for p in judged if inbound.get(p.id, 0) == 0]
    well_linked = [p for p in judged if inbound.get(p.id, 0) >= 3]
    inputs.update({"pages_judged_for_links": len(judged), "orphan_pages": len(orphans), "pages_with_3plus_inlinks": len(well_linked),
                   "avg_inlinks": round(sum(inbound.get(p.id, 0) for p in judged) / len(judged), 2) if judged else None,
                   "home_found": home is not None})
    # depth
    reached = [depth[p.id] for p in ok_pages if p.id in depth]
    inputs.update({"pages_reached_from_home": len(reached), "max_depth": max(reached) if reached else None,
                   "avg_depth": round(sum(reached) / len(reached), 2) if reached else None, "pages_within_depth_3": sum(1 for d in reached if d <= 3)})
    # content
    words = [snaps[p.id].word_count for p in ok_pages if p.id in snaps]
    fingerprints = Counter(snaps[p.id].content_fingerprint for p in ok_pages if p.id in snaps and snaps[p.id].content_fingerprint)
    inputs.update({"pages_with_content_data": len(words), "pages_thin": sum(1 for w in words if w < THIN_WORDS),
                   "pages_in_duplicate_groups": sum(n for n in fingerprints.values() if n > 1)})
    # topical consistency: share of pages whose title/H1 uses at least one of the site's own most common terms
    term_pages: Counter = Counter()
    page_terms = {}
    for p in ok_pages:
        s = snaps.get(p.id)
        if not s:
            continue
        t = content_terms(" ".join([s.title or "", *((s.headings_json or {}).get("h1") or [])]))
        page_terms[p.id] = t
        term_pages.update(t)
    top = [t for t, _ in term_pages.most_common(8)]
    inputs.update({"pages_with_titles": len(page_terms), "site_top_terms": top,
                   "pages_using_a_top_term": sum(1 for t in page_terms.values() if t & set(top)) if top else 0})
    # crawl health: broken internal links from findings
    broken = db.query(func.count(func.distinct(SEOFinding.page_id))).filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open,
                                                                          SEOFinding.rule_code == "BROKEN_INTERNAL_LINK").scalar() or 0
    inputs["pages_with_broken_internal_links"] = int(broken)
    # organic visibility (Search Console property totals, last 28 days with data)
    end = db.query(func.max(ProjectMetricHistory.metric_date)).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console",
                                                                       ProjectMetricHistory.scope_type == "property").scalar()
    if end is not None:
        rows = db.query(ProjectMetricHistory).filter(ProjectMetricHistory.website_id == website.id, ProjectMetricHistory.source == "google_search_console",
                                                     ProjectMetricHistory.scope_type == "property", ProjectMetricHistory.metric_date > end - timedelta(days=28)).all()
        inputs.update({"gsc_days_with_data_28d": len(rows), "gsc_clicks_28d": sum(r.clicks for r in rows), "gsc_impressions_28d": sum(r.impressions for r in rows)})
        from app.models.keyword_observation import KeywordObservation
        shown = db.query(func.count(func.distinct(KeywordObservation.page_id))).filter(KeywordObservation.website_id == website.id, KeywordObservation.page_id.isnot(None),
                                                                                    KeywordObservation.date > end - timedelta(days=28), KeywordObservation.impressions > 0).scalar() or 0
        inputs["pages_with_impressions_28d"] = int(shown)
    else:
        inputs.update({"gsc_days_with_data_28d": 0, "gsc_clicks_28d": None, "gsc_impressions_28d": None, "pages_with_impressions_28d": None})
    # freshness: share of pages whose content changed (fingerprint differs between snapshots at least 7 days apart) in the last 90 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    snap_rows = (db.query(PageSnapshot.page_id, PageSnapshot.content_fingerprint, PageSnapshot.fetched_at).join(Page, Page.id == PageSnapshot.page_id)
                 .filter(Page.website_id == website.id, PageSnapshot.fetched_at >= cutoff).all())
    per_page: dict = {}
    for pid, fp, at in snap_rows:
        per_page.setdefault(pid, []).append((at, fp))
    spans = [max(a for a, _ in v) - min(a for a, _ in v) for v in per_page.values() if len(v) > 1]
    observed_days = max((s.days for s in spans), default=0)
    changed = sum(1 for v in per_page.values() if len({fp for _, fp in v if fp}) > 1)
    inputs.update({"history_days_observed": observed_days, "pages_with_changed_content_90d": changed, "pages_with_history": len(per_page)})
    return inputs


def score_from_inputs(inputs: dict) -> list[dict]:
    """The eight signals, each 0-100 or None (not available), re-derivable from `inputs` alone."""
    def sig(key: str, value: float | None, how: str, detail: dict | None = None, note: str | None = None) -> dict:
        return {"key": key, "label": LABELS[key], "value": None if value is None else round(_clamp(value), 1), "weight": WEIGHTS[key],
                "status": "calculated" if value is not None else "not_available", "how": how, "inputs": detail or {}, "note": note}

    i = inputs
    n_j = i["pages_judged_for_links"]
    link = None
    if n_j >= 3 and i["home_found"]:
        orphan_share = i["orphan_pages"] / n_j
        strong_share = i["pages_with_3plus_inlinks"] / n_j
        link = 100 * (0.6 * (1 - orphan_share) + 0.4 * strong_share)
    coverage = None
    if i["pages_with_content_data"]:
        n = i["pages_with_content_data"]
        coverage = 100 * (0.7 * (1 - i["pages_thin"] / n) + 0.3 * (1 - i["pages_in_duplicate_groups"] / n))
    topical = None
    if i["pages_with_titles"] >= 5 and i["site_top_terms"]:
        topical = 100 * i["pages_using_a_top_term"] / i["pages_with_titles"]
    crawl = None
    if i["pages_discovered"]:
        crawl = 100 * (0.6 * (i["pages_ok"] / i["pages_discovered"]) + 0.4 * (1 - min(i["pages_with_broken_internal_links"] / max(i["pages_ok"], 1), 1)))
    index = None
    if i["pages_ok"]:
        index = 100 * (i["pages_indexable"] / i["pages_ok"])
    organic = None
    if i["gsc_days_with_data_28d"] and i["pages_with_impressions_28d"] is not None and i["pages_indexable"]:
        organic = 100 * min(i["pages_with_impressions_28d"] / i["pages_indexable"], 1)
    structure = None
    if i["pages_reached_from_home"] >= 3:
        structure = 100 * (0.7 * (i["pages_within_depth_3"] / i["pages_reached_from_home"]) + 0.3 * (1 - min(max((i["max_depth"] or 0) - 3, 0) / 5, 1)))
    fresh = None
    if i["history_days_observed"] >= 30 and i["pages_with_history"]:
        fresh = 100 * min(i["pages_with_changed_content_90d"] / i["pages_with_history"] / 0.25, 1)  # 25% of pages updated in 90 days is full marks
    return [
        sig("internal_link_strength", link, "60% pages that have at least one internal link pointing to them + 40% pages with 3 or more, judged over crawled pages except the home page.",
            {"pages_judged": n_j, "orphan_pages": i["orphan_pages"], "pages_with_3plus_inlinks": i["pages_with_3plus_inlinks"], "avg_inlinks": i["avg_inlinks"]},
            None if link is not None else "Needs at least 3 crawled pages and a found home page."),
        sig("content_coverage", coverage, "70% pages with at least 300 words + 30% pages not sharing identical content with another page.",
            {"pages": i["pages_with_content_data"], "thin": i["pages_thin"], "in_duplicate_groups": i["pages_in_duplicate_groups"]}),
        sig("topical_consistency", topical, "Share of pages whose title or H1 uses at least one of the site's own 8 most common terms (a heuristic for staying on topic).",
            {"top_terms": i["site_top_terms"], "pages": i["pages_with_titles"], "pages_on_topic": i["pages_using_a_top_term"]}, None if topical is not None else "Needs at least 5 crawled pages with titles."),
        sig("crawl_health", crawl, "60% pages answering with a 2xx status + 40% pages without a broken internal link.",
            {"pages": i["pages_discovered"], "ok": i["pages_ok"], "non_2xx": i["pages_non_2xx"], "pages_with_broken_internal_links": i["pages_with_broken_internal_links"]}),
        sig("indexability_health", index, "Share of 2xx pages that search engines are allowed to index (no noindex, not blocked by robots.txt).",
            {"ok_pages": i["pages_ok"], "indexable": i["pages_indexable"], "noindex": i["pages_noindex"], "blocked_by_robots": i["pages_blocked_by_robots"]}),
        sig("organic_visibility", organic, "Share of indexable pages that had at least one Search Console impression in the last 28 days of stored data.",
            {"pages_with_impressions": i["pages_with_impressions_28d"], "indexable": i["pages_indexable"], "clicks_28d": i["gsc_clicks_28d"], "impressions_28d": i["gsc_impressions_28d"]},
            None if organic is not None else "Needs Search Console data."),
        sig("structure_quality", structure, "70% pages reachable within 3 clicks of the home page + 30% penalty-free share for how far the deepest page sits beyond depth 3.",
            {"reached": i["pages_reached_from_home"], "within_depth_3": i["pages_within_depth_3"], "max_depth": i["max_depth"], "avg_depth": i["avg_depth"]}),
        sig("content_freshness", fresh, "Share of pages whose content changed between crawls in the last 90 days; 25% of pages updated counts as full marks. Needs 30+ days of crawl history.",
            {"history_days": i["history_days_observed"], "changed": i["pages_with_changed_content_90d"], "pages_with_history": i["pages_with_history"]},
            None if fresh is not None else f"Needs 30 days of crawl history (have {i['history_days_observed']})."),
    ]


def combine(signals: list[dict]) -> tuple[float | None, float, str]:
    """Weighted average of the signals that have data. Returns (score, coverage = share of weight available, confidence)."""
    have = [s for s in signals if s["value"] is not None]
    available = sum(s["weight"] for s in have)
    if not have or available == 0:
        return None, 0.0, "none"
    score = sum(s["weight"] * s["value"] for s in have) / available
    for s in signals:
        s["contribution"] = round(s["weight"] * s["value"] / available, 2) if s["value"] is not None else None
    coverage = round(available, 2)
    confidence = "high" if coverage >= 0.85 else "medium" if coverage >= 0.6 else "low"
    return round(score, 1), coverage, confidence


def compute(db: Session, website: Website, crawl_job_id=None) -> AuthorityAssessment:
    """Append one assessment row (idempotent per crawl)."""
    if crawl_job_id is not None:
        existing = db.query(AuthorityAssessment).filter_by(website_id=website.id, crawl_job_id=crawl_job_id).one_or_none()
        if existing is not None:
            return existing
    inputs = collect_inputs(db, website)
    signals = score_from_inputs(inputs)
    score, coverage, confidence = combine(signals)
    row = AuthorityAssessment(website_id=website.id, crawl_job_id=crawl_job_id, computed_at=datetime.now(timezone.utc), formula_version=FORMULA_VERSION,
                              domain_quality=score, coverage=coverage, confidence=confidence, signals_json=signals, inputs_json=inputs)
    db.add(row)
    db.flush()
    return row


def compare(previous: AuthorityAssessment | None, current: AuthorityAssessment) -> dict:
    """What changed between two assessments, per signal, with the input numbers that explain it. Never calls a missing value zero."""
    if previous is None:
        return {"available": False, "reason": "This is the first assessment, so there is nothing to compare with yet."}
    prev = {s["key"]: s for s in previous.signals_json}
    rows = []
    for s in current.signals_json:
        before = prev.get(s["key"], {}).get("value")
        after = s["value"]
        rows.append({"key": s["key"], "label": s["label"], "previous": before, "current": after,
                     "change": round(after - before, 1) if before is not None and after is not None else None,
                     "status": "not_available" if before is None or after is None else "improved" if after > before else "declined" if after < before else "unchanged"})
    d = None if previous.domain_quality is None or current.domain_quality is None else round(current.domain_quality - previous.domain_quality, 1)
    formula_changed = previous.formula_version != current.formula_version
    return {"available": True, "previous_at": previous.computed_at.isoformat(), "domain_quality_change": d, "signals": rows, "formula_changed": formula_changed,
            "note": "The two assessments were computed with different formula versions, so they are not directly comparable." if formula_changed else None}
