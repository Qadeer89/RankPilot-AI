import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.ai.client import AINotConfigured
from app.ai.content_agent import propose_content_fix
from app.ai.runner import PromptTooLarge
from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.page_snapshot import PageSnapshot
from app.models.seo_opportunity import SEOOpportunity
from app.schemas.opportunity import OpportunityResponse
from app.ai.schemas import OpportunityProposal

router = APIRouter(tags=["opportunities"])


def _get_opportunity_or_404(db: Session, website_id: uuid.UUID, opportunity_id: uuid.UUID) -> SEOOpportunity:
    opportunity = (
        db.query(SEOOpportunity)
        .filter(SEOOpportunity.id == opportunity_id, SEOOpportunity.website_id == website_id)
        .one_or_none()
    )
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    return opportunity


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/opportunities",
    response_model=list[OpportunityResponse],
)
def list_opportunities(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[OpportunityResponse]:
    get_website_or_404(db, organization_id, website_id)
    opportunities = (
        db.query(SEOOpportunity).filter(SEOOpportunity.website_id == website_id).all()
    )
    ranked = sorted(opportunities, key=lambda o: o.score, reverse=True)
    return [OpportunityResponse.model_validate(o) for o in ranked]


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/opportunities/{opportunity_id}/proposals",
    response_model=OpportunityProposal,
)
def create_proposal(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> OpportunityProposal:
    website = get_website_or_404(db, organization_id, website_id)
    opportunity = _get_opportunity_or_404(db, website_id, opportunity_id)

    snapshot = None
    if opportunity.page_id is not None:
        snapshot = (
            db.query(PageSnapshot)
            .filter(PageSnapshot.page_id == opportunity.page_id)
            .order_by(PageSnapshot.fetched_at.desc())
            .first()
        )

    try:
        proposal = propose_content_fix(db, website, opportunity, snapshot)
        db.commit()
        return proposal
    except AINotConfigured as exc:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except BudgetExceeded as exc:
        db.rollback()
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except PromptTooLarge as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        # Unlike the two cases above, propose_content_fix may already have
        # written a "failed" AgentRun audit row before raising; commit (not
        # rollback) so that cost/audit record survives for debugging
        # (AI_AGENT_SPECIFICATION.md #7).
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"AI proposal failed: {exc}") from exc
