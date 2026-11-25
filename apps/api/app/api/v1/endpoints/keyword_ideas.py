import uuid

from app.billing.entitlement import require as require_entitlement

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import country_param_or_400, get_website_or_404
from app.db.session import get_db
from app.keywords.brand import is_brand_navigational
from app.keywords.discovery_service import run_keyword_discovery_detailed
from app.models.keyword_idea import KeywordIdea, KeywordIdeaSource, KeywordIdeaStatus
from app.models.membership import Membership, MembershipRole
from app.schemas.keyword_idea import (
    KeywordDiscoveryRunResponse,
    KeywordIdeaResponse,
    RunKeywordDiscoveryRequest,
    UpdateKeywordIdeaRequest,
)

router = APIRouter(tags=["keyword-ideas"])


def _response(idea: KeywordIdea, website) -> KeywordIdeaResponse:
    out = KeywordIdeaResponse.model_validate(idea)
    out.brand_search = is_brand_navigational(idea.keyword, idea.search_intent.value, website.display_name, website.hostname)
    return out


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
    require_entitlement(db, website, "keyword_discovery")
    enforce_rate_limit(f"keyword_discovery:{website_id}", max_attempts=10, window_seconds=3600)
    try:
        outcome = run_keyword_discovery_detailed(
            db, website, country=country_param_or_400(payload.country), max_ideas=payload.max_ideas
        )
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    db.commit()
    for idea in outcome.ideas:
        db.refresh(idea)
    return KeywordDiscoveryRunResponse(
        ideas=[_response(i, website) for i in outcome.ideas],
        ai_status=outcome.ai_status,
        ai_message=outcome.ai_message,
    )


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
    website = get_website_or_404(db, organization_id, website_id)
    query = db.query(KeywordIdea).filter(KeywordIdea.website_id == website_id)
    country = country_param_or_400(country)
    if country is not None:
        query = query.filter(KeywordIdea.country == country)
    if source is not None:
        query = query.filter(KeywordIdea.source == source)
    if status_filter is not None:
        query = query.filter(KeywordIdea.status == status_filter)
    ideas = query.order_by(KeywordIdea.relevance.desc()).limit(500).all()
    return [_response(i, website) for i in ideas]


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
    website = get_website_or_404(db, organization_id, website_id)
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
    return _response(idea, website)
