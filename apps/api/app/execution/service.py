"""The execution protocol (SEO_AUTOMATION_ENGINE.md #5): turn an approved,
risk-gated SEO task into one bounded WordPress write, with before/after
evidence and deterministic post-change validation. Automatic rollback
only ever runs when validation fails right after the write it's
undoing — it is never a general-purpose "undo" tool.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.ai.schemas import OpportunityProposal
from app.connectors import github_pr, sanity, shopify, webflow
from app.connectors import wordpress as wordpress_connector
from app.connectors.errors import ConnectorError
from app.crawler.fetch import FetchError, safe_fetch
from app.connectors.wordpress import (
    UnsupportedOperation,
    WordPressConnectorError,
    current_meta_description,
    current_title,
    find_post_by_url,
    get_resource,
    update_meta_description,
    update_title,
)
from app.execution import policy
from app.execution.connections import (
    get_connected_content_connector,
    get_connector_credentials,
    get_wordpress_credentials,
)
from app.execution.validation import validate_wordpress_change
from app.models.approval import Approval, ApprovalDecision
from app.models.change_record import ChangeActorType, ChangeRecord, ValidationStatus
from app.models.rollback_record import RollbackRecord, RollbackStatus
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.website import Website, WebsiteStatus
from app.models.website_connection import ConnectorType


class ExecutionBlocked(RuntimeError):
    pass


# Connector modules sharing the standardized find_target/get_current_value/
# apply_change/validate_change/rollback function set (everything except
# WordPress, which keeps its own historical function names and code path
# below unchanged).
GENERIC_CONNECTOR_MODULES = {
    ConnectorType.shopify: shopify,
    ConnectorType.webflow: webflow,
    ConnectorType.github: github_pr,
    ConnectorType.sanity: sanity,
}

# Declared capability registry (CW-001, custom-website-write addendum §4.3):
# the operations each connector type actually implements. Both proposal
# creation and execution consult this before touching a connector, so an
# unsupported operation is rejected cleanly instead of failing deep inside
# a write call or with a raw AttributeError/KeyError.
CONNECTOR_CAPABILITIES: dict[ConnectorType, frozenset[str]] = {
    ConnectorType.wordpress: wordpress_connector.SUPPORTED_OPERATIONS,
    ConnectorType.shopify: shopify.SUPPORTED_OPERATIONS,
    ConnectorType.webflow: webflow.SUPPORTED_OPERATIONS,
    ConnectorType.github: github_pr.SUPPORTED_OPERATIONS,
    ConnectorType.sanity: sanity.SUPPORTED_OPERATIONS,
}


def get_connector_capabilities(connector_type: ConnectorType) -> frozenset[str]:
    """What a connector type can actually do — the source of truth the UI
    and planner should consult so they never offer an operation the
    connector doesn't support (addendum §4.3)."""
    return CONNECTOR_CAPABILITIES[connector_type]


def _idempotency_key(website_id: uuid.UUID, opportunity_id: uuid.UUID, operation: str, target_url: str) -> str:
    return hashlib.sha256(f"{website_id}:{opportunity_id}:{operation}:{target_url}".encode("utf-8")).hexdigest()


def create_tasks_from_proposal(
    db: Session,
    website: Website,
    opportunity: SEOOpportunity,
    proposal: OpportunityProposal,
    *,
    requested_by: uuid.UUID,
) -> list[SEOTask]:
    """One SEOTask per proposed action, idempotent per (website,
    opportunity, operation, target_url) so retried requests don't create
    duplicate tasks (RP-0701).
    """
    if policy.is_risk_tier_blocked(proposal.risk_tier):
        raise ExecutionBlocked(f"Risk tier {proposal.risk_tier} is blocked; no task was created.")

    # If a connector is already connected, reject an unsupported operation
    # now rather than letting it reach execution (CW-001): the planner
    # should never offer, and the backend should never queue, a change a
    # connected connector can't actually perform.
    connected_connector_type = get_connected_content_connector(db, website)
    if connected_connector_type is not None:
        capabilities = get_connector_capabilities(connected_connector_type)
        for action in proposal.proposed_actions:
            if action.operation not in capabilities:
                raise ExecutionBlocked(
                    f"Operation '{action.operation}' is not supported by the "
                    f"{connected_connector_type.value} connector; no task was created."
                )

    tasks: list[SEOTask] = []
    for action in proposal.proposed_actions:
        idempotency_key = _idempotency_key(website.id, opportunity.id, action.operation, action.target_url)

        existing = db.query(SEOTask).filter(SEOTask.idempotency_key == idempotency_key).one_or_none()
        if existing is not None:
            tasks.append(existing)
            continue

        approval_needed = policy.requires_approval(website, proposal.risk_tier, action.operation)
        task = SEOTask(
            website_id=website.id,
            opportunity_id=opportunity.id,
            task_type=action.operation,
            risk_tier=proposal.risk_tier,
            proposed_change_json={
                "operation": action.operation,
                "target_url": action.target_url,
                "value": action.value,
                "summary": proposal.summary,
                "evidence": [e.model_dump() for e in proposal.evidence],
                "validation_plan": proposal.validation_plan,
            },
            approval_status=ApprovalStatus.pending if approval_needed else ApprovalStatus.not_required,
            status=SEOTaskStatus.pending,
            idempotency_key=idempotency_key,
        )
        db.add(task)
        db.flush()

        if approval_needed:
            db.add(Approval(seo_task_id=task.id, requested_by=requested_by, decision=ApprovalDecision.pending))

        tasks.append(task)

    db.flush()
    return tasks


