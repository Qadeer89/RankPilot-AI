import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.competitors.service import add_competitor_domain, run_competitor_analysis
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.models.competitor import CompetitorDomain
from app.models.membership import Membership, MembershipRole
from app.schemas.competitor import (
    AddCompetitorDomainRequest,
    CompetitorDomainResponse,
    CompetitorPageSnapshotResponse,
)
from app.schemas.keyword_idea import KeywordIdeaResponse

router = APIRouter(tags=["competitors"])
MAX_COMPETITORS_PER_WEBSITE = 10


def _get_competitor_or_404(db: Session, website_id: uuid.UUID, competitor_id: uuid.UUID) -> CompetitorDomain:
    competitor = (
        db.query(CompetitorDomain)
        .filter(CompetitorDomain.id == competitor_id, CompetitorDomain.website_id == website_id)
        .one_or_none()
    )
    if competitor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Competitor domain not found")
    return competitor


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/competitors",
    response_model=list[CompetitorDomainResponse],
)
def list_competitors(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[CompetitorDomainResponse]:
    get_website_or_404(db, organization_id, website_id)
    competitors = db.query(CompetitorDomain).filter(CompetitorDomain.website_id == website_id).all()
    return [CompetitorDomainResponse.model_validate(c) for c in competitors]


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/competitors",
    response_model=CompetitorDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_competitor(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: AddCompetitorDomainRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> CompetitorDomainResponse:
    website = get_website_or_404(db, organization_id, website_id)
    if db.query(CompetitorDomain).filter(CompetitorDomain.website_id == website_id).count() >= MAX_COMPETITORS_PER_WEBSITE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"A website can track at most {MAX_COMPETITORS_PER_WEBSITE} competitors."
        )
    competitor = add_competitor_domain(db, website, payload.domain)
    db.commit()
    db.refresh(competitor)
    return CompetitorDomainResponse.model_validate(competitor)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/competitors/{competitor_id}/analyze",
    response_model=list[KeywordIdeaResponse],
)
def analyze_competitor(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    competitor_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> list[KeywordIdeaResponse]:
    website = get_website_or_404(db, organization_id, website_id)
    competitor = _get_competitor_or_404(db, website_id, competitor_id)
    enforce_rate_limit(f"competitor_analysis:{website_id}", max_attempts=10, window_seconds=3600)
    ideas = run_competitor_analysis(db, website, competitor)
    db.commit()
    for idea in ideas:
        db.refresh(idea)
    return [KeywordIdeaResponse.model_validate(i) for i in ideas]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/competitors/{competitor_id}/pages",
    response_model=list[CompetitorPageSnapshotResponse],
)
def list_competitor_pages(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    competitor_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[CompetitorPageSnapshotResponse]:
    get_website_or_404(db, organization_id, website_id)
    competitor = _get_competitor_or_404(db, website_id, competitor_id)
    return [CompetitorPageSnapshotResponse.model_validate(p) for p in competitor.pages]


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_competitor(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    competitor_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> None:
    get_website_or_404(db, organization_id, website_id)
    competitor = _get_competitor_or_404(db, website_id, competitor_id)
    db.delete(competitor)
    db.commit()
