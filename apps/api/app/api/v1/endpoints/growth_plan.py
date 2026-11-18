"""Growth journey, unified recommendations, 30-day plan and business profile. Tenant-scoped like every project route."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.growth import action_plan, journey, unified
from app.history import activity
from app.models.audit_event import AuditEvent
from app.models.business_profile import BusinessProfile
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["growth-plan"])
_BASE = "/organizations/{organization_id}/websites/{website_id}"
_DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


@router.get(f"{_BASE}/growth/journey")
def get_journey(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    result = journey.build(db, website)
    db.commit()
    return result


@router.get(f"{_BASE}/growth/plan")
def get_plan(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    result = action_plan.build(db, website)
    db.commit()
    return {**result, "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get(f"{_BASE}/growth/recommendations")
def list_unified(organization_id: uuid.UUID, website_id: uuid.UUID, type: str | None = None, priority: str | None = None, stage: str | None = None,
                 q: str | None = Query(None, max_length=200), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
                 db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    items = unified.build(db, website)
    try:
        rows = unified.filtered(items, type_=type, priority=priority, stage=stage, q=q)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "invalid_filter", "message": str(exc)}) from exc
    total = len(rows)
    return {"items": rows[(page - 1) * page_size: page * page_size], "page": page, "page_size": page_size, "total": total, "pages": max((total + page_size - 1) // page_size, 1),
            "summary": unified.summarise(items)}


def _profile_dict(p: BusinessProfile | None) -> dict:
    if p is None:
        return {"exists": False, "confirmed": False, "business_type": None, "industry": None, "offerings": [], "target_customers": [], "objective": None,
                "known_competitors": [], "ai_suggestions": None, "confirmed_at": None}
    return {"exists": True, "confirmed": p.confirmed_at is not None, "business_type": p.business_type, "industry": p.industry, "offerings": p.offerings,
            "target_customers": p.target_customers, "objective": p.objective, "known_competitors": p.known_competitors, "ai_suggestions": p.ai_suggestions,
            "confirmed_at": p.confirmed_at.isoformat() if p.confirmed_at else None}


@router.get(f"{_BASE}/business-profile")
def get_profile(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db), _m: Membership = Depends(RequireRole(MembershipRole.viewer))) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    return {**_profile_dict(db.query(BusinessProfile).filter(BusinessProfile.website_id == website.id).one_or_none()),
            "target_countries": website.all_target_countries, "target_language": website.target_language}


class ProfileUpdate(BaseModel):
    business_type: str | None = Field(None, max_length=128)
    industry: str | None = Field(None, max_length=128)
    offerings: list[str] = Field(default_factory=list, max_length=20)
    target_customers: list[str] = Field(default_factory=list, max_length=20)
    objective: str | None = Field(None, max_length=1000)
    known_competitors: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("offerings", "target_customers")
    @classmethod
    def _short_items(cls, items: list[str]) -> list[str]:
        cleaned = [i.strip() for i in items if i and i.strip()]
        if any(len(i) > 200 for i in cleaned):
            raise ValueError("Each entry must be 200 characters or fewer.")
        return cleaned

    @field_validator("known_competitors")
    @classmethod
    def _domains(cls, items: list[str]) -> list[str]:
        out = []
        for raw in items:
            host = re.sub(r"^https?://", "", raw.strip().lower()).split("/")[0].removeprefix("www.")
            if not host:
                continue
            if not _DOMAIN.match(host):
                raise ValueError(f"'{raw}' is not a valid website address.")
            out.append(host)
        return list(dict.fromkeys(out))


@router.put(f"{_BASE}/business-profile")
def save_profile(organization_id: uuid.UUID, website_id: uuid.UUID, payload: ProfileUpdate, db: Session = Depends(get_db),
                 membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    """Saving is the confirmation: it records that a person reviewed these details."""
    website = get_website_or_404(db, organization_id, website_id)
    row = db.query(BusinessProfile).filter(BusinessProfile.website_id == website.id).one_or_none()
    if row is None:
        row = BusinessProfile(website_id=website.id)
        db.add(row)
    row.business_type, row.industry = (payload.business_type or "").strip() or None, (payload.industry or "").strip() or None
    row.offerings, row.target_customers, row.known_competitors = payload.offerings, payload.target_customers, payload.known_competitors
    row.objective = (payload.objective or "").strip() or None
    row.confirmed_at, row.confirmed_by = datetime.now(timezone.utc), membership.user_id
    db.add(AuditEvent(organization_id=organization_id, actor_user_id=membership.user_id, action="business_profile.confirm", resource_type="website",
                      resource_id=str(website.id), metadata_json={}))
    activity.record_event(db, website, "project", "business_profile_confirmed", "Business profile confirmed", dedupe_key=f"profile_confirmed:{website.id}:{row.confirmed_at.date()}")
    db.commit()
    return _profile_dict(row)


@router.post(f"{_BASE}/business-profile/suggest")
def suggest_profile(organization_id: uuid.UUID, website_id: uuid.UUID, db: Session = Depends(get_db),
                    membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    """AI suggestions from the site's own text. Stored as suggestions only; the confirmed fields are untouched."""
    from app.ai import business_profile as agent
    from app.ai.budget import BudgetExceeded

    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"business_profile_suggest:{website.id}", max_attempts=10, window_seconds=3600)
    try:
        suggestion = agent.suggest(db, website)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "no_pages", "message": str(exc)}) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": "ai_unavailable", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001 - never leak provider details
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail={"code": "ai_failed", "message": "The AI provider could not produce suggestions. Try again shortly."}) from exc
    row = db.query(BusinessProfile).filter(BusinessProfile.website_id == website.id).one_or_none()
    if row is None:
        row = BusinessProfile(website_id=website.id)
        db.add(row)
    row.ai_suggestions = {**suggestion, "generated_at": datetime.now(timezone.utc).isoformat()}
    db.commit()
    return _profile_dict(row)
