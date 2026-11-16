import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import country_param_or_400, get_website_or_404
from app.db.session import get_db
from app.growth import lifecycle
from app.growth.execution import NotExecutable, send_to_execution, sync_completed, verify_live
from app.growth.service import generate_growth_recommendations
from app.models.audit_event import AuditEvent
from app.models.growth_recommendation import GrowthRecommendation, RecommendationStatus
from app.models.membership import Membership, MembershipRole
from app.schemas.growth_recommendation import GrowthRecommendationResponse, UpdateGrowthRecommendationRequest

router = APIRouter(tags=["growth-recommendations"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/growth-recommendations"
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _one(db: Session, website, row: GrowthRecommendation) -> GrowthRecommendationResponse:
    response = GrowthRecommendationResponse.model_validate(row)
    response.lifecycle = lifecycle.describe(db, website, row)
    return response


def _sorted(db: Session, website, rows: list[GrowthRecommendation]) -> list[GrowthRecommendationResponse]:
    rows = sorted(rows, key=lambda r: _PRIORITY_ORDER[r.priority.value])
    return [_one(db, website, r) for r in rows]


@router.post(f"{_BASE}/generate", response_model=list[GrowthRecommendationResponse])
def generate(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    country: str | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> list[GrowthRecommendationResponse]:
    website = get_website_or_404(db, organization_id, website_id)
    rows = generate_growth_recommendations(db, website, country=country_param_or_400(country))
    db.commit()
    return _sorted(db, website, rows)


@router.get(_BASE, response_model=list[GrowthRecommendationResponse])
def list_recommendations(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    status_filter: RecommendationStatus | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[GrowthRecommendationResponse]:
    website = get_website_or_404(db, organization_id, website_id)
    query = db.query(GrowthRecommendation).filter(GrowthRecommendation.website_id == website_id)
    if status_filter is not None:
        query = query.filter(GrowthRecommendation.status == status_filter)
    rows = query.limit(500).all()
    sync_completed(db, rows)
    db.commit()
    if status_filter is not None:
        rows = [r for r in rows if r.status == status_filter]
    return _sorted(db, website, rows)


@router.patch(f"{_BASE}/{{recommendation_id}}", response_model=GrowthRecommendationResponse)
def update_recommendation(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    payload: UpdateGrowthRecommendationRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> GrowthRecommendationResponse:
    website = get_website_or_404(db, organization_id, website_id)
    row = (
        db.query(GrowthRecommendation)
        .filter(GrowthRecommendation.id == recommendation_id, GrowthRecommendation.website_id == website_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    row.status = payload.status
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action=f"growth_recommendation.{payload.status.value}",
            resource_type="growth_recommendation",
            resource_id=str(row.id),
            metadata_json={"title": row.title},
        )
    )
    db.commit()
    db.refresh(row)
    return _one(db, website, row)


@router.post(f"{_BASE}/{{recommendation_id}}/send-to-execution", response_model=GrowthRecommendationResponse)
def send_recommendation_to_execution(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> GrowthRecommendationResponse:
    website = get_website_or_404(db, organization_id, website_id)
    row = (
        db.query(GrowthRecommendation)
        .filter(GrowthRecommendation.id == recommendation_id, GrowthRecommendation.website_id == website_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    try:
        opportunity = send_to_execution(db, website, row)
    except NotExecutable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="growth_recommendation.sent_to_execution",
            resource_type="growth_recommendation",
            resource_id=str(row.id),
            metadata_json={"opportunity_id": str(opportunity.id)},
        )
    )
    db.commit()
    db.refresh(row)
    return _one(db, website, row)


@router.post(f"{_BASE}/{{recommendation_id}}/verify-live")
def verify_recommendation_live(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> dict:
    """Re-fetch the public page and check it shows the applied change."""
    website = get_website_or_404(db, organization_id, website_id)
    row = (
        db.query(GrowthRecommendation)
        .filter(GrowthRecommendation.id == recommendation_id, GrowthRecommendation.website_id == website_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    try:
        result = verify_live(db, website, row)
    except NotExecutable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="growth_recommendation.live_check",
            resource_type="growth_recommendation",
            resource_id=str(row.id),
            metadata_json={"matched": result["matched"]},
        )
    )
    db.commit()
    return result


@router.post(f"{_BASE}/{{recommendation_id}}/recrawl")
def recrawl_recommendation_pages(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> GrowthRecommendationResponse:
    """Queue a one-URL verification crawl for each applied change of this
    recommendation (skipping any whose crawl is already queued/running)."""
    from app.growth.recrawl import IN_FLIGHT, enqueue_post_change_crawl
    from app.models.change_record import ChangeRecord
    from app.models.seo_task import SEOTask

    website = get_website_or_404(db, organization_id, website_id)
    row = (
        db.query(GrowthRecommendation)
        .filter(GrowthRecommendation.id == recommendation_id, GrowthRecommendation.website_id == website_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    if row.opportunity_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Nothing has been applied for this recommendation yet.")

    changes = (
        db.query(ChangeRecord)
        .join(SEOTask, SEOTask.id == ChangeRecord.seo_task_id)
        .filter(SEOTask.opportunity_id == row.opportunity_id)
        .all()
    )
    if not changes:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Nothing has been applied for this recommendation yet.")
    queued = 0
    for change in changes:
        if ((change.after_state_json or {}).get("recrawl") or {}).get("status") in IN_FLIGHT:
            continue
        if enqueue_post_change_crawl(db, website, change) is not None:
            queued += 1
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="growth_recommendation.recrawl",
            resource_type="growth_recommendation",
            resource_id=str(row.id),
            metadata_json={"queued": queued},
        )
    )
    db.commit()
    return _one(db, website, row)
