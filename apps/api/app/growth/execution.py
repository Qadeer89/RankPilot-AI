"""Hands an approved growth recommendation to the existing AI-fix and
execution pipeline (SEO Growth Engine spec section 8) instead of
building a second one. The recommendation becomes an SEOOpportunity in
the "growth" category; from there the existing flow applies unchanged:
AI drafts a title/meta change, a person previews and approves it, the
connected CMS publishes it, the change is validated and can be rolled
back (app/execution/service.py).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.growth_recommendation import GrowthRecommendation, RecommendationStatus
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.website import Website

EXECUTABLE_TYPES = {"improve_existing_page"}


class NotExecutable(ValueError):
    pass


def send_to_execution(db: Session, website: Website, rec: GrowthRecommendation) -> SEOOpportunity:
    if rec.opportunity_id is not None:
        existing = db.get(SEOOpportunity, rec.opportunity_id)
        if existing is not None:
            return existing
    if rec.status != RecommendationStatus.approved:
        raise NotExecutable("Approve the recommendation before sending it for an AI draft.")
    if rec.recommendation_type not in EXECUTABLE_TYPES or rec.page_id is None:
        raise NotExecutable("This recommendation has no automated change; it needs to be done by hand.")

    opportunity = SEOOpportunity(
        website_id=website.id,
        page_id=rec.page_id,
        category="growth",
        title=rec.title[:255],
        rationale=f"{rec.problem} {rec.recommended_action}"[:2048],
        impact_estimate=0.6,
        confidence=0.7,
        effort_estimate=0.3,
        risk_tier=1,
        evidence_json={**rec.evidence_json, "query": rec.keyword, "growth_recommendation_id": str(rec.id)},
        status=OpportunityStatus.open,
    )
    db.add(opportunity)
    db.flush()
    rec.opportunity_id = opportunity.id
    db.flush()
    return opportunity


def sync_completed(db: Session, recs: list[GrowthRecommendation]) -> None:
    """A recommendation is done once the pipeline has applied and
    validated its change -- the only thing that marks an opportunity
    `completed`.
    """
    linked = {r.opportunity_id: r for r in recs if r.opportunity_id and r.status == RecommendationStatus.approved}
    if not linked:
        return
    completed = (
        db.query(SEOOpportunity.id)
        .filter(SEOOpportunity.id.in_(linked.keys()), SEOOpportunity.status == OpportunityStatus.completed)
        .all()
    )
    for (opportunity_id,) in completed:
        linked[opportunity_id].status = RecommendationStatus.done
    db.flush()