def approve_task(db: Session, task: SEOTask, *, decided_by: uuid.UUID, reason: str | None = None) -> SEOTask:
    if task.approval_status != ApprovalStatus.pending:
        raise ExecutionBlocked(f"Task is not awaiting approval (current status: {task.approval_status.value}).")

    approval = (
        db.query(Approval)
        .filter(Approval.seo_task_id == task.id, Approval.decision == ApprovalDecision.pending)
        .order_by(Approval.created_at.desc())
        .first()
    )
    if approval is not None:
        approval.decision = ApprovalDecision.approved
        approval.decided_by = decided_by
        approval.reason = reason
        approval.decided_at = datetime.now(timezone.utc)

    task.approval_status = ApprovalStatus.approved
    db.flush()
    return task


def reject_task(db: Session, task: SEOTask, *, decided_by: uuid.UUID, reason: str | None = None) -> SEOTask:
    if task.approval_status != ApprovalStatus.pending:
        raise ExecutionBlocked(f"Task is not awaiting approval (current status: {task.approval_status.value}).")

    approval = (
        db.query(Approval)
        .filter(Approval.seo_task_id == task.id, Approval.decision == ApprovalDecision.pending)
        .order_by(Approval.created_at.desc())
        .first()
    )
    if approval is not None:
        approval.decision = ApprovalDecision.rejected
        approval.decided_by = decided_by
        approval.reason = reason
        approval.decided_at = datetime.now(timezone.utc)

    task.approval_status = ApprovalStatus.rejected
    task.status = SEOTaskStatus.rejected
    db.flush()
    return task


def dry_run_task(db: Session, website: Website, task: SEOTask) -> dict:
    """Read the connector's current value and compute the diff an
    execution would make, without ever calling apply_change (CW-009,
    addendum §6 Level 2 / §7 "Before execution": "Run dry-run and show a
    human-readable diff").

    Also records the live value it just read as `expected_before_value`
    on the task, so a later `execute_task` call can detect whether the
    target changed between this dry-run and execution (the stale-revision
    check in `execute_task`) instead of silently overwriting a concurrent
    edit (CW-008).
    """
    connector_type = get_connected_content_connector(db, website)
    if connector_type is None:
        raise ExecutionBlocked("No content connector is connected for this website.")

    change = task.proposed_change_json
    operation = change["operation"]
    target_url = change["target_url"]
    proposed_value = change["value"]

    if operation not in CONNECTOR_CAPABILITIES[connector_type]:
        raise ExecutionBlocked(f"Operation '{operation}' is not supported by the {connector_type.value} connector.")

    if connector_type == ConnectorType.wordpress:
        try:
            credentials = get_wordpress_credentials(db, website)
        except LookupError as exc:
            raise ExecutionBlocked(str(exc)) from exc
        try:
            post_type, post_id = find_post_by_url(credentials, target_url)
            resource = get_resource(credentials, post_type, post_id)
            current_value = current_title(resource) if operation == "set_title" else current_meta_description(resource)
        except (WordPressConnectorError, UnsupportedOperation) as exc:
            raise ExecutionBlocked(str(exc)) from exc
    else:
        module = GENERIC_CONNECTOR_MODULES[connector_type]
        try:
            credentials = get_connector_credentials(db, website, connector_type)
        except LookupError as exc:
            raise ExecutionBlocked(str(exc)) from exc
        try:
            target_ref = module.find_target(credentials, target_url)
            current_value = module.get_current_value(credentials, target_ref, operation)
        except ConnectorError as exc:
            raise ExecutionBlocked(str(exc)) from exc

    change["expected_before_value"] = current_value
    change["dry_run_at"] = datetime.now(timezone.utc).isoformat()
    task.proposed_change_json = dict(change)  # reassign so SQLAlchemy detects the JSON mutation
    db.flush()

    return {
        "operation": operation,
        "target_url": target_url,
        "before_value": current_value,
        "proposed_value": proposed_value,
        "changed": current_value != proposed_value,
    }


