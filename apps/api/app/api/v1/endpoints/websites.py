import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import RequireRole
from app.core.resources import get_website_or_404 as _get_website_or_404
from app.core.url_safety import UnsafeUrlError, validate_public_url
from app.core.verification import build_instructions, check_html_file_verification, generate_token, hash_token
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.membership import Membership, MembershipRole
from app.models.website import VerificationStatus, Website, WebsiteStatus
from app.models.website_verification import VerificationMethod, WebsiteVerification
from app.schemas.website import (
    VerificationConfirmRequest,
    VerificationInstructionsResponse,
    VerificationResultResponse,
    WebsiteCreateRequest,
    WebsiteResponse,
    WebsiteSettingsUpdateRequest,
)

router = APIRouter(tags=["websites"])


@router.post(
    "/organizations/{organization_id}/websites",
    response_model=WebsiteResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_website(
    organization_id: uuid.UUID,
    payload: WebsiteCreateRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> WebsiteResponse:
    try:
        safe_url = validate_public_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unsafe_url: {exc}") from exc

    website = Website(
        organization_id=organization_id,
        canonical_url=safe_url.normalized_url,
        hostname=safe_url.hostname,
        display_name=payload.display_name,
    )
    db.add(website)
    db.flush()
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.register",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={"url": safe_url.normalized_url, "purpose": payload.purpose},
        )
    )
    db.commit()
    return WebsiteResponse.model_validate(website)


@router.get("/organizations/{organization_id}/websites", response_model=list[WebsiteResponse])
def list_websites(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[WebsiteResponse]:
    websites = db.query(Website).filter(Website.organization_id == organization_id).all()
    return [WebsiteResponse.model_validate(w) for w in websites]


@router.get("/organizations/{organization_id}/websites/{website_id}", response_model=WebsiteResponse)
def get_website(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> WebsiteResponse:
    website = _get_website_or_404(db, organization_id, website_id)
    return WebsiteResponse.model_validate(website)


@router.patch(
    "/organizations/{organization_id}/websites/{website_id}/settings",
    response_model=WebsiteResponse,
)
def update_website_settings(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: WebsiteSettingsUpdateRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteResponse:
    website = _get_website_or_404(db, organization_id, website_id)

    if payload.display_name is not None:
        website.display_name = payload.display_name
    if payload.crawl_budget is not None:
        website.crawl_budget = payload.crawl_budget
    if payload.auto_execute_risk_tier_1 is not None:
        website.automation_policy = {
            **website.automation_policy,
            "auto_execute_risk_tier_1": payload.auto_execute_risk_tier_1,
        }

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.settings.update",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json=payload.model_dump(exclude_none=True),
        )
    )
    db.commit()
    return WebsiteResponse.model_validate(website)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/verify/instructions",
    response_model=VerificationInstructionsResponse,
)
def start_verification(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> VerificationInstructionsResponse:
    website = _get_website_or_404(db, organization_id, website_id)

    settings = get_settings()
    token = generate_token()
    method = VerificationMethod.html_file
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.verification_token_expire_minutes)
    verification = WebsiteVerification(
        website_id=website.id, method=method, token_hash=hash_token(token), expires_at=expires_at
    )
    website.verification_status = VerificationStatus.pending

    db.add(verification)
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.verification.start",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={"method": method.value},
        )
    )
    db.commit()

    return VerificationInstructionsResponse(
        website_id=website.id,
        method=method.value,
        token=token,
        instructions=build_instructions(website.hostname, method, token),
    )


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/verify",
    response_model=VerificationResultResponse,
)
def confirm_verification(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: VerificationConfirmRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> VerificationResultResponse:
    website = _get_website_or_404(db, organization_id, website_id)

    settings = get_settings()
    pending = (
        db.query(WebsiteVerification)
        .filter(
            WebsiteVerification.website_id == website.id,
            WebsiteVerification.verified_at.is_(None),
        )
        .order_by(WebsiteVerification.created_at.desc())
        .first()
    )
    if pending is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="No pending verification for this website")

    # RP13-004: throttle repeated confirm attempts against this one
    # verification row rather than allowing unlimited guesses.
    if pending.attempt_count >= settings.verification_max_attempts:
        website.verification_status = VerificationStatus.failed
        db.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=membership.user_id,
                action="website.verification.rate_limited",
                resource_type="website",
                resource_id=str(website.id),
                metadata_json={"attempt_count": pending.attempt_count},
            )
        )
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification attempts. Request new verification instructions.",
        )

    pending.attempt_count += 1

    # RP13-003: a verification token is single-purpose and time-boxed; an
    # expired token must not be usable even if it is later leaked/replayed.
    if pending.expires_at is not None and datetime.now(timezone.utc) > pending.expires_at:
        website.verification_status = VerificationStatus.failed
        db.add(
            AuditEvent(
                organization_id=organization_id,
                actor_user_id=membership.user_id,
                action="website.verification.confirm",
                resource_type="website",
                resource_id=str(website.id),
                metadata_json={"verified": False, "detail": "expired"},
            )
        )
        db.commit()
        return VerificationResultResponse(
            website_id=website.id,
            verification_status=website.verification_status.value,
            verified=False,
            detail="Verification token has expired. Request new verification instructions.",
        )

    token = payload.token
    if hash_token(token) != pending.token_hash:
        db.commit()  # persist the attempt_count increment above
        return VerificationResultResponse(
            website_id=website.id,
            verification_status=website.verification_status.value,
            verified=False,
            detail="Token does not match the pending verification.",
        )

    verified, detail = check_html_file_verification(website.canonical_url, token)

    if verified:
        pending.verified_at = datetime.now(timezone.utc)
        website.verification_status = VerificationStatus.verified
    else:
        website.verification_status = VerificationStatus.failed

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.verification.confirm",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={"verified": verified, "detail": detail},
        )
    )
    db.commit()

    return VerificationResultResponse(
        website_id=website.id,
        verification_status=website.verification_status.value,
        verified=verified,
        detail=detail,
    )


@router.post("/organizations/{organization_id}/websites/{website_id}/pause", response_model=WebsiteResponse)
def pause_website(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> WebsiteResponse:
    website = _get_website_or_404(db, organization_id, website_id)
    website.status = WebsiteStatus.paused
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.pause",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteResponse.model_validate(website)


@router.delete("/organizations/{organization_id}/websites/{website_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_website(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = _get_website_or_404(db, organization_id, website_id)
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.delete",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={"hostname": website.hostname},
        )
    )
    db.delete(website)
    db.commit()
