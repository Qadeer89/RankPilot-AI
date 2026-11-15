import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.rate_limit import rate_limit_by_ip
from app.core.security import create_access_token, hash_password, verify_password
from app.core.verification import generate_token, hash_token
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User
from app.notifications.email import send_plain_email
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    MessageResponse,
    OrganizationSummary,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)

# Always the same regardless of whether the email matched an account --
# the one piece of information that must never leak through a
# forgot-password endpoint's response (RP13-followup).
_FORGOT_PASSWORD_GENERIC_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)

router = APIRouter(tags=["auth"])

_SLUG_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    base = _SLUG_SANITIZE_RE.sub("-", name.lower()).strip("-") or "org"
    return f"{base}-{uuid.uuid4().hex[:8]}"


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    rate_limit_by_ip(
        request,
        scope="auth_register",
        max_attempts=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    existing = db.query(User).filter(User.email == payload.email).one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(email=payload.email, hashed_password=hash_password(payload.password))
    organization = Organization(name=payload.organization_name, slug=_slugify(payload.organization_name))
    db.add_all([user, organization])
    db.flush()

    membership = Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.owner)
    db.add(membership)
    db.add(
        AuditEvent(
            organization_id=organization.id,
            actor_user_id=user.id,
            action="user.register",
            resource_type="organization",
            resource_id=str(organization.id),
            metadata_json={"email": payload.email},
        )
    )
    db.commit()

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    rate_limit_by_ip(
        request,
        scope="auth_login",
        max_attempts=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/auth/forgot-password", response_model=MessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> MessageResponse:
    settings = get_settings()
    rate_limit_by_ip(
        request,
        scope="auth_forgot_password",
        max_attempts=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    user = db.query(User).filter(User.email == payload.email).one_or_none()
    # Deliberately identical response and (near-identical) timing whether
    # or not the account exists -- an attacker must not be able to use
    # this endpoint to enumerate registered emails.
    if user is not None:
        token = generate_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.password_reset_token_expire_minutes),
            )
        )
        db.commit()

        reset_link = f"{settings.frontend_base_url}/reset-password?token={token}"
        send_plain_email(
            user.email,
            "Reset your RankPilot AI password",
            f"Click the link below to reset your password. This link expires in "
            f"{settings.password_reset_token_expire_minutes} minutes and can only be used once.\n\n{reset_link}\n\n"
            "If you didn't request this, you can safely ignore this email.",
        )

    return MessageResponse(message=_FORGOT_PASSWORD_GENERIC_MESSAGE)


@router.post("/auth/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> MessageResponse:
    settings = get_settings()
    rate_limit_by_ip(
        request,
        scope="auth_reset_password",
        max_attempts=settings.auth_rate_limit_max_attempts,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )

    token_hash = hash_token(payload.token)
    reset_token = (
        db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == token_hash).one_or_none()
    )
    now = datetime.now(timezone.utc)
    if (
        reset_token is None
        or reset_token.used_at is not None
        or reset_token.expires_at < now
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset token.")

    user = db.get(User, reset_token.user_id)
    user.hashed_password = hash_password(payload.new_password)
    reset_token.used_at = now

    # Any other outstanding reset tokens for this user are now moot --
    # closing them prevents a second, older leaked link from still
    # working after the user has already reset their password with a
    # newer one.
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.id != reset_token.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now})

    db.add(
        AuditEvent(
            organization_id=None,
            actor_user_id=user.id,
            action="user.password_reset",
            resource_type="user",
            resource_id=str(user.id),
            metadata_json={},
        )
    )
    db.commit()

    return MessageResponse(message="Password has been reset. You can now log in with your new password.")


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    memberships = db.query(Membership).filter(Membership.user_id == user.id).all()
    organizations = [
        OrganizationSummary(
            id=m.organization.id,
            name=m.organization.name,
            slug=m.organization.slug,
            role=m.role.value,
        )
        for m in memberships
    ]
    return MeResponse(user=UserResponse.model_validate(user), organizations=organizations)
