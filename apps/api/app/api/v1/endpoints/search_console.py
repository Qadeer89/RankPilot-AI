import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.integrations import search_console_sync, token_store
from app.integrations.google_search_console import (
    GoogleApiError,
    GoogleIntegrationNotConfigured,
    build_authorization_url,
    decode_state,
    exchange_code_for_tokens,
    list_sites,
)
from app.models.keyword_observation import KeywordObservation
from app.models.membership import Membership, MembershipRole
from app.schemas.integrations import (
    ConnectUrlResponse,
    SearchPerformanceResponse,
    SearchPerformanceRow,
    SearchPropertiesResponse,
    SelectPropertyRequest,
    SyncResultResponse,
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
        token_store.upsert_connection(db, organization_id, token_set)
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
    token_store.disconnect(db, organization_id)
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
        access_token = token_store.get_valid_access_token(db, organization_id)
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
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> SearchPerformanceResponse:
    get_website_or_404(db, organization_id, website_id)
    observations = (
        db.query(KeywordObservation)
        .filter(KeywordObservation.website_id == website_id)
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
        )
        for o in observations
    ]
    return SearchPerformanceResponse(rows=rows)
