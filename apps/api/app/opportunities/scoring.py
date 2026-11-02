"""Deterministic opportunity scoring from rule-engine findings (RP-0603,
SEO_AUTOMATION_ENGINE.md #3).

Scoring is entirely deterministic and explainable: impact/effort/risk_tier
come from a fixed per-rule table, confidence is inherited from the finding
that triggered it. AI is never involved in deciding whether or how much an
opportunity matters — only in explaining it afterwards
(MASTER_SPEC.md "Global implementation rules").
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website


@dataclass(frozen=True)
class OpportunityTemplate:
    category: str
    title: str
    rationale: str
    impact_estimate: float
    effort_estimate: float
    risk_tier: int


# Heuristic, length-based findings (TITLE_TOO_LONG, HEADING_MULTIPLE_H1,
# NOINDEX_DIRECTIVE, etc.) deliberately have no entry here: they stay
# visible as findings but are not promoted to actionable opportunities,
# to keep the opportunity list high-precision (MASTER_SPEC.md #8/#9).
RULE_OPPORTUNITY_TEMPLATES: dict[str, OpportunityTemplate] = {
    "TITLE_MISSING": OpportunityTemplate(
        category="metadata",
        title="Add a missing page title",
        rationale="This page has no <title>, which search engines rely on heavily for ranking and the result snippet.",
        impact_estimate=0.8,
        effort_estimate=0.2,
        risk_tier=1,
    ),
    "META_DESCRIPTION_MISSING": OpportunityTemplate(
        category="metadata",
        title="Add a missing meta description",
        rationale="This page has no meta description, so search engines generate a snippet automatically.",
        impact_estimate=0.5,
        effort_estimate=0.2,
        risk_tier=1,
    ),
    "DUPLICATE_TITLE": OpportunityTemplate(
        category="metadata",
        title="Resolve a duplicate page title",
        rationale="This page shares its title with at least one other page, which can confuse search engines about which page to rank.",
        impact_estimate=0.7,
        effort_estimate=0.3,
        risk_tier=1,
    ),
    "DUPLICATE_META_DESCRIPTION": OpportunityTemplate(
        category="metadata",
        title="Resolve a duplicate meta description",
        rationale="This page shares its meta description with at least one other page.",
        impact_estimate=0.4,
        effort_estimate=0.3,
        risk_tier=1,
    ),
    "CANONICAL_MISSING": OpportunityTemplate(
        category="indexability",
        title="Add a canonical tag",
        rationale="This page has no canonical URL declared.",
        impact_estimate=0.3,
        effort_estimate=0.3,
        risk_tier=1,
    ),
    "CANONICAL_MISMATCH": OpportunityTemplate(
        category="indexability",
        title="Fix a mismatched canonical tag",
        rationale="This page's canonical URL points somewhere other than itself, which may be unintentional.",
        impact_estimate=0.6,
        effort_estimate=0.4,
        risk_tier=2,
    ),
    "HTTP_ERROR_STATUS": OpportunityTemplate(
        category="technical",
        title="Fix a broken page",
        rationale="This page returned an error status on the last crawl.",
        impact_estimate=0.9,
        effort_estimate=0.5,
        risk_tier=1,
    ),
    "BROKEN_INTERNAL_LINK": OpportunityTemplate(
        category="technical",
        title="Fix a broken internal link",
        rationale="This page links to one or more URLs that return an error status.",
        impact_estimate=0.5,
        effort_estimate=0.2,
        risk_tier=1,
    ),
    "REDIRECT_CHAIN": OpportunityTemplate(
        category="technical",
        title="Shorten a redirect chain",
        rationale="This page is only reachable after multiple redirect hops, which slows crawling and page load.",
        impact_estimate=0.3,
        effort_estimate=0.3,
        risk_tier=1,
    ),
    "STRUCTURED_DATA_PARSE_ERROR": OpportunityTemplate(
        category="structured_data",
        title="Fix invalid structured data",
        rationale="This page has a JSON-LD block that fails to parse, so search engines can't read it.",
        impact_estimate=0.4,
        effort_estimate=0.4,
        risk_tier=1,
    ),
    "ORPHAN_PAGE_CANDIDATE": OpportunityTemplate(
        category="internal_linking",
        title="Add internal links to an orphan page",
        rationale="This page is in the sitemap but isn't linked from any other crawled page, making it hard to discover.",
        impact_estimate=0.4,
        effort_estimate=0.4,
        risk_tier=1,
    ),
    "SITEMAP_URL_ERROR": OpportunityTemplate(
        category="technical",
        title="Fix a broken sitemap entry",
        rationale="This page is listed in the sitemap but returns an error status.",
        impact_estimate=0.5,
        effort_estimate=0.3,
        risk_tier=1,
    ),
}


def refresh_opportunities_for_website(db: Session, website: Website) -> list[SEOOpportunity]:
    """Re-derive opportunities from this website's current open findings.

    Upserts by (website_id, page_id, title): an opportunity whose backing
    finding is no longer open gets marked completed, matching the
    finding-resolution lifecycle in app/seo_rules/engine.py.
    """
    open_findings = (
        db.query(SEOFinding)
        .filter(SEOFinding.website_id == website.id, SEOFinding.status == FindingStatus.open)
        .all()
    )

    existing_opportunities = {
        (o.page_id, o.title): o
        for o in db.query(SEOOpportunity).filter(SEOOpportunity.website_id == website.id).all()
    }

    touched_keys: set[tuple] = set()
    persisted: list[SEOOpportunity] = []

    for finding in open_findings:
        template = RULE_OPPORTUNITY_TEMPLATES.get(finding.rule_code)
        if template is None:
            continue

        key = (finding.page_id, template.title)
        touched_keys.add(key)

        existing = existing_opportunities.get(key)
        if existing is None:
            opportunity = SEOOpportunity(
                website_id=website.id,
                page_id=finding.page_id,
                category=template.category,
                title=template.title,
                rationale=template.rationale,
                impact_estimate=template.impact_estimate,
                confidence=finding.confidence,
                effort_estimate=template.effort_estimate,
                risk_tier=template.risk_tier,
                evidence_json={"rule_code": finding.rule_code, "finding_evidence": finding.evidence_json},
                status=OpportunityStatus.open,
            )
            db.add(opportunity)
        else:
            existing.confidence = finding.confidence
            existing.evidence_json = {"rule_code": finding.rule_code, "finding_evidence": finding.evidence_json}
            if existing.status == OpportunityStatus.completed:
                existing.status = OpportunityStatus.open
            opportunity = existing
        persisted.append(opportunity)

    db.flush()

    for (page_id, title), opportunity in existing_opportunities.items():
        if (page_id, title) not in touched_keys and opportunity.status == OpportunityStatus.open:
            opportunity.status = OpportunityStatus.completed

    # See app/seo_rules/engine.py's matching comment: flush so an immediate
    # subsequent read in the same transaction isn't stale under
    # autoflush=False.
    db.flush()
    return sorted(persisted, key=lambda o: o.score, reverse=True)
