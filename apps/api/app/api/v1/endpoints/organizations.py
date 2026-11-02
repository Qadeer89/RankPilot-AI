import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.schemas.organization import MemberResponse

router = APIRouter(tags=["organizations"])


@router.get("/organizations/{organization_id}/members", response_model=list[MemberResponse])
def list_members(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[MemberResponse]:
    memberships = db.query(Membership).filter(Membership.organization_id == organization_id).all()
    return [
        MemberResponse(user_id=m.user_id, email=m.user.email, role=m.role.value) for m in memberships
    ]
