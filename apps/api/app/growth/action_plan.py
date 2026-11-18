"""A first-30-days SEO plan built from THIS website's own findings, recommendations and integrations.

Nothing here is a fixed checklist: every item exists because a stored record says so (a count of critical issues, a
connection that is missing, recommendations awaiting review), and each item says what it is based on. The five
stages follow the suggested structure, but the amount of work in each is scaled to the real size of the site, and the
plan states plainly that thirty days does not guarantee any ranking result."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.execution.connections import get_connected_content_connector
from app.growth import unified
from app.history import snapshots as snap
from app.models.business_profile import BusinessProfile
from app.models.competitor import CompetitorDomain
from app.models.keyword_idea import KeywordIdea
from app.models.page import Page
from app.models.seo_finding import FindingSeverity, FindingStatus, SEOFinding
from app.models.website import Website
from app.models.website_connection import ConnectorType

DISCLAIMER = ("This plan lists the work RankPilot found for your website. Completing it does not guarantee higher rankings, traffic or sales within 30 days or any "
              "other time: search engines decide rankings independently, and competition, demand and updates also matter.")
SMALL_SITE, LARGE_SITE_PAGES, LARGE_ISSUES = 20, 300, 150


def _item(text: str, status: str, basis: str, *, count: int | None = None) -> dict:
    return {"text": text, "status": status, "basis": basis, "count": count}


def build(db: Session, website: Website) -> dict:
    snap.ensure_history(db, website)
    baseline = snap.baseline_snapshot(db, website.id)
    pages = db.query(func.count(Page.id)).filter(Page.website_id == website.id).scalar() or 0
    open_q = db.query(SEOFinding).filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open)
    findings = open_q.all()
    critical = [f for f in findings if f.severity == FindingSeverity.critical]
    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule_code] = by_rule.get(f.rule_code, 0) + 1
    top_rules = sorted(by_rule.items(), key=lambda kv: -kv[1])[:5]
    items = unified.build(db, website)
    open_items = [i for i in items if i["stage"] in ("recommended", "reopened", "approved")]
    by_type = lambda t: [i for i in open_items if i["type"] == t]  # noqa: E731
    profile = db.query(BusinessProfile).filter(BusinessProfile.website_id == website.id).one_or_none()
    ideas = db.query(func.count(KeywordIdea.id)).filter(KeywordIdea.website_id == website.id).scalar() or 0
    competitors = db.query(func.count(CompetitorDomain.id)).filter(CompetitorDomain.website_id == website.id).scalar() or 0
    cms = get_connected_content_connector(db, website)
    gsc, ga4 = bool(website.search_console_site_url), bool(website.ga4_property_id)
    applied = [i for i in items if i["stage"] in ("implemented", "validated", "monitoring")]
    on_page_priority = [i for i in by_type("on_page") if i["priority"] in ("critical", "high")]

    # ---- days 1-3: discovery and baseline
    d1 = [
        _item("Website discovery and technical baseline", "done" if baseline else "todo",
              f"{pages} page(s) discovered" + (f"; baseline saved {baseline.created_at.date().isoformat()}" if baseline else "; the first crawl has not finished"), count=pages),
        _item("Confirm what your business is and who it serves", "done" if profile and profile.confirmed_at else "todo",
              "No confirmed business profile yet." if not (profile and profile.confirmed_at) else "Business profile confirmed."),
        _item("Initial keyword discovery", "done" if ideas else "todo", f"{ideas} AI-generated keyword idea(s) stored (suggestions, not verified search data)." if ideas else
              "No keyword ideas generated yet.", count=ideas),
    ]
    if not gsc:
        d1.append(_item("Connect Google Search Console", "todo", "Not connected, so there is no verified search performance to measure."))
    if not ga4:
        d1.append(_item("Connect Google Analytics", "todo", "Not connected, so organic sessions and conversions cannot be measured."))

    # ---- days 4-7: critical technical issues
    d2 = [_item(f"Fix critical issue: {rule.replace('_', ' ').lower()}", "todo", f"{sum(1 for f in critical if f.rule_code == rule)} page(s) affected",
                count=sum(1 for f in critical if f.rule_code == rule)) for rule in sorted({f.rule_code for f in critical})]
    if not d2:
        d2.append(_item("No critical technical issues detected", "done", "Based on the latest crawl."))
    index_rules = [(r, n) for r, n in by_rule.items() if r in ("NOINDEX_DIRECTIVE", "CANONICAL_MISSING", "CANONICAL_MISMATCH", "GOOGLE_INDEXING_BLOCKED", "SITEMAP_URL_ERROR")]
    for rule, n in index_rules:
        d2.append(_item(f"Review indexability: {rule.replace('_', ' ').lower()}", "todo", f"{n} open finding(s)", count=n))

    # ---- days 8-14: on-page and internal linking, products
    d3 = [_item("Implement high-priority on-page improvements", "todo" if on_page_priority else "done",
                f"{len(on_page_priority)} high-priority on-page recommendation(s) awaiting action." if on_page_priority else "No high-priority on-page recommendations open.",
                count=len(on_page_priority))]
    links = by_type("internal_linking")
    if links:
        d3.append(_item("Improve internal linking", "todo", f"{len(links)} internal-linking recommendation(s) open.", count=len(links)))
    if cms == ConnectorType.shopify:
        d3.append(_item("Optimize product and collection pages", "todo", "A Shopify store is connected; its products and collections are the main pages to optimise."))
    if cms is None:
        d3.append(_item("Connect your CMS to apply approved changes from RankPilot", "todo", "No CMS is connected."))

    # ---- days 15-21: content and competitor gaps
    content = by_type("content") + by_type("keyword")
    gaps = by_type("competitor_gap")
    d4 = [_item("Develop supporting content", "todo" if content else "done", f"{len(content)} content/keyword recommendation(s) open." if content else "No content recommendations open.",
                count=len(content)),
          _item("Address competitor content gaps", "todo" if gaps else ("todo" if competitors == 0 else "done"),
                f"{len(gaps)} competitor-gap recommendation(s) open." if gaps else ("No competitors added yet." if competitors == 0 else "No open competitor gaps."), count=len(gaps))]

    # ---- days 22-30: validate and review
    d5 = [_item("Re-crawl the pages you changed and validate the changes", "todo" if applied else "blocked",
                f"{len(applied)} change(s) applied so far." if applied else "Nothing has been applied yet, so there is nothing to validate.", count=len(applied)),
          _item("Review Google search performance", "todo" if gsc else "blocked", "Search Console is connected." if gsc else "Needs Google Search Console."),
          _item("Generate the next improvement plan", "todo", "A new plan is built from the findings at that time.")]

    size = "large" if pages >= LARGE_SITE_PAGES or len(findings) >= LARGE_ISSUES else "small" if pages < SMALL_SITE else "medium"
    pace = {"small": f"With {pages} page(s), much of this can finish sooner than 30 days.",
            "medium": "The stages are sequenced by priority.",
            "large": f"With {pages} page(s) and {len(findings)} open issue(s) this work is sequenced by priority and the later stages may take longer than 30 days."}[size]
    return {
        "generated_from": {"pages": pages, "open_issues": len(findings), "critical_issues": len(critical), "open_recommendations": len(open_items),
                           "top_issue_rules": [{"rule": r, "count": n} for r, n in top_rules]},
        "size_class": size, "pace_note": pace, "disclaimer": DISCLAIMER,
        "stages": [{"days": "1-3", "title": "Discovery and baseline", "items": d1}, {"days": "4-7", "title": "Critical technical issues", "items": d2},
                   {"days": "8-14", "title": "On-page improvements and internal linking", "items": d3}, {"days": "15-21", "title": "Content and competitor gaps", "items": d4},
                   {"days": "22-30", "title": "Validate and review", "items": d5}],
    }
