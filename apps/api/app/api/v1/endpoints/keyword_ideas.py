import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.keywords.discovery_service import run_keyword_discovery
from app.models.keyword_idea import KeywordIdea, KeywordIdeaSource, KeywordIdeaStatus
from app.models.membership import Membership, MembershipRole
from app.schemas.keyword_idea import (
    KeywordDiscoveryRunResponse,
    KeywordIdeaResponse,
    RunKeywordDiscoveryRequest,
    UpdateKeywordIdeaRequest,
)

router = APIRouter(tags=["keyword-ideas"])


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/keyword-discovery/run",
    response_model=KeywordDiscoveryRunResponse,
)
def run_discovery(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: RunKeywordDiscoveryRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> KeywordDiscoveryRunResponse:
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"keyword_discovery:{website_id}", max_attempts=10, window_seconds=3600)
    try:
        ideas = run_keyword_discovery(db, website, country=payload.country, max_ideas=payload.max_ideas)
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    db.commit()
    for idea in ideas:
        db.refresh(idea)
    return KeywordDiscoveryRunResponse(ideas=[KeywordIdeaResponse.model_validate(i) for i in ideas])


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/keyword-ideas",
    response_model=list[KeywordIdeaResponse],
)
def list_keyword_ideas(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    country: str | None = None,
    source: KeywordIdeaSource | None = None,
    status_filter: KeywordIdeaStatus | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[KeywordIdeaResponse]:
    get_website_or_404(db, organization_id, website_id)
    query = db.query(KeywordIdea).filter(KeywordIdea.website_id == website_id)
    if country is not None:
        query = query.filter(KeywordIdea.country == country)
    if source is not None:
        query = query.filter(KeywordIdea.source == source)
    if status_filter is not None:
        query = query.filter(KeywordIdea.status == status_filter)
    ideas = query.order_by(KeywordIdea.relevance.desc()).limit(500).all()
    return [KeywordIdeaResponse.model_validate(i) for i in ideas]


@router.patch(
    "/organizations/{organization_id}/websites/{website_id}/keyword-ideas/{idea_id}",
    response_model=KeywordIdeaResponse,
)
def update_keyword_idea(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    idea_id: uuid.UUID,
    payload: UpdateKeywordIdeaRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> KeywordIdeaResponse:
    get_website_or_404(db, organization_id, website_id)
    idea = (
        db.query(KeywordIdea)
        .filter(KeywordIdea.id == idea_id, KeywordIdea.website_id == website_id)
        .one_or_none()
    )
    if idea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Keyword idea not found")
    idea.status = payload.status
    db.commit()
    db.refresh(idea)
    return KeywordIdeaResponse.model_validate(idea)
