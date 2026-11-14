"""Generic deployment/webhook-triggered re-crawl (RankPilot AI Phase 7
"Change Detection"). Any CMS or CI pipeline can hit this endpoint after
a deploy to re-crawl the site right away instead of waiting for the
next scheduled crawl -- the earlier GitHub post-deploy hook
(verify_github_deployment, app/execution/service.py) only re-checks
one specific prior change on one URL; this starts a full new crawl and
is not GitHub-specific.

Secret-authenticated rather than JWT-authenticated, since the caller
is an external system with no RankPilot user session -- the same
hash-compare pattern as WebsiteVerification.token_hash
(app/core/verification.py), not an OAuth/JWT concern.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.core.verification import generate_token, hash_token
from app.crawler.orchestrator import create_crawl_job
from app.db.session import get_db
from app.models.audit_event import AuditEvent
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.membership import Membership, MembershipRole
from app.models.website import Website, WebsiteStatus
from app.schemas.crawl import CrawlJobResponse
from app.schemas.deploy_webhook import RotateWebhookSecretResponse
from app.tasks.crawl import run_site_crawl

router = APIRouter(tags=["deploy-webhook"])

_ACTIVE_CRAWL_STATUSES = (CrawlStatus.pending, CrawlStatus.running)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/webhooks/deploy/rotate-secret",
    response_model=RotateWebhookSecretResponse,
)
def rotate_deploy_webhook_secret(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> RotateWebhookSecretResponse:
    """Generates a new secret and returns it in plaintext exactly once --
    only its hash is stored (Website.deploy_webhook_secret_hash), the
    same pattern as domain-ownership verification tokens. Rotating
    invalidates whatever the CMS/CI pipeline was configured with before.
    """
    website = get_website_or_404(db, organization_id, website_id)
    secret = generate_token()
    website.deploy_webhook_secret_hash = hash_token(secret)
    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.rotate_deploy_webhook_secret",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={},
        )
    )
    db.commit()
    return RotateWebhookSecretResponse(secret=secret)


@router.post(
    "/websites/{website_id}/webhooks/deploy",
    response_model=CrawlJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_deploy_webhook(
    website_id: uuid.UUID,
    x_rankpilot_webhook_secret: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CrawlJobResponse:
    """No organization_id in the path and no JWT -- an external CMS/CI
    system authenticates with the secret alone (X-RankPilot-Webhook-Secret).
    """
    website = db.get(Website, website_id)
    if website is None or website.deploy_webhook_secret_hash is None:
        # Same 404 whether the website doesn't exist or no secret has ever
        # been rotated for it -- distinguishing the two would let an
        # attacker enumerate valid website ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")

    if not x_rankpilot_webhook_secret or hash_token(x_rankpilot_webhook_secret) != website.deploy_webhook_secret_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret.")

    if website.status != WebsiteStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Automation is paused for this website.")

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

    crawl_job = create_crawl_job(db, website, trigger=CrawlTrigger.webhook)
    db.add(
        AuditEvent(
            organization_id=website.organization_id,
            actor_user_id=None,
            action="crawl.trigger_via_webhook",
            resource_type="crawl_job",
            resource_id=str(crawl_job.id),
            metadata_json={},
        )
    )
    db.commit()

    run_site_crawl.delay(str(website.id), str(crawl_job.id))

    return CrawlJobResponse.model_validate(crawl_job)
