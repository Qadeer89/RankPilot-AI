import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.admin import super_admin_state
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.user import User, UserStatus

_bearer_scheme = HTTPBearer(auto_error=False)

_ROLE_RANK = {
    MembershipRole.viewer: 0,
    MembershipRole.editor: 1,
    MembershipRole.admin: 2,
    MembershipRole.owner: 3,
}


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.status != UserStatus.active:
        # A suspended account stops working at once, even with a token that has not expired yet.
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This account is suspended.")

    return user


def get_membership(organization_id: uuid.UUID, db: Session, user: User) -> Membership:
    """Resolve the current user's membership in `organization_id`, or raise a
    tenant-access-denied error. Every tenant-scoped endpoint must depend on this
    (via `RequireRole`) before touching organization-owned data
    (SECURITY_SPECIFICATION.md #2, QA_TEST_STRATEGY.md multi-tenancy coverage).
    """
    membership = (
        db.query(Membership)
        .filter(Membership.organization_id == organization_id, Membership.user_id == user.id)
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Tenant access denied")
    return membership


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """The only gate for admin functionality. Every admin endpoint depends on it; it checks the database
    row each time (configured email, verified, active), never a client-supplied value."""
    state = super_admin_state(user)
    if state == "ok":
        return user
    if state == "email_not_verified":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "email_not_verified", "message": "Verify your email address to use admin features."},
        )
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Super Admin access required")


def require_platform_admin(user: User = Depends(require_super_admin)) -> User:
    """Kept for the existing admin endpoints (knowledge base, AI usage). It is now exactly the Super Admin
    gate, so the old `is_platform_admin` database flag is no longer a second way in."""
    return user


class RequireRole:
    """FastAPI dependency factory: `Depends(RequireRole(MembershipRole.editor))`.

    Must be used on a route with an `organization_id` path parameter; FastAPI
    binds it into `__call__` the same way it binds any other path parameter.
    """

    def __init__(self, minimum_role: MembershipRole) -> None:
        self.minimum_role = minimum_role

    def __call__(
        self,
        organization_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user),
    ) -> Membership:
        membership = get_membership(organization_id, db, user)
        if _ROLE_RANK[membership.role] < _ROLE_RANK[self.minimum_role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return membership
