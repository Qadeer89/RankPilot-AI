"""Fix titles that went live with the brand twice, from the app instead of a script.

`plan` only reads (it fetches the live pages politely and changes nothing). `tasks` re-plans on the server, so the
corrected values are never taken from the client, and creates tasks that always wait for a person's approval; nothing
goes live until each task is approved and executed in the normal Tasks flow."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.rate_limit import enforce_rate_limit
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.growth import title_repair
from app.models.audit_event import AuditEvent
from app.models.membership import Membership, MembershipRole

router = APIRouter(tags=["title-repair"])
_BASE = "/organizations/{organization_id}/websites/{website_id}/title-repair"
MAX_BATCH, MAX_SECONDS = 25, 40.0


def _plan_json(plan: title_repair.RepairPlan) -> dict:
    return {
        "candidates": [{"url": c.target_url, "live_title": c.live_title, "new_title": c.fixed_title} for c in plan.candidates],
        "skipped_already_pending": plan.skipped_already_pending, "skipped": dict(plan.skipped), "reason_none": plan.reason_none,
        "pages_with_applied_titles": plan.total_applied_pages, "stopped_early": plan.stopped_early,
    }


@router.post(f"{_BASE}/plan")
def plan(organization_id: uuid.UUID, website_id: uuid.UUID, limit: int = Query(10, ge=1, le=MAX_BATCH), db: Session = Depends(get_db),
         _m: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    """Read-only: which pages show the brand twice right now, and what each title would become."""
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"title_repair_plan:{website.id}", max_attempts=12, window_seconds=3600)
    return _plan_json(title_repair.plan_title_repairs(db, website, limit=limit, max_seconds=MAX_SECONDS))


@router.post(f"{_BASE}/tasks")
def create_tasks(organization_id: uuid.UUID, website_id: uuid.UUID, limit: int = Query(10, ge=1, le=MAX_BATCH), db: Session = Depends(get_db),
                 membership: Membership = Depends(RequireRole(MembershipRole.editor))) -> dict:
    """Create approval-pending tasks for the next batch. Does not change the website."""
    website = get_website_or_404(db, organization_id, website_id)
    enforce_rate_limit(f"title_repair_tasks:{website.id}", max_attempts=12, window_seconds=3600)
    result = title_repair.plan_title_repairs(db, website, limit=limit, max_seconds=MAX_SECONDS)
    created = title_repair.create_repair_tasks(db, website, result.candidates, requested_by=membership.user_id) if result.candidates else []
    db.add(AuditEvent(organization_id=organization_id, actor_user_id=membership.user_id, action="title_repair.create_tasks", resource_type="website",
                      resource_id=str(website.id), metadata_json={"tasks": len(created)}))
    db.commit()
    return {"created": len(created), "plan": _plan_json(result), "message": "Tasks were created and are waiting for your approval in the Tasks tab. Nothing has been changed on your website."}
