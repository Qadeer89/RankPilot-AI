"""One recommendation list over RankPilot's different recommendation sources.

RankPilot produces recommendations in two places that grew separately: deterministic "opportunities" from crawl
findings, and "growth recommendations" from Search Console data, AI keyword ideas, competitor pages and the AI
search finder. Customers should see one list with the same fields and one vocabulary, so this read model maps both.
It stores nothing and invents nothing: every field comes from the source record, and priority is derived from
stated rules (a critical finding is Critical; nothing is called Critical on a guess)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.growth_recommendation import GrowthRecommendation, RecommendationStatus
from app.models.history import RecommendationHistory
from app.models.page import Page
from app.models.seo_finding import FindingSeverity, SEOFinding
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website

TYPES = ("technical", "on_page", "content", "keyword", "product", "internal_linking", "competitor_gap")
PRIORITIES = ("critical", "high", "medium", "low")
STAGES = ("identified", "recommended", "approved", "implemented", "validated", "monitoring", "rejected", "dismissed", "failed", "reopened", "resolved_externally")

_OPPORTUNITY_TYPE = {"technical": "technical", "structured_data": "technical", "metadata": "on_page", "images": "on_page", "internal_linking": "internal_linking",
                     "content": "content", "performance": "technical", "growth": "on_page"}
_GROWTH_TYPE = {"improve_existing_page": "on_page", "resolve_cannibalization": "keyword", "refresh_declining_page": "content", "new_content": "content",
                "ai_search_answer": "content"}
_BENEFIT = {"technical": "Crawlability and indexing", "on_page": "Relevance and click-through", "content": "Topical coverage and relevance",
            "keyword": "Search-intent alignment", "product": "Product discoverability", "internal_linking": "Page discovery and relevance",
            "competitor_gap": "Topical coverage"}
_WHY = {"technical": "Technical problems can stop search engines from finding or understanding pages.",
        "on_page": "Titles, descriptions and headings are how search engines and people judge what a page is about.",
        "content": "Content that answers what people search for may improve relevance for that search intent.",
        "keyword": "Pages that compete for the same query can split relevance between them.",
        "product": "Clear product pages may be easier to discover and understand.",
        "internal_linking": "Internal links help search engines and visitors reach and understand pages.",
        "competitor_gap": "Topics competitors cover and this site does not may be an opportunity."}
_ACTIONS = {"identified": ["view_details"], "recommended": ["view_details", "approve", "edit", "dismiss"], "approved": ["view_details", "apply", "edit", "dismiss"],
            "implemented": ["view_details", "validate"], "validated": ["view_details"], "monitoring": ["view_details"], "rejected": ["view_details", "reopen"],
            "dismissed": ["view_details", "reopen"], "failed": ["view_details", "reopen"], "reopened": ["view_details", "approve", "dismiss"],
            "resolved_externally": ["view_details"]}


def _level(value: float, low: float, high: float) -> str:
    return "low" if value < low else "medium" if value < high else "high"


def _opportunity_priority(opp: SEOOpportunity, finding_severity: FindingSeverity | None) -> str:
    if finding_severity == FindingSeverity.critical:
        return "critical"
    score = opp.impact_estimate * opp.confidence / (0.5 + opp.effort_estimate)
    return "high" if score >= 0.45 else "medium" if score >= 0.25 else "low"


def _latest_stages(db: Session, website_id) -> dict[tuple[str, str], str]:
    latest: dict[tuple[str, str], tuple] = {}
    for kind, ref, stage, at in db.query(RecommendationHistory.kind, RecommendationHistory.ref_id, RecommendationHistory.stage,
                                         RecommendationHistory.occurred_at).filter(RecommendationHistory.website_id == website_id):
        if (kind, ref) not in latest or at >= latest[(kind, ref)][0]:
            latest[(kind, ref)] = (at, stage)
    return {k: v[1] for k, v in latest.items()}


def _opportunity_item(opp: SEOOpportunity, page_url: str | None, severity: FindingSeverity | None, kind_type: str) -> dict:
    stage = {OpportunityStatus.open: "recommended", OpportunityStatus.dismissed: "dismissed", OpportunityStatus.completed: "validated",
             OpportunityStatus.resolved: "resolved_externally"}.get(opp.status, "recommended")
    evidence = {k: v for k, v in (opp.evidence_json or {}).items() if isinstance(v, (str, int, float, bool))}
    return {
        "id": f"seo_opportunity:{opp.id}", "kind": "seo_opportunity", "title": opp.title, "affected": page_url, "type": kind_type,
        "problem": opp.rationale, "evidence": evidence, "why_it_matters": _WHY[kind_type],
        "suggested_solution": opp.title, "implementation": (
            "RankPilot drafts the change with AI; you review and approve it in Tasks, and it is applied through your connected CMS and then checked on the live page."
            if opp.risk_tier is not None else "Review the suggested change and apply it."),
        "priority": _opportunity_priority(opp, severity), "effort": _level(opp.effort_estimate, 0.34, 0.67), "benefit_category": _BENEFIT[kind_type],
        "validation": "A re-crawl confirms the issue is no longer detected on the page.", "stage": stage, "actions": _ACTIONS[stage],
        "data_source": "RankPilot crawl",
    }


def _growth_item(rec: GrowthRecommendation, page_url: str | None, stage_log: dict) -> dict:
    kind_type = _GROWTH_TYPE.get(rec.recommendation_type, "on_page")
    if rec.recommendation_type == "new_content" and rec.data_source == "competitor_public_content":
        kind_type = "competitor_gap"
    elif rec.recommendation_type == "new_content" and rec.data_source == "ai_generated_idea":
        kind_type = "keyword"
    default_stage = {RecommendationStatus.open: "recommended", RecommendationStatus.approved: "approved", RecommendationStatus.rejected: "rejected",
                     RecommendationStatus.done: "implemented"}[rec.status]
    logged = stage_log.get(("growth_recommendation", str(rec.id))) or stage_log.get(("ai_search_finding", str((rec.evidence_json or {}).get("ai_search_finding_id"))))
    stage = logged if logged in STAGES and rec.status != RecommendationStatus.open else default_stage
    evidence = {k: v for k, v in (rec.evidence_json or {}).items() if isinstance(v, (str, int, float, bool))}
    return {
        "id": f"growth_recommendation:{rec.id}", "kind": "growth_recommendation", "title": rec.title, "affected": page_url or rec.proposed_url, "type": kind_type,
        "problem": rec.problem, "evidence": evidence, "why_it_matters": rec.expected_benefit, "suggested_solution": rec.recommended_action,
        "implementation": ("Send it for an AI draft, approve the draft, and RankPilot applies and verifies it." if rec.automation_available
                           else "Apply this by hand in your CMS, then mark it done so it can be checked and tracked."),
        "priority": rec.priority.value, "effort": rec.difficulty.value, "benefit_category": _BENEFIT[kind_type], "validation": rec.validation_method, "stage": stage,
        "actions": _ACTIONS[stage], "data_source": {"google_search_console": "Google Search Console", "competitor_public_content": "Public competitor pages",
                                                    "ai_generated_idea": "AI-generated idea (not verified search data)"}.get(rec.data_source, rec.data_source),
    }


def build(db: Session, website: Website) -> list[dict]:
    pages = {p.id: p.canonical_url for p in db.query(Page.id, Page.canonical_url).filter(Page.website_id == website.id)}
    severity: dict[tuple, FindingSeverity] = {(f.page_id, f.rule_code): f.severity for f in db.query(SEOFinding).filter(SEOFinding.website_id == website.id)}
    stage_log = _latest_stages(db, website.id)
    items: list[dict] = []
    for opp in db.query(SEOOpportunity).filter(SEOOpportunity.website_id == website.id).all():
        rule = (opp.evidence_json or {}).get("rule_code")
        items.append(_opportunity_item(opp, pages.get(opp.page_id), severity.get((opp.page_id, rule)), _OPPORTUNITY_TYPE.get(opp.category, "technical")))
    for rec in db.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == website.id).all():
        items.append(_growth_item(rec, pages.get(rec.page_id), stage_log))
    order = {p: i for i, p in enumerate(PRIORITIES)}
    items.sort(key=lambda i: (order[i["priority"]], i["title"]))
    return items


def filtered(items: list[dict], *, type_: str | None = None, priority: str | None = None, stage: str | None = None, q: str | None = None) -> list[dict]:
    for value, allowed, name in ((type_, TYPES, "type"), (priority, PRIORITIES, "priority"), (stage, STAGES, "stage")):
        if value and value not in allowed:
            raise ValueError(f"Unknown {name} '{value}'.")
    return [i for i in items if (not type_ or i["type"] == type_) and (not priority or i["priority"] == priority) and (not stage or i["stage"] == stage)
            and (not q or q.lower() in (i["title"] + " " + (i["affected"] or "")).lower())]


def summarise(items: list[dict]) -> dict:
    def count(key: str, values: tuple) -> dict:
        return {v: sum(1 for i in items if i[key] == v) for v in values if any(i[key] == v for i in items)}

    return {"total": len(items), "by_priority": count("priority", PRIORITIES), "by_type": count("type", TYPES), "by_stage": count("stage", STAGES)}
