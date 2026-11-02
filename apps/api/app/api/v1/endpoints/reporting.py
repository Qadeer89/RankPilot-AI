import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.membership import Membership, MembershipRole
from app.models.report import Report
from app.models.usage_record import UsageRecord
from app.schemas.reporting import AuditEventResponse, ReportResponse, UsageMetricTotal, UsageResponse

router = APIRouter(tags=["reporting"])

DEFAULT_USAGE_WINDOW_DAYS = 30


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/reports",
    response_model=list[ReportResponse],
)
def list_reports(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[ReportResponse]:
    get_website_or_404(db, organization_id, website_id)
    reports = (
        db.query(Report)
        .filter(Report.website_id == website_id)
        .order_by(Report.period_end.desc())
        .all()
    )
    return [ReportResponse.model_validate(r) for r in reports]


@router.get("/organizations/{organization_id}/usage", response_model=UsageResponse)
def get_usage(
    organization_id: uuid.UUID,
    period_start: date | None = None,
    period_end: date | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> UsageResponse:
    period_end = period_end or date.today()
    period_start = period_start or (period_end - timedelta(days=DEFAULT_USAGE_WINDOW_DAYS))

    rows = (
        db.query(
            UsageRecord.metric,
            UsageRecord.unit,
            func.sum(UsageRecord.quantity),
            func.sum(UsageRecord.estimated_cost),
        )
        .filter(
            UsageRecord.organization_id == organization_id,
            UsageRecord.period_start >= period_start,
            UsageRecord.period_start <= period_end,
        )
        .group_by(UsageRecord.metric, UsageRecord.unit)
        .all()
    )

    totals = [
        UsageMetricTotal(metric=metric, unit=unit, quantity=float(quantity), estimated_cost=float(cost))
        for metric, unit, quantity, cost in rows
    ]
    return UsageResponse(
        organization_id=organization_id, period_start=period_start, period_end=period_end, totals=totals
    )


@router.get("/organizations/{organization_id}/audit-events", response_model=list[AuditEventResponse])
def list_audit_events(
    organization_id: uuid.UUID,
    limit: int = 100,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> list[AuditEventResponse]:
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.organization_id == organization_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [AuditEventResponse.model_validate(e) for e in events]
