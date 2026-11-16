from fastapi import APIRouter, Depends

from app.core.countries import list_countries
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(tags=["reference"])


@router.get("/reference/countries")
def get_countries(_user: User = Depends(get_current_user)) -> list[dict[str, str]]:
    """Every country RankPilot accepts, as {code, name} with the internal
    two-letter code -- the one list the UI builds its selectors from.
    """
    return list_countries()
