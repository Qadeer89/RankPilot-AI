import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.schemas import OpportunityProposal
from app.core.deps import RequireRole
from app.core.resources import get_website_or_404
from app.db.session import get_db
from app.execution.connections import (
    connect_github,
    connect_sanity,
    connect_shopify,
    connect_webflow,
    connect_wordpress,
    disconnect_github,
    disconnect_sanity,
    disconnect_shopify,
    disconnect_webflow,
    disconnect_wordpress,
)
from app.execution.service import (
    ExecutionBlocked,
    approve_task,
    cancel_task,
    create_tasks_from_proposal,
    dry_run_task,
    execute_task,
    reject_task,
    rollback_change,
    verify_github_deployment,
)
from app.models.audit_event import AuditEvent
from app.models.change_record import ChangeRecord
from app.models.membership import Membership, MembershipRole
from app.models.rollback_record import RollbackRecord
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import SEOTask
from app.models.website_connection import WebsiteConnection
from app.schemas.execution import (
    ApprovalDecisionRequest,
    ChangeRecordResponse,
    DeploymentVerificationResponse,
    DryRunResponse,
    GitHubConnectRequest,
    RollbackRecordResponse,
    SanityConnectRequest,
    SEOTaskResponse,
    ShopifyConnectRequest,
    WebflowConnectRequest,
    WebsiteConnectionResponse,
    WordPressConnectRequest,
    WritesEnabledRequest,
)

router = APIRouter(tags=["execution"])


