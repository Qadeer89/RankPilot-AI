import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.integrations import ga4_sync, token_store
from app.integrations.google_analytics import (
    GoogleApiError,
    GoogleIntegrationNotConfigured,
    build_authorization_url,
    decode_state,
    exchange_code_for_tokens,
    list_properties,
    refresh_access_token,
)
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.membership import Membership, MembershipRole
from app.models.oauth_connection import OAuthProvider
from app.schemas.integrations import (
    ConnectUrlResponse,
    Ga4MetricsResponse,
    Ga4MetricsRow,
    Ga4PropertiesResponse,
    SelectGa4PropertyRequest,
    SyncResultResponse,
)
from app.schemas.website import WebsiteResponse

router = APIRouter(tags=["analytics"])


@router.get(
    "/organizations/{organization_id}/integrations/google/analytics/connect",
    response_model=ConnectUrlResponse,
)
def start_ga4_connect(
    organization_id: uuid.UUID,
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> ConnectUrlResponse:
    try:
        return ConnectUrlResponse(authorization_url=build_authorization_url(organization_id))
    except GoogleIntegrationNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/integrations/google/analytics/callback", include_in_schema=False)
def google_analytics_callback(code: str, state: str, db: Session = Depends(get_db)) -> RedirectResponse:
    """See google_search_console_callback's docstring: same reasoning for
    why this isn't nested under /organizations/{id}.
    """
    try:
        organization_id = decode_state(state)
        token_set = exchange_code_for_tokens(code)
        token_store.upsert_connection(db, organization_id, OAuthProvider.google_analytics, token_set)
        db.commit()
    except (GoogleApiError, GoogleIntegrationNotConfigured) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return RedirectResponse(url="/dashboard?ga4=connected")


@router.post(
    "/organizations/{organization_id}/integrations/google/analytics/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_ga4(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    token_store.disconnect(db, organization_id, OAuthProvider.google_analytics)
    db.commit()


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/ga4-properties",
    response_model=Ga4PropertiesResponse,
)
def get_ga4_properties(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> Ga4PropertiesResponse:
    get_website_or_404(db, organization_id, website_id)
    try:
        access_token = token_store.get_valid_access_token(
            db, organization_id, OAuthProvider.google_analytics, refresh_fn=refresh_access_token
        )
        db.commit()
        return Ga4PropertiesResponse(properties=list_properties(access_token))
    except LookupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GoogleApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/ga4/select",
    response_model=WebsiteResponse,
)
def select_ga4_property(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: SelectGa4PropertyRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> WebsiteResponse:
    website = get_website_or_404(db, organization_id, website_id)
    website.ga4_property_id = payload.property_id
    db.commit()
    return WebsiteResponse.model_validate(website)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/ga4/sync",
    response_model=SyncResultResponse,
)
def sync_ga4(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> SyncResultResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        rows_synced = ga4_sync.sync_ga4_metrics(db, website)
        db.commit()
        return SyncResultResponse(rows_synced=rows_synced)
    except LookupError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GoogleApiError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/ga4-metrics",
    response_model=Ga4MetricsResponse,
)
def get_ga4_metrics(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> Ga4MetricsResponse:
    get_website_or_404(db, organization_id, website_id)
    metrics = (
        db.query(Ga4DailyMetric)
        .filter(Ga4DailyMetric.website_id == website_id)
        .order_by(Ga4DailyMetric.date.desc())
        .limit(90)
        .all()
    )
    rows = [
        Ga4MetricsRow(date=m.date, sessions=m.sessions, total_users=m.total_users, conversions=m.conversions)
        for m in metrics
    ]
    return Ga4MetricsResponse(rows=rows)
