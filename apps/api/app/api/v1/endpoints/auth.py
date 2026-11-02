import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(tags=["auth"])

_SLUG_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(name: str) -> str:
    base = _SLUG_SANITIZE_RE.sub("-", name.lower()).strip("-") or "org"
    return f"{base}-{uuid.uuid4().hex[:8]}"


@router.post("/auth/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
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
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email).one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return TokenResponse(access_token=create_access_token(user.id))


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