def _get_task_or_404(db: Session, website_id: uuid.UUID, task_id: uuid.UUID) -> SEOTask:
    task = db.query(SEOTask).filter(SEOTask.id == task_id, SEOTask.website_id == website_id).one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _get_change_record_or_404(db: Session, website_id: uuid.UUID, change_id: uuid.UUID) -> ChangeRecord:
    record = (
        db.query(ChangeRecord)
        .filter(ChangeRecord.id == change_id, ChangeRecord.website_id == website_id)
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Change record not found")
    return record


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/connections/wordpress",
    response_model=WebsiteConnectionResponse,
)
def connect_wordpress_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: WordPressConnectRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteConnectionResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        connection = connect_wordpress(db, website, payload.username, payload.application_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="connector.wordpress.connect",
            resource_type="website_connection",
            resource_id=str(connection.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteConnectionResponse.model_validate(connection)


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/connections/wordpress",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_wordpress_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = get_website_or_404(db, organization_id, website_id)
    disconnect_wordpress(db, website)
    db.commit()


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/connections/shopify",
    response_model=WebsiteConnectionResponse,
)
def connect_shopify_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: ShopifyConnectRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteConnectionResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        connection = connect_shopify(db, website, payload.shop_domain, payload.access_token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="connector.shopify.connect",
            resource_type="website_connection",
            resource_id=str(connection.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteConnectionResponse.model_validate(connection)


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/connections/shopify",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_shopify_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = get_website_or_404(db, organization_id, website_id)
    disconnect_shopify(db, website)
    db.commit()


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/connections/webflow",
    response_model=WebsiteConnectionResponse,
)
def connect_webflow_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: WebflowConnectRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteConnectionResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        connection = connect_webflow(db, website, payload.site_id, payload.access_token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="connector.webflow.connect",
            resource_type="website_connection",
            resource_id=str(connection.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteConnectionResponse.model_validate(connection)


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/connections/webflow",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_webflow_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = get_website_or_404(db, organization_id, website_id)
    disconnect_webflow(db, website)
    db.commit()


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/connections/github",
    response_model=WebsiteConnectionResponse,
)
def connect_github_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: GitHubConnectRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteConnectionResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        connection = connect_github(db, website, payload.owner, payload.repo, payload.base_branch, payload.access_token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="connector.github.connect",
            resource_type="website_connection",
            resource_id=str(connection.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteConnectionResponse.model_validate(connection)


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/connections/github",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_github_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = get_website_or_404(db, organization_id, website_id)
    disconnect_github(db, website)
    db.commit()


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/connections/sanity",
    response_model=WebsiteConnectionResponse,
)
def connect_sanity_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: SanityConnectRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WebsiteConnectionResponse:
    website = get_website_or_404(db, organization_id, website_id)
    try:
        connection = connect_sanity(db, website, payload.project_id, payload.dataset, payload.token)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="connector.sanity.connect",
            resource_type="website_connection",
            resource_id=str(connection.id),
            metadata_json={},
        )
    )
    db.commit()
    return WebsiteConnectionResponse.model_validate(connection)


@router.delete(
    "/organizations/{organization_id}/websites/{website_id}/connections/sanity",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect_sanity_connector(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> None:
    website = get_website_or_404(db, organization_id, website_id)
    disconnect_sanity(db, website)
    db.commit()


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/connections",
    response_model=list[WebsiteConnectionResponse],
)
def list_connections(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[WebsiteConnectionResponse]:
    get_website_or_404(db, organization_id, website_id)
    connections = db.query(WebsiteConnection).filter(WebsiteConnection.website_id == website_id).all()
    return [WebsiteConnectionResponse.model_validate(c) for c in connections]


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/opportunities/{opportunity_id}/tasks",
    response_model=list[SEOTaskResponse],
)
def create_tasks(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    payload: OpportunityProposal,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> list[SEOTaskResponse]:
    website = get_website_or_404(db, organization_id, website_id)
    opportunity = (
        db.query(SEOOpportunity)
        .filter(SEOOpportunity.id == opportunity_id, SEOOpportunity.website_id == website_id)
        .one_or_none()
    )
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    try:
        tasks = create_tasks_from_proposal(db, website, opportunity, payload, requested_by=membership.user_id)
    except ExecutionBlocked as exc:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.commit()
    return [SEOTaskResponse.model_validate(t) for t in tasks]


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/tasks",
    response_model=list[SEOTaskResponse],
)
def list_tasks(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> list[SEOTaskResponse]:
    get_website_or_404(db, organization_id, website_id)
    tasks = db.query(SEOTask).filter(SEOTask.website_id == website_id).order_by(SEOTask.created_at.desc()).all()
    return [SEOTaskResponse.model_validate(t) for t in tasks]


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/tasks/{task_id}/approve",
    response_model=SEOTaskResponse,
)
def approve(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> SEOTaskResponse:
    get_website_or_404(db, organization_id, website_id)
    task = _get_task_or_404(db, website_id, task_id)
    try:
        approve_task(db, task, decided_by=membership.user_id, reason=payload.reason)
    except ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="seo_task.approve",
            resource_type="seo_task",
            resource_id=str(task.id),
            metadata_json={"reason": payload.reason},
        )
    )
    db.commit()
    return SEOTaskResponse.model_validate(task)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/tasks/{task_id}/reject",
    response_model=SEOTaskResponse,
)
def reject(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> SEOTaskResponse:
    get_website_or_404(db, organization_id, website_id)
    task = _get_task_or_404(db, website_id, task_id)
    try:
        reject_task(db, task, decided_by=membership.user_id, reason=payload.reason)
    except ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="seo_task.reject",
            resource_type="seo_task",
            resource_id=str(task.id),
            metadata_json={"reason": payload.reason},
        )
    )
    db.commit()
    return SEOTaskResponse.model_validate(task)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/tasks/{task_id}/cancel",
    response_model=SEOTaskResponse,
)
def cancel(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    task_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> SEOTaskResponse:
    get_website_or_404(db, organization_id, website_id)
    task = _get_task_or_404(db, website_id, task_id)
    try:
        cancel_task(db, task, decided_by=membership.user_id, reason=payload.reason)
    except ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="seo_task.cancel",
            resource_type="seo_task",
            resource_id=str(task.id),
            metadata_json={"reason": payload.reason},
        )
    )
    db.commit()
    return SEOTaskResponse.model_validate(task)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/tasks/{task_id}/execute",
    response_model=ChangeRecordResponse,
)
def execute(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> ChangeRecordResponse:
    website = get_website_or_404(db, organization_id, website_id)
    task = _get_task_or_404(db, website_id, task_id)

    try:
        change_record = execute_task(db, website, task)
    except ExecutionBlocked as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="seo_task.execute",
            resource_type="change_record",
            resource_id=str(change_record.id),
            metadata_json={"validation_status": change_record.validation_status.value},
        )
    )
    db.commit()
    return ChangeRecordResponse.model_validate(change_record)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/tasks/{task_id}/dry-run",
    response_model=DryRunResponse,
)
def dry_run(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> DryRunResponse:
    """Preview what executing this task would change, without writing
    anything (CW-009). Also records the live value it read so a later
    `execute` call can detect whether the target changed in the meantime
    (CW-008's stale-revision check in execution/service.py)."""
    website = get_website_or_404(db, organization_id, website_id)
    task = _get_task_or_404(db, website_id, task_id)

    try:
        diff = dry_run_task(db, website, task)
    except ExecutionBlocked as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="seo_task.dry_run",
            resource_type="seo_task",
            resource_id=str(task.id),
            metadata_json={"changed": diff["changed"]},
        )
    )
    db.commit()
    return DryRunResponse(**diff)


