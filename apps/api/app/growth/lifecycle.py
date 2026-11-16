"""Where a growth recommendation is in its life, derived from real
records rather than stored as a second copy of the truth: the
recommendation's own decision, and -- once it has been sent for
execution -- its task, change record and rollback record in the
existing execution pipeline.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.execution.connections import get_connected_content_connector
from app.execution.service import get_connector_capabilities
from app.growth.execution import EXECUTABLE_TYPES
from app.models.change_record import ChangeRecord, ValidationStatus
from app.models.growth_recommendation import GrowthRecommendation, RecommendationStatus
from app.models.rollback_record import RollbackRecord, RollbackStatus
from app.models.seo_task import SEOTask, SEOTaskStatus
from app.models.website import Website

# What the AI draft for an existing page can change today.
DRAFT_OPERATIONS = ("set_title", "set_meta_description")


def execution_support(db: Session, website: Website, rec: GrowthRecommendation) -> tuple[bool, str | None]:
    """Can this recommendation be applied through a connected CMS, and
    if not, the plain reason to show the user.
    """
    if rec.recommendation_type not in EXECUTABLE_TYPES:
        return False, "RankPilot has no automated change for this kind of recommendation. Apply it by hand, then mark it done."
    if rec.page_id is None:
        return False, "The page for this query has not been crawled yet, so there is nothing to change automatically."
    connector = get_connected_content_connector(db, website)
    if connector is None:
        return False, "No CMS is connected. Connect one in Integrations to apply this from RankPilot."
    capabilities = get_connector_capabilities(connector)
    if not any(op in capabilities for op in DRAFT_OPERATIONS):
        return False, f"The connected {connector.value} integration cannot change page titles or meta descriptions."
    return True, None


def describe(db: Session, website: Website, rec: GrowthRecommendation) -> dict:
    supported, reason = execution_support(db, website, rec)
    info: dict = {
        "lifecycle_status": "pending",
        "supported": supported,
        "unsupported_reason": reason,
        "applied_manually": False,
        "tasks": [],
    }

    if rec.status == RecommendationStatus.rejected:
        info["lifecycle_status"] = "rejected"
        return info
    if rec.status == RecommendationStatus.open:
        return info
    if rec.opportunity_id is None:
        if rec.status == RecommendationStatus.done:
            info["lifecycle_status"] = "applied"
            info["applied_manually"] = True
        else:
            info["lifecycle_status"] = "approved"
        return info

    tasks = (
        db.query(SEOTask).filter(SEOTask.opportunity_id == rec.opportunity_id).order_by(SEOTask.created_at).all()
    )
    if not tasks:
        info["lifecycle_status"] = "in_progress"
        return info

    states: list[str] = []
    for task in tasks:
        change = (
            db.query(ChangeRecord)
            .filter(ChangeRecord.seo_task_id == task.id)
            .order_by(ChangeRecord.executed_at.desc())
            .first()
        )
        rolled_back = change is not None and (
            db.query(RollbackRecord)
            .filter(RollbackRecord.change_record_id == change.id, RollbackRecord.status == RollbackStatus.completed)
            .first()
            is not None
        )
        if rolled_back:
            state = "rolled_back"
        elif change is not None:
            state = {
                ValidationStatus.passed: "validated",
                ValidationStatus.failed: "failed",
                ValidationStatus.pending: "validation_pending",
            }[change.validation_status]
        elif task.status == SEOTaskStatus.failed:
            state = "failed"
        elif task.status == SEOTaskStatus.rejected:
            state = "rejected"
        else:
            state = "in_progress"
        states.append(state)
        info["tasks"].append(
            {
                "task_id": str(task.id),
                "operation": task.task_type,
                "target_url": task.proposed_change_json.get("target_url"),
                "proposed_value": task.proposed_change_json.get("value"),
                "summary": task.proposed_change_json.get("summary"),
                "task_status": task.status.value,
                "approval_status": task.approval_status.value,
                "state": state,
                "change_record_id": str(change.id) if change else None,
                "before_value": change.before_state_json.get("value") if change else None,
                "applied_value": change.after_state_json.get("value") if change else None,
                "connector": change.connector_type.value if change else None,
            }
        )

    # The recommendation is only as far along as its least-advanced change.
    for candidate in ("failed", "in_progress", "validation_pending", "rolled_back", "rejected", "validated"):
        if candidate in states:
            info["lifecycle_status"] = candidate
            break
    info["live_check"] = rec.evidence_json.get("live_check")
    return info