def execute_task(db: Session, website: Website, task: SEOTask) -> ChangeRecord:
    if website.status != WebsiteStatus.active:
        raise ExecutionBlocked("Automation is paused for this website.")
    if not website.writes_enabled:
        raise ExecutionBlocked(
            "Writes are disabled for this website (kill switch). Crawling and analysis are unaffected; "
            "re-enable writes to resume execution."
        )
    if policy.is_risk_tier_blocked(task.risk_tier):
        raise ExecutionBlocked(f"Risk tier {task.risk_tier} is blocked.")
    if task.approval_status == ApprovalStatus.pending:
        raise ExecutionBlocked("This task is still awaiting approval.")
    if task.approval_status == ApprovalStatus.rejected:
        raise ExecutionBlocked("This task was rejected and cannot be executed.")
    if task.status in (SEOTaskStatus.completed, SEOTaskStatus.executing):
        raise ExecutionBlocked(f"Task is already {task.status.value}; idempotent re-execution is not performed.")

    connector_type = get_connected_content_connector(db, website)
    if connector_type is None:
        raise ExecutionBlocked("No content connector is connected for this website.")

    change = task.proposed_change_json
    operation = change["operation"]
    target_url = change["target_url"]
    new_value = change["value"]
    expected_before_value = change.get("expected_before_value")

    if operation not in CONNECTOR_CAPABILITIES[connector_type]:
        task.status = SEOTaskStatus.failed
        db.flush()
        raise ExecutionBlocked(f"Operation '{operation}' is not supported by the {connector_type.value} connector.")

    task.status = SEOTaskStatus.executing
    db.flush()

    if connector_type == ConnectorType.wordpress:
        try:
            credentials = get_wordpress_credentials(db, website)
        except LookupError as exc:
            raise ExecutionBlocked(str(exc)) from exc

        try:
            post_type, post_id = find_post_by_url(credentials, target_url)
            before = get_resource(credentials, post_type, post_id)
            if operation == "set_title":
                before_value = current_title(before)
            elif operation == "set_meta_description":
                before_value = current_meta_description(before)
            else:
                raise ValueError(f"Unsupported operation: {operation}")

            if expected_before_value is not None and before_value != expected_before_value:
                task.status = SEOTaskStatus.failed
                db.flush()
                raise ExecutionBlocked(
                    "Stale revision: this value changed since the proposal was planned "
                    f"(expected {expected_before_value!r}, found {before_value!r}). Re-plan before executing."
                )

            if operation == "set_title":
                update_title(credentials, post_type, post_id, new_value)
            elif operation == "set_meta_description":
                update_meta_description(credentials, post_type, post_id, new_value)
            else:
                raise ValueError(f"Unsupported operation: {operation}")

            passed, validation_evidence = validate_wordpress_change(
                credentials, post_type, post_id, operation, new_value
            )

            change_record = ChangeRecord(
                website_id=website.id,
                page_id=None,
                seo_task_id=task.id,
                connector_type=ConnectorType.wordpress,
                before_state_json={"operation": operation, "post_type": post_type, "post_id": post_id, "value": before_value},
                after_state_json={"value": new_value, "validation_evidence": validation_evidence},
                actor_type=ChangeActorType.system,
                executed_at=datetime.now(timezone.utc),
                validation_status=ValidationStatus.passed if passed else ValidationStatus.failed,
            )
            db.add(change_record)
            db.flush()

            if passed:
                task.status = SEOTaskStatus.completed
            else:
                task.status = SEOTaskStatus.failed
                rollback_change(db, change_record, initiated_by=None, website=website)

            db.flush()
            return change_record

        except (WordPressConnectorError, UnsupportedOperation) as exc:
            task.status = SEOTaskStatus.failed
            db.flush()
            raise ExecutionBlocked(str(exc)) from exc

    # Generic path shared by Shopify, Webflow, and the GitHub PR connector.
    module = GENERIC_CONNECTOR_MODULES[connector_type]
    try:
        credentials = get_connector_credentials(db, website, connector_type)
    except LookupError as exc:
        raise ExecutionBlocked(str(exc)) from exc

    try:
        target_ref = module.find_target(credentials, target_url)
        before_value = module.get_current_value(credentials, target_ref, operation)

        if expected_before_value is not None and before_value != expected_before_value:
            task.status = SEOTaskStatus.failed
            db.flush()
            raise ExecutionBlocked(
                "Stale revision: this value changed since the proposal was planned "
                f"(expected {expected_before_value!r}, found {before_value!r}). Re-plan before executing."
            )

        apply_result = module.apply_change(credentials, target_ref, operation, new_value)
        passed, validation_evidence = module.validate_change(credentials, target_ref, operation, new_value, apply_result)

        change_record = ChangeRecord(
            website_id=website.id,
            page_id=None,
            seo_task_id=task.id,
            connector_type=connector_type,
            before_state_json={"operation": operation, "target_ref": target_ref, "value": before_value},
            after_state_json={"apply_result": apply_result, "validation_evidence": validation_evidence},
            actor_type=ChangeActorType.system,
            executed_at=datetime.now(timezone.utc),
            validation_status=ValidationStatus.passed if passed else ValidationStatus.failed,
        )
        db.add(change_record)
        db.flush()

        if passed:
            task.status = SEOTaskStatus.completed
        else:
            task.status = SEOTaskStatus.failed
            rollback_change(db, change_record, initiated_by=None, website=website)

        db.flush()
        return change_record

    except ConnectorError as exc:
        task.status = SEOTaskStatus.failed
        db.flush()
        raise ExecutionBlocked(str(exc)) from exc


