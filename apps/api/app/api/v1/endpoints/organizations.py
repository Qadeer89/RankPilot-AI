import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_organization_or_404
from app.db.session import get_db
from app.models.crawl_job import CrawlJob
from app.models.membership import Membership, MembershipRole
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import Website
from app.notifications.slack import send_slack_notification, set_slack_webhook_url
from app.schemas.organization import (
    MemberResponse,
    OrganizationResponse,
    OrganizationSettingsUpdateRequest,
    SlackTestResultResponse,
    WebsiteOverviewRow,
)

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


@router.get(
    "/organizations/{organization_id}/overview",
    response_model=list[WebsiteOverviewRow],
)
def get_organization_overview(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[WebsiteOverviewRow]:
    """An agency-style multi-client view: one row per website in the
    organization with just enough to triage which ones need attention,
    without opening each website's own detail page.
    """
    websites = db.query(Website).filter(Website.organization_id == organization_id).all()
    if not websites:
        return []
    website_ids = [w.id for w in websites]

    findings_counts: dict[uuid.UUID, int] = dict(
        db.query(SEOFinding.website_id, func.count(SEOFinding.id))
        .filter(SEOFinding.website_id.in_(website_ids), SEOFinding.status == FindingStatus.open)
        .group_by(SEOFinding.website_id)
        .all()
    )

    opportunities_counts: dict[uuid.UUID, int] = dict(
        db.query(SEOOpportunity.website_id, func.count(SEOOpportunity.id))
        .filter(SEOOpportunity.website_id.in_(website_ids), SEOOpportunity.status == OpportunityStatus.open)
        .group_by(SEOOpportunity.website_id)
        .all()
    )

    pending_tasks_counts: dict[uuid.UUID, int] = dict(
        db.query(SEOTask.website_id, func.count(SEOTask.id))
        .filter(SEOTask.website_id.in_(website_ids), SEOTask.approval_status == ApprovalStatus.pending)
        .group_by(SEOTask.website_id)
        .all()
    )

    last_crawl_by_website: dict[uuid.UUID, CrawlJob] = {}
    for crawl_job in (
        db.query(CrawlJob)
        .filter(CrawlJob.website_id.in_(website_ids))
        .order_by(CrawlJob.website_id, CrawlJob.created_at.desc())
        .all()
    ):
        if crawl_job.website_id not in last_crawl_by_website:
            last_crawl_by_website[crawl_job.website_id] = crawl_job

    rows = []
    for website in websites:
        last_crawl = last_crawl_by_website.get(website.id)
        rows.append(
            WebsiteOverviewRow(
                website_id=website.id,
                display_name=website.display_name,
                hostname=website.hostname,
                verification_status=website.verification_status.value,
                status=website.status.value,
                open_findings_count=findings_counts.get(website.id, 0),
                open_opportunities_count=opportunities_counts.get(website.id, 0),
                pending_tasks_count=pending_tasks_counts.get(website.id, 0),
                last_crawl_at=last_crawl.started_at if last_crawl else None,
                last_crawl_status=last_crawl.status.value if last_crawl else None,
            )
        )
    return rows


@router.patch("/organizations/{organization_id}/settings", response_model=OrganizationResponse)
def update_organization_settings(
    organization_id: uuid.UUID,
    payload: OrganizationSettingsUpdateRequest,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> OrganizationResponse:
    organization = get_organization_or_404(db, organization_id)
    set_slack_webhook_url(db, organization, payload.slack_webhook_url)
    db.commit()
    return OrganizationResponse.model_validate(organization)


@router.post(
    "/organizations/{organization_id}/notifications/slack/test",
    response_model=SlackTestResultResponse,
)
def send_slack_test_notification(
    organization_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> SlackTestResultResponse:
    organization = get_organization_or_404(db, organization_id)
    notification = send_slack_notification(
        db,
        organization,
        website_id=None,
        event_type="test",
        message="This is a test notification from RankPilot AI. If you can see this, Slack notifications are working.",
    )
    db.commit()
    if notification.status.value == "skipped_not_configured":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="No Slack webhook URL is configured for this organization."
        )
    return SlackTestResultResponse(status=notification.status.value)
