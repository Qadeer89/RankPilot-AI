import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.crawler.orchestrator import create_crawl_job
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.change_record import ChangeRecord
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.membership import Membership, MembershipRole
from app.models.page import Page
from app.models.page_external_link import PageExternalLink
from app.models.page_image import PageImage
from app.models.page_indexing_status import PageIndexingStatus
from app.models.page_snapshot import PageSnapshot
from app.models.performance_metric import PerformanceMetric, PerformanceStrategy
from app.models.seo_finding import FindingStatus, SEOFinding
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import WebsiteStatus
from app.opportunities.health_score import get_score_history
from app.schemas.crawl import (
    CrawlJobResponse,
    PageExternalLinkSummaryResponse,
    PageImageSummaryResponse,
    PageIndexingStatusSummaryResponse,
    PageReportResponse,
    PageResponse,
    PageSnapshotSummaryResponse,
    PerformanceMetricSummaryResponse,
    SEOFindingResponse,
    SiteHealthScoreResponse,
    WebsiteOverviewResponse,
)
from app.schemas.execution import ChangeRecordResponse
from app.tasks.crawl import run_site_crawl

router = APIRouter(tags=["crawls"])

_ACTIVE_CRAWL_STATUSES = (CrawlStatus.pending, CrawlStatus.running)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/crawls",
    response_model=CrawlJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_crawl(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> CrawlJobResponse:
    website = get_website_or_404(db, organization_id, website_id)

    # RP13-010: a paused website shouldn't start new crawl activity either.
    if website.status != WebsiteStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Automation is paused for this website.")

    # RP13-011: a concurrent request must not create a second active crawl.
    existing = (
        db.query(CrawlJob)
        .filter(CrawlJob.website_id == website_id, CrawlJob.status.in_(_ACTIVE_CRAWL_STATUSES))
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"A crawl is already {existing.status.value} for this website (id {existing.id}).",
        )

    crawl_job = create_crawl_job(db, website, trigger=CrawlTrigger.manual)
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="crawl.trigger",
            resource_type="crawl_job",
            resource_id=str(crawl_job.id),
            metadata_json={},
        )
    )
    db.commit()

    run_site_crawl.delay(str(website.id), str(crawl_job.id))

    return CrawlJobResponse.model_validate(crawl_job)


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/crawls",
    response_model=list[CrawlJobResponse],
)
def list_crawls(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[CrawlJobResponse]:
    get_website_or_404(db, organization_id, website_id)
    jobs = (
        db.query(CrawlJob)
        .filter(CrawlJob.website_id == website_id)
        .order_by(CrawlJob.created_at.desc())
        .all()
    )
    return [CrawlJobResponse.model_validate(j) for j in jobs]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/crawls/{crawl_id}",
    response_model=CrawlJobResponse,
)
def get_crawl(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    crawl_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> CrawlJobResponse:
    get_website_or_404(db, organization_id, website_id)
    job = (
        db.query(CrawlJob)
        .filter(CrawlJob.id == crawl_id, CrawlJob.website_id == website_id)
        .one_or_none()
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Crawl job not found")
    return CrawlJobResponse.model_validate(job)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/crawls/{crawl_id}/cancel",
    response_model=CrawlJobResponse,
)
def cancel_crawl(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    crawl_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> CrawlJobResponse:
    """RP13-010: mark a crawl job for cancellation. The job itself (running
    in a worker) checks its own status between pages and stops at the next
    safe checkpoint rather than being killed mid-request.
    """
    get_website_or_404(db, organization_id, website_id)
    job = db.query(CrawlJob).filter(CrawlJob.id == crawl_id, CrawlJob.website_id == website_id).one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Crawl job not found")
    if job.status not in _ACTIVE_CRAWL_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"Crawl is already {job.status.value}; it cannot be cancelled."
        )

    job.status = CrawlStatus.cancelled
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="crawl.cancel",
            resource_type="crawl_job",
            resource_id=str(job.id),
            metadata_json={},
        )
    )
    db.commit()
    return CrawlJobResponse.model_validate(job)


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/pages",
    response_model=list[PageResponse],
)
def list_pages(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[PageResponse]:
    get_website_or_404(db, organization_id, website_id)
    pages = db.query(Page).filter(Page.website_id == website_id).order_by(Page.normalized_url).all()
    return [PageResponse.model_validate(p) for p in pages]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/findings",
    response_model=list[SEOFindingResponse],
)
def list_findings(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[SEOFindingResponse]:
    get_website_or_404(db, organization_id, website_id)
    query = db.query(SEOFinding).filter(SEOFinding.website_id == website_id)
    if status_filter:
        query = query.filter(SEOFinding.status == status_filter)
    findings = query.order_by(SEOFinding.last_detected_at.desc()).all()
    return [SEOFindingResponse.model_validate(f) for f in findings]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/health-score",
    response_model=list[SiteHealthScoreResponse],
)
def list_health_scores(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    limit: int = 30,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[SiteHealthScoreResponse]:
    """Most recent first (app/opportunities/health_score.py computes one
    row per crawl), so index 0 is "current" and the rest is history for
    a score-over-time chart."""
    website = get_website_or_404(db, organization_id, website_id)
    scores = get_score_history(db, website, limit=min(limit, 100))
    return [SiteHealthScoreResponse.model_validate(s) for s in scores]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/overview",
    response_model=WebsiteOverviewResponse,
)
def get_website_overview(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> WebsiteOverviewResponse:
    """Site Overview (RankPilot AI Phase 6): the few numbers a dashboard
    landing view needs in one call, each still backed by real
    already-computed data -- no new scoring logic here.
    """
    website = get_website_or_404(db, organization_id, website_id)

    pages_discovered = db.query(Page).filter(Page.website_id == website_id).count()

    has_indexing_data = (
        db.query(PageIndexingStatus)
        .join(Page, Page.id == PageIndexingStatus.page_id)
        .filter(Page.website_id == website_id)
        .first()
        is not None
    )
    pages_indexed = None
    if has_indexing_data:
        pages_indexed = (
            db.query(PageIndexingStatus)
            .join(Page, Page.id == PageIndexingStatus.page_id)
            .filter(Page.website_id == website_id, PageIndexingStatus.verdict == "PASS")
            .count()
        )

    pending_approvals = (
        db.query(SEOTask)
        .filter(SEOTask.website_id == website_id, SEOTask.approval_status == ApprovalStatus.pending)
        .count()
    )

    latest_scores = get_score_history(db, website, limit=1)
    latest_health_score = SiteHealthScoreResponse.model_validate(latest_scores[0]) if latest_scores else None

    return WebsiteOverviewResponse(
        pages_discovered=pages_discovered,
        pages_indexed=pages_indexed,
        pending_approvals=pending_approvals,
        latest_health_score=latest_health_score,
    )


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/pages/{page_id}/report",
    response_model=PageReportResponse,
)
def get_page_report(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    page_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> PageReportResponse:
    """Page-Level SEO Report (RankPilot AI Phase 6): aggregates every
    per-page data source into one call instead of the frontend
    stitching together several separate ones, each of which previously
    had no read endpoint at all (snapshot, images, external links,
    performance, indexing status).
    """
    get_website_or_404(db, organization_id, website_id)
    page = db.query(Page).filter(Page.id == page_id, Page.website_id == website_id).one_or_none()
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found.")

    latest_snapshot = (
        db.query(PageSnapshot)
        .filter(PageSnapshot.page_id == page_id)
        .order_by(PageSnapshot.fetched_at.desc())
        .first()
    )
    images = db.query(PageImage).filter(PageImage.page_id == page_id).all()
    external_links = db.query(PageExternalLink).filter(PageExternalLink.page_id == page_id).all()
    performance = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.page_id == page_id, PerformanceMetric.strategy == PerformanceStrategy.mobile)
        .one_or_none()
    )
    indexing_status = (
        db.query(PageIndexingStatus).filter(PageIndexingStatus.page_id == page_id).one_or_none()
    )
    findings = (
        db.query(SEOFinding)
        .filter(SEOFinding.page_id == page_id, SEOFinding.status == FindingStatus.open)
        .order_by(SEOFinding.last_detected_at.desc())
        .all()
    )
    change_history = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.page_id == page_id)
        .order_by(ChangeRecord.executed_at.desc())
        .all()
    )

    return PageReportResponse(
        page=PageResponse.model_validate(page),
        latest_snapshot=(
            PageSnapshotSummaryResponse(
                fetched_at=latest_snapshot.fetched_at,
                status_code=latest_snapshot.status_code,
                redirect_count=latest_snapshot.redirect_count,
                title=latest_snapshot.title,
                meta_description=latest_snapshot.meta_description,
                canonical_url=latest_snapshot.canonical_url,
                robots_directives=latest_snapshot.robots_directives,
                heading_sequence_json=latest_snapshot.heading_sequence_json,
                structured_data_json=latest_snapshot.schema_json,
                word_count=latest_snapshot.word_count,
                viewport_content=latest_snapshot.viewport_content,
                rel_next_url=latest_snapshot.rel_next_url,
                rel_prev_url=latest_snapshot.rel_prev_url,
            )
            if latest_snapshot
            else None
        ),
        images=[PageImageSummaryResponse.model_validate(i) for i in images],
        external_links=[PageExternalLinkSummaryResponse.model_validate(l) for l in external_links],
        performance=PerformanceMetricSummaryResponse.model_validate(performance) if performance else None,
        indexing_status=PageIndexingStatusSummaryResponse.model_validate(indexing_status) if indexing_status else None,
        findings=[SEOFindingResponse.model_validate(f) for f in findings],
        change_history=[ChangeRecordResponse.model_validate(c) for c in change_history],
    )