def rollback_change(
    db: Session, change_record: ChangeRecord, *, initiated_by: uuid.UUID | None, website: Website
) -> RollbackRecord:
    before = change_record.before_state_json
    operation = before["operation"]
    connector_type = change_record.connector_type

    rollback = RollbackRecord(
        change_record_id=change_record.id,
        rollback_method=f"{connector_type.value}.{operation}",
        status=RollbackStatus.pending,
        initiated_by=initiated_by,
    )
    db.add(rollback)
    db.flush()

    if connector_type == ConnectorType.wordpress:
        try:
            credentials = get_wordpress_credentials(db, website)
            post_type, post_id = before["post_type"], before["post_id"]
            if operation == "set_title":
                update_title(credentials, post_type, post_id, before["value"])
            elif operation == "set_meta_description":
                update_meta_description(credentials, post_type, post_id, before["value"])
            else:
                raise ValueError(f"No rollback method for operation: {operation}")

            rollback.status = RollbackStatus.completed
            rollback.result_json = {"restored_value": before["value"]}
        except (WordPressConnectorError, UnsupportedOperation, LookupError, ValueError) as exc:
            rollback.status = RollbackStatus.failed
            rollback.result_json = {"error": str(exc)}
        finally:
            rollback.completed_at = datetime.now(timezone.utc)
            db.flush()

        return rollback

    module = GENERIC_CONNECTOR_MODULES[connector_type]
    try:
        credentials = get_connector_credentials(db, website, connector_type)
        result = module.rollback(
            credentials, before["target_ref"], operation, before["value"], change_record.after_state_json
        )
        rollback.status = RollbackStatus.completed
        rollback.result_json = result
    except (ConnectorError, LookupError, ValueError, KeyError) as exc:
        rollback.status = RollbackStatus.failed
        rollback.result_json = {"error": str(exc)}
    finally:
        rollback.completed_at = datetime.now(timezone.utc)
        db.flush()

    return rollback


def verify_github_deployment(db: Session, website: Website, change_record: ChangeRecord) -> dict:
    """Post-deploy verification for the GitHub connector (CW-014,
    addendum §4.2/§7: "After deployment, crawl the live URL again").

    `github_pr.validate_change()` can only check the open PR's branch --
    it has no way to know when, or whether, a human has merged it and the
    site has actually redeployed, since this platform doesn't control or
    observe the deploy pipeline (same limitation github_pr.py's own
    module docstring documents for its "validation" generally). This is
    a separate step a human calls once they've confirmed the PR merged
    and the site redeployed, re-crawling the now-live URL to confirm the
    change actually shipped -- an API success response from the PR/merge
    step is never, by itself, proof of that.
    """
    if change_record.connector_type != ConnectorType.github:
        raise ExecutionBlocked("Post-deploy verification only applies to the GitHub connector.")

    task = (
        db.query(SEOTask).filter(SEOTask.id == change_record.seo_task_id).one_or_none()
        if change_record.seo_task_id
        else None
    )
    if task is None:
        raise ExecutionBlocked("Could not find the task this change record came from.")

    operation = task.proposed_change_json["operation"]
    target_url = task.proposed_change_json["target_url"]
    expected_value = task.proposed_change_json["value"]

    try:
        fetch_result = safe_fetch(target_url)
    except FetchError as exc:
        verification = {"verified": False, "error": str(exc)}
    else:
        actual_value = github_pr.extract_value(operation, fetch_result.body)
        verification = {
            "verified": actual_value == expected_value,
            "expected": expected_value,
            "actual": actual_value,
            "fetched_url": fetch_result.final_url,
        }

    verification["checked_at"] = datetime.now(timezone.utc).isoformat()
    change_record.after_state_json = {**change_record.after_state_json, "post_deploy_verification": verification}
    db.flush()
    return verification
