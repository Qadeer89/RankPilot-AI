"""Live validation of the AI Search Opportunity Finder against a project's REAL Search Console data.

Run on the VPS (real database, real OpenAI key, outbound internet):

    .venv/bin/python scripts/validate_ai_search.py --site gulsrehab --window 3m
    .venv/bin/python scripts/validate_ai_search.py --site gulsrehab --window 3m --analyze-top 1 --save

Nothing is mocked and nothing is invented. If the project has no suitable query the script says
"BLOCKED: insufficient real data" and stops. It never approves, implements or publishes anything; with
--save it stores the analysis (a recommendation awaiting your review) so you can see it in the dashboard.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai_search import discovery, service  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.website import Website  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, help="part of the project's hostname, e.g. gulsrehab")
    ap.add_argument("--window", default="28d", choices=list(discovery.WINDOW_PRESETS))
    ap.add_argument("--country", default=None)
    ap.add_argument("--min-impressions", type=int, default=20, help="smallest query worth a live AI analysis")
    ap.add_argument("--analyze-top", type=int, default=0, help="analyse the N best opportunities with the real page and real AI")
    ap.add_argument("--save", action="store_true", help="keep the analysis (otherwise the transaction is rolled back)")
    ap.add_argument("--out", default="ai_search_validation.json")
    args = ap.parse_args()

    db = SessionLocal()
    sites = db.query(Website).filter(Website.hostname.ilike(f"%{args.site}%")).all()
    if len(sites) != 1:
        print(f"Expected exactly one project matching '{args.site}', found {len(sites)}.")
        return 2
    site = sites[0]
    start, end = discovery.resolve_window(args.window, None, None)
    report: dict = {"site": site.hostname, "window": [start.isoformat(), end.isoformat()], "analyses": []}

    print(f"Project: {site.hostname}  (Search Console property: {site.search_console_site_url or 'NOT SET'})")
    result = discovery.discover(db, site, start=start, end=end, country=args.country)
    cov = result["coverage"]
    print(f"Stored Search Console rows: {cov['rows']}  first day: {cov['first_day']}  last day: {cov['last_day']}")
    for w in result["warnings"]:
        print(f"  note: {w}")
    items = result["items"]
    report["coverage"], report["classified_queries"] = cov, len(items)
    if cov["rows"] == 0 or not items:
        print("BLOCKED: insufficient real data. No Search Console rows (or no conversational/question/long-tail queries) are stored for this window.")
        print("Run a Search Console sync (dashboard or the scheduler) and, for 3m/6m windows, make sure enough history has been synced.")
        report["verdict"] = "blocked_no_data"
        Path(args.out).write_text(json.dumps(report, indent=1, default=str))
        return 3

    by_cat = Counter(c for i in items for c in i.categories)
    by_tier = Counter(i.tier for i in items)
    print(f"Classified queries: {len(items)}   by category: {dict(by_cat)}   by tier: {dict(by_tier)}")
    report["by_category"], report["by_tier"], report["benchmarks"] = dict(by_cat), dict(by_tier), result["benchmarks"]
    print("\nTop opportunities (real data, explainable score):")
    ranked = discovery.filter_and_sort(items, min_impressions=args.min_impressions)
    for op in ranked[:15]:
        print(f"  [{op.score:3d}] {op.tier:20s} impr={op.impressions:5d} clicks={op.clicks:4d} pos={op.position:5.1f} "
              f"page={'-' if not op.page else op.page.url}  | {op.query}")
    report["top"] = [{"query": o.query, "score": o.score, "tier": o.tier, "impressions": o.impressions, "clicks": o.clicks,
                      "position": round(o.position, 1), "page": o.page.url if o.page else None, "factors": o.factors} for o in ranked[:15]]

    candidates = [o for o in ranked if o.page is not None and not o.needs_review][: args.analyze_top]
    if args.analyze_top and not candidates:
        print("\nBLOCKED: no query with meaningful impressions, a known landing page and a single owning page. Nothing was analysed.")
        report["verdict"] = "blocked_no_suitable_query"
    for op in candidates:
        print(f"\nAnalysing: {op.query!r} -> {op.page.url}")
        try:
            finding = service.analyse(db, site, query=op.query, country=args.country, window=(start, end))
        except service.AnalysisError as exc:
            print(f"  FAIL: {exc.message}")
            report["analyses"].append({"query": op.query, "error": exc.message})
            continue
        print(f"  page readable: {finding.content_available}   answer on page: {finding.answer_analysis.get('level')} ({finding.answer_analysis.get('reason')})")
        print(f"  readiness: {finding.readiness_json.get('label')} {finding.readiness_json.get('passed')}/{finding.readiness_json.get('total')}  AI visibility: unmeasured")
        print(f"  AI status: {finding.ai_status} {finding.ai_error or ''}")
        if finding.draft_json:
            print(f"  suggested heading: {finding.draft_json['suggested_heading']}")
            print(f"  direct answer:     {finding.draft_json['direct_answer']}")
            print(f"  needs owner input: {finding.draft_json['needs_owner_input']}")
            for c in finding.quality_json["checks"]:
                print(f"    {c['status']:5s} {c['check']}: {c['detail']}")
            print(f"  quality blocked: {finding.quality_json['blocked']}   (recommendation stays 'open' until a person approves it)")
        report["analyses"].append({"query": op.query, "page": op.page.url, "answer": finding.answer_analysis, "readiness": finding.readiness_json,
                                   "ai_status": finding.ai_status, "draft": finding.draft_json, "quality": finding.quality_json})
    if candidates:
        report.setdefault("verdict", "analysed")
    if args.save:
        db.commit()
        print("\nSaved. Open the project's Keyword Intelligence -> AI Search Opportunities tab to review it. Nothing was approved or published.")
    else:
        db.rollback()
        print("\nRolled back (use --save to keep the analysis).")
    Path(args.out).write_text(json.dumps(report, indent=1, default=str))
    print(f"Report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
