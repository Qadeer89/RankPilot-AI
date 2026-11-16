"""Super Admin API. EVERY route here sits behind `require_super_admin` (configured email + verified +
active, re-read from the database on each request); tests enumerate the router to prove none is left open."""

from fastapi import APIRouter, Depends

from app.core.deps import require_super_admin
from app.models.user import User

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_super_admin)])


@router.get("/whoami")
def whoami(admin: User = Depends(require_super_admin)) -> dict:
    return {"id": str(admin.id), "email": admin.email, "is_super_admin": True}
