import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import country_param_or_400, get_website_or_404
from app.db.session import get_db
from app.integrations import search_console_sync, token_store
from app.opportunities.search_console_signals import refresh_ctr_opportunities
from app.opportunities.search_trend_signals import (
    detect_keyword_cannibalization,
    detect_new_queries,
    detect_page_trend_signals,
    detect_ranking_improvement_opportunities,
)
from app.integrations.google_search_console import (
    GoogleApiError,
    GoogleIntegrationNotConfigured,
    build_authorization_url,
    decode_state,
    exchange_code_for_tokens,
    list_sites,
    refresh_access_token,
)
from app.models.keyword_observation import KeywordObservation
from app.models.membership import Membership, MembershipRole
from app.models.oauth_connection import OAuthProvider
from app.schemas.integrations import (
    CannibalizationCandidateResponse,
    ConnectUrlResponse,
    NewQueryResponse,
    PageTrendSignalResponse,
    RankingOpportunityResponse,
    SearchPerformanceIntelligenceResponse,
    SearchPerformanceResponse,
    SearchPerformanceRow,
    SearchPropertiesResponse,
    SelectPropertyRequest,
    SyncResultResponse,
    WindowStatsResponse,
)
from app.schemas.website import WebsiteResponse

router = APIRouter(tags=["search-console"])


@router.get(
    "/organizations/{organization_id}/integrations/google/search-console/connect",
    response_model=ConnectUrlResponse,
)
def start_google_connect(
    organization_id: uuid.UUID,
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> ConnectUrlResponse:
    try:
        return ConnectUrlResponse(authorization_url=build_authorization_url(organization_id))
    except GoogleIntegrationNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/integrations/google/search-console/callback", include_in_schema=False)
def google_search_console_callback(
    code: str, state: str, db: Session = Depends(get_db)
) -> RedirectResponse:
    """Google redirects the user's browser here after consent. This route
    is intentionally *not* nested under /organizations/{id}: the
    organization is recovered from the signed `state` parameter instead
    (WEBSITE_CONNECTORS.md #1: a callback URL is fixed infrastructure, not
    a tenant-scoped resource path).
    """
    try:
        organization_id = decode_state(state)
        token_set = exchange_code_for_tokens(code)
        token_store.upsert_connection(db, organization_id, OAuthProvider.google_search_console, token_set)
        db.commit()
    except (GoogleApiError, GoogleIntegrationNotConfigured) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return RedirectResponse(url="/dashboard?search_console=connected")


@router.post(
    "/organizations/{organization_id}/integrations/google/search-console/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_google(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    token_store.disconnect(db, organization_id, OAuthProvider.google_search_console)
    db.commit()


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/search-properties",
    response_model=SearchPropertiesResponse,
)
def get_search_properties(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> SearchPropertiesResponse:
    get_website_or_404(db, organization_id, website_id)
    try:
        access_token = token_store.get_valid_access_token(
            db, organization_id, OAuthProvider.google_search_console, refresh_fn=refresh_access_token
        )
        db.commit()
        return SearchPropertiesResponse(site_urls=list_sites(access_token))
    except LookupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GoogleApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/search-console/select",
    response_model=WebsiteResponse,
)
def select_search_console_property(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: SelectPropertyRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> WebsiteResponse:
    website = get_website_or_404(db, organization_id, website_id)
    website.search_console_site_url = payload.site_url
    from app.history.activity import record_event

    record_event(db, website, "integration", "gsc_connected", "Google Search Console connected",
                 detail={"property": payload.site_url}, dedupe_key=f"gsc_connected:{payload.site_url}")
    db.commit()
    return WebsiteResponse.model_validate(website)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/search-console/sync",
    response_model=SyncResultResponse,
)
def sync_search_console(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> SyncResultResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        rows_synced = search_console_sync.sync_search_performance(db, website)
        from app.history.metrics import sync_search_history

        sync_search_history(db, website)
        refresh_ctr_opportunities(db, website)
        db.commit()
        return SyncResultResponse(rows_synced=rows_synced)
    except LookupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GoogleApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/search-performance",
    response_model=SearchPerformanceResponse,
)
def get_search_performance(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    country: str | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> SearchPerformanceResponse:
    get_website_or_404(db, organization_id, website_id)
    country = country_param_or_400(country)
    query = db.query(KeywordObservation).filter(KeywordObservation.website_id == website_id)
    if country is not None:
        query = query.filter(KeywordObservation.country == country)
    observations = (
        query
        .order_by(KeywordObservation.date.desc())
        .limit(500)
        .all()
    )
    rows = [
        SearchPerformanceRow(
            query=o.query,
            date=o.date,
            clicks=o.clicks,
            impressions=o.impressions,
            ctr=o.ctr,
            average_position=o.average_position,
            country=o.country,
            device=o.device,
            page_id=o.page_id,
        )
        for o in observations
    ]
    return SearchPerformanceResponse(rows=rows)


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/search-performance/intelligence",
    response_model=SearchPerformanceIntelligenceResponse,
)
def get_search_performance_intelligence(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    country: str | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> SearchPerformanceIntelligenceResponse:
    """Report-only search-performance signals (RankPilot AI Phase 5,
    extended for the SEO Growth Engine's country-based intelligence):
    pages losing or gaining clicks/impressions/ranking, queries close to
    page 1 that aren't there yet, newly-discovered queries, and keyword
    cannibalization candidates. Pass `country` (any supported code,
    e.g. "US" or "usa") to scope every signal to one target market instead of
    the site's worldwide traffic -- never combined into one misleading
    report (SEO Growth Engine spec section 5). Unlike CTR opportunities,
    none of these feed the auto-execute pipeline -- there's no existing
    AI fix operation for any of them.
    """
    website = get_website_or_404(db, organization_id, website_id)
    country = country_param_or_400(country)

    declining = [
        PageTrendSignalResponse(
            page_id=s.page_id,
            signals=s.signals,
            prior=WindowStatsResponse(**s.prior.__dict__),
            recent=WindowStatsResponse(**s.recent.__dict__),
        )
        for s in detect_page_trend_signals(db, website, country=country)
    ]
    ranking_opportunities = [
        RankingOpportunityResponse(**o.__dict__)
        for o in detect_ranking_improvement_opportunities(db, website, country=country)
    ]
    cannibalization = [
        CannibalizationCandidateResponse(**c.__dict__)
        for c in detect_keyword_cannibalization(db, website, country=country)
    ]
    new_queries = [NewQueryResponse(**q.__dict__) for q in detect_new_queries(db, website, country=country)]

    return SearchPerformanceIntelligenceResponse(
        country=country,
        declining_pages=declining,
        ranking_improvement_opportunities=ranking_opportunities,
        keyword_cannibalization=cannibalization,
        new_queries=new_queries,
    )
