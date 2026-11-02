"""The three remaining MVP agents from AI_AGENT_SPECIFICATION.md #2 that
aren't tied to the content-proposal/execution flow already covered by
opportunities.py and execution.py: Post-change QA Assistant, SEO Strategy
Assistant, and Internal Linking Analyst.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.ai.client import AINotConfigured
from app.ai.internal_linking import InternalLinkSuggestions, suggest_internal_links
from app.ai.qa_assistant import QaSummary, summarize_change
from app.ai.runner import PromptTooLarge
from app.ai.strategy_assistant import StrategySummary, generate_weekly_strategy
from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.linking.candidates import find_orphan_target_pages
from app.models.change_record import ChangeRecord
from app.models.membership import Membership, MembershipRole
from app.models.page import Page
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.schemas.crawl import PageResponse

router = APIRouter(tags=["ai-agents"])


def _ai_call_or_error(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AINotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except PromptTooLarge as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=f"AI agent call failed: {exc}") from exc


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/change-records/{change_id}/qa-summary",
    response_model=QaSummary,
)
def get_qa_summary(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> QaSummary:
    website = get_website_or_404(db, organization_id, website_id)
    change_record = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.id == change_id, ChangeRecord.website_id == website_id)
        .one_or_none()
    )
    if change_record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Change record not found")

    try:
        result = _ai_call_or_error(summarize_change, db, website, change_record)
        db.commit()
        return result
    except HTTPException:
        db.commit()  # Preserve the failed AgentRun audit row; see opportunities.py.
        raise


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/strategy",
    response_model=StrategySummary,
)
def get_weekly_strategy(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> StrategySummary:
    website = get_website_or_404(db, organization_id, website_id)
    opportunities = (
        db.query(SEOOpportunity)
        .filter(SEOOpportunity.website_id == website_id, SEOOpportunity.status == OpportunityStatus.open)
        .all()
    )

    try:
        result = _ai_call_or_error(generate_weekly_strategy, db, website, opportunities)
        db.commit()
        return result
    except HTTPException:
        db.commit()
        raise


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/orphan-pages",
    response_model=list[PageResponse],
)
def list_orphan_pages(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[PageResponse]:
    website = get_website_or_404(db, organization_id, website_id)
    pages = find_orphan_target_pages(db, website)
    return [PageResponse.model_validate(p) for p in pages]


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/pages/{page_id}/internal-link-suggestions",
    response_model=InternalLinkSuggestions,
)
def get_internal_link_suggestions(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    page_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> InternalLinkSuggestions:
    website = get_website_or_404(db, organization_id, website_id)
    page = db.query(Page).filter(Page.id == page_id, Page.website_id == website_id).one_or_none()
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found")

    try:
        result = _ai_call_or_error(suggest_internal_links, db, website, page)
        db.commit()
        return result
    except HTTPException:
        db.commit()
        raise