@router.put(
    "/organizations/{organization_id}/websites/{website_id}/writes-enabled",
    response_model=WritesEnabledRequest,
)
def set_writes_enabled(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    payload: WritesEnabledRequest,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> WritesEnabledRequest:
    """The write-specific kill switch (CW-004): blocks new connector
    writes immediately without pausing crawling/monitoring, which
    `website.status = paused` would also do."""
    website = get_website_or_404(db, organization_id, website_id)
    website.writes_enabled = payload.writes_enabled

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="website.writes_enabled.set",
            resource_type="website",
            resource_id=str(website.id),
            metadata_json={"writes_enabled": payload.writes_enabled},
        )
    )
    db.commit()
    return WritesEnabledRequest(writes_enabled=website.writes_enabled)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/change-records/{change_id}/verify-deployment",
    response_model=DeploymentVerificationResponse,
)
def verify_deployment(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.editor)),
) -> DeploymentVerificationResponse:
    """CW-014: re-crawl the live URL for a GitHub-connector change and
    confirm it actually shipped. Call this once the PR has been reviewed,
    merged, and the site redeployed -- RankPilot does not control or
    observe that deploy pipeline, so it cannot trigger this automatically."""
    website = get_website_or_404(db, organization_id, website_id)
    change_record = _get_change_record_or_404(db, website_id, change_id)

    try:
        verification = verify_github_deployment(db, website, change_record)
    except ExecutionBlocked as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="change_record.verify_deployment",
            resource_type="change_record",
            resource_id=str(change_record.id),
            metadata_json={"verified": verification["verified"]},
        )
    )
    db.commit()
    return DeploymentVerificationResponse(**verification)


@router.get(
    "/organizations/{organization_id}/websites/{website_id}/change-records/{change_id}",
    response_model=ChangeRecordResponse,
)
def get_change_record(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    _membership: Membership = Depends(RequireRole(MembershipRole.viewer)),
) -> ChangeRecordResponse:
    get_website_or_404(db, organization_id, website_id)
    record = _get_change_record_or_404(db, website_id, change_id)
    return ChangeRecordResponse.model_validate(record)


@router.post(
    "/organizations/{organization_id}/websites/{website_id}/change-records/{change_id}/rollback",
    response_model=RollbackRecordResponse,
)
def rollback(
    organization_id: uuid.UUID,
    website_id: uuid.UUID,
    change_id: uuid.UUID,
    db: Session = Depends(get_db),
    membership: Membership = Depends(RequireRole(MembershipRole.admin)),
) -> RollbackRecordResponse:
    website = get_website_or_404(db, organization_id, website_id)
    change_record = _get_change_record_or_404(db, website_id, change_id)

    existing_rollback = (
        db.query(RollbackRecord).filter(RollbackRecord.change_record_id == change_record.id).one_or_none()
    )
    if existing_rollback is not None:
        return RollbackRecordResponse.model_validate(existing_rollback)

    rollback_record = rollback_change(db, change_record, initiated_by=membership.user_id, website=website)

    db.add(
        AuditEvent(
            organization_id=organization_id,
            actor_user_id=membership.user_id,
            action="change_record.rollback",
            resource_type="rollback_record",
            resource_id=str(rollback_record.id),
            metadata_json={"status": rollback_record.status.value},
        )
    )
    db.commit()
    return RollbackRecordResponse.model_validate(rollback_record)
