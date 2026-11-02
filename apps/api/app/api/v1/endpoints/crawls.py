import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.crawler.orchestrator import create_crawl_job
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.crawl_job import CrawlJob, CrawlTrigger
from app.models.membership import Membership, MembershipRole
from app.models.page import Page
from app.models.seo_finding import SEOFinding
from app.schemas.crawl import CrawlJobResponse, PageResponse, SEOFindingResponse
from app.tasks.crawl import run_site_crawl

router = APIRouter(tags=["crawls"])


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
