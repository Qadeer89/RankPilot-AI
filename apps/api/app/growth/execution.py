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


LIVE_CHECK_FIELDS = {"set_title": "title", "set_meta_description": "meta_description"}


def verify_live(db: Session, website: Website, rec: GrowthRecommendation) -> dict:
    """Re-fetch the public page and confirm it now shows each applied
    value. The pipeline's own validation reads the value back from the
    CMS; this checks what a visitor or crawler actually receives, which
    can lag behind (caching, a build that has not finished).
    """
    from datetime import datetime, timezone

    from app.crawler.extract import extract_page
    from app.crawler.fetch import FetchError, safe_fetch
    from app.models.change_record import ChangeRecord
    from app.models.seo_task import SEOTask

    if rec.opportunity_id is None:
        raise NotExecutable("Nothing has been applied for this recommendation yet.")
    tasks = db.query(SEOTask).filter(SEOTask.opportunity_id == rec.opportunity_id).all()
    checks = []
    for task in tasks:
        change = (
            db.query(ChangeRecord)
            .filter(ChangeRecord.seo_task_id == task.id)
            .order_by(ChangeRecord.executed_at.desc())
            .first()
        )
        field = LIVE_CHECK_FIELDS.get(task.task_type)
        target_url = task.proposed_change_json.get("target_url")
        if change is None or field is None or not target_url:
            continue
        from app.growth.recrawl import applied_value

        expected = applied_value(change, task)
        try:
            fetched = safe_fetch(target_url)
            found = getattr(extract_page(fetched.body, base_url=fetched.final_url, site_hostname=website.hostname), field)
            checks.append(
                {"operation": task.task_type, "url": target_url, "expected": expected, "found": found,
                 "matched": (found or "").strip() == (expected or "").strip(), "error": None}
            )
        except FetchError as exc:
            checks.append(
                {"operation": task.task_type, "url": target_url, "expected": expected, "found": None,
                 "matched": False, "error": str(exc)}
            )
    if not checks:
        raise NotExecutable("Nothing has been applied for this recommendation yet.")

    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "matched": all(c["matched"] for c in checks),
        "checks": checks,
    }
    rec.evidence_json = {**rec.evidence_json, "live_check": result}
    db.flush()
    return result
