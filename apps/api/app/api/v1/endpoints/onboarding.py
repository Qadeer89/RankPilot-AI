import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.onboarding import service as onboarding_service
from app.schemas.onboarding import OnboardingStatusResponse, SkipStepRequest

router = APIRouter(tags=["onboarding"])


@router.get(
    "/organizations/{organization_id}/onboarding",
    response_model=OnboardingStatusResponse,
)
def get_onboarding_status(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> OnboardingStatusResponse:
    return OnboardingStatusResponse(**onboarding_service.get_onboarding_status(db, organization_id))


@router.post(
    "/organizations/{organization_id}/onboarding/dismiss-welcome",
    response_model=OnboardingStatusResponse,
)
def dismiss_welcome(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> OnboardingStatusResponse:
    onboarding_service.dismiss_welcome(db, organization_id)
    db.commit()
    return OnboardingStatusResponse(**onboarding_service.get_onboarding_status(db, organization_id))


@router.post(
    "/organizations/{organization_id}/onboarding/skip",
    response_model=OnboardingStatusResponse,
)
def skip_step(
    organization_id: uuid.UUID,
    payload: SkipStepRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> OnboardingStatusResponse:
    try:
        onboarding_service.skip_step(db, organization_id, payload.step_key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return OnboardingStatusResponse(**onboarding_service.get_onboarding_status(db, organization_id))


@router.post(
    "/organizations/{organization_id}/onboarding/unskip",
    response_model=OnboardingStatusResponse,
)
def unskip_step(
    organization_id: uuid.UUID,
    payload: SkipStepRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> OnboardingStatusResponse:
    onboarding_service.unskip_step(db, organization_id, payload.step_key)
    db.commit()
    return OnboardingStatusResponse(**onboarding_service.get_onboarding_status(db, organization_id))


@router.post(
    "/organizations/{organization_id}/onboarding/complete",
    response_model=OnboardingStatusResponse,
)
def complete_onboarding(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> OnboardingStatusResponse:
    onboarding_service.mark_complete_if_ready(db, organization_id)
    db.commit()
    return OnboardingStatusResponse(**onboarding_service.get_onboarding_status(db, organization_id))
