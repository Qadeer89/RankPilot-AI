"""Read-only growth insights: the SEO improvement timeline and AI usage
(SEO Growth Engine spec sections 9 and 12).
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import RequireRole, require_platform_admin
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.growth.performance import ALLOWED_WINDOWS, build_performance_timeline
from app.models.agent_run import AgentRun
from app.models.membership import Membership, MembershipRole
from app.models.user import User
from app.models.website import Website

router = APIRouter(tags=["growth-insights"])


@router.get("/organizations/{organization_id}/websites/{website_id}/performance-timeline")
def get_performance_timeline(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    window_days: int = 28,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    website = get_website_or_404(db, organization_id, website_id)
    if window_days not in ALLOWED_WINDOWS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"window_days must be one of {list(ALLOWED_WINDOWS)}.")
    return build_performance_timeline(db, website, window_days=window_days)


def _usage_rows(db: Session, since: datetime, *group_by, website_id: uuid.UUID | None = None):
    query = db.query(
        *group_by,
        func.count(AgentRun.id),
        func.coalesce(func.sum(AgentRun.input_tokens), 0),
        func.coalesce(func.sum(AgentRun.output_tokens), 0),
        func.coalesce(func.sum(AgentRun.estimated_cost), 0.0),
    ).filter(AgentRun.started_at >= since)
    if website_id is not None:
        query = query.filter(AgentRun.website_id == website_id)
    return query.group_by(*group_by).all()


@router.get("/organizations/{organization_id}/websites/{website_id}/ai-usage")
def get_website_ai_usage(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> dict:
    get_website_or_404(db, organization_id, website_id)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = _usage_rows(db, since, AgentRun.agent_type, website_id=website_id)
    by_agent = [
        {
            "agent_type": agent_type.value,
            "runs": runs,
            "input_tokens": int(tokens_in),
            "output_tokens": int(tokens_out),
            "estimated_cost_usd": round(float(cost), 4),
        }
        for agent_type, runs, tokens_in, tokens_out, cost in rows
    ]
    return {
        "days": days,
        "by_agent_type": by_agent,
        "total_estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in by_agent), 4),
        "note": "Costs are estimates from token counts. Chat-assistant and embedding calls are not included.",
    }


@router.get("/admin/ai-usage")
def get_platform_ai_usage(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_platform_admin),
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = _usage_rows(db, since, AgentRun.website_id)
    names = dict(db.query(Website.id, Website.display_name).all())
    by_website = sorted(
        (
            {
                "website_id": str(website_id),
                "website_name": names.get(website_id),
                "runs": runs,
                "input_tokens": int(tokens_in),
                "output_tokens": int(tokens_out),
                "estimated_cost_usd": round(float(cost), 4),
            }
            for website_id, runs, tokens_in, tokens_out, cost in rows
        ),
        key=lambda r: r["estimated_cost_usd"],
        reverse=True,
    )
    return {
        "days": days,
        "by_website": by_website,
        "total_estimated_cost_usd": round(sum(r["estimated_cost_usd"] for r in by_website), 4),
        "note": "Costs are estimates from token counts. Chat-assistant and embedding calls are not included.",
    }
