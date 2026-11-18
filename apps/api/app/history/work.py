"""Work RankPilot has actually done on a project, counted from execution records.

Change records written by the execution engine carry no page of their own, so the page is resolved through the task's
opportunity. Counting only `ChangeRecord.page_id` made a project with 100+ applied changes read as zero. Everything
here is derived from stored records; a change that failed validation is never counted as optimisation."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.change_record import ChangeRecord, ValidationStatus
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import SEOTask
from app.models.website import Website


def change_rows(db: Session, website: Website, page_id=None):
    """(ChangeRecord, resolved page id, opportunity id) for the project, optionally for one page."""
    resolved = func.coalesce(ChangeRecord.page_id, SEOOpportunity.page_id)
    q = (db.query(ChangeRecord, resolved, SEOTask.opportunity_id)
         .outerjoin(SEOTask, SEOTask.id == ChangeRecord.seo_task_id)
         .outerjoin(SEOOpportunity, SEOOpportunity.id == SEOTask.opportunity_id)
         .filter(ChangeRecord.website_id == website.id))
    if page_id is not None:
        q = q.filter(resolved == page_id)
    return q.order_by(ChangeRecord.executed_at).all()


def summary(db: Session, website: Website) -> dict:
    rows = change_rows(db, website)
    applied = [r for r in rows if r[0].validation_status != ValidationStatus.failed]
    validated = [r for r in rows if r[0].validation_status == ValidationStatus.passed]
    failed = [r for r in rows if r[0].validation_status == ValidationStatus.failed]
    return {
        "changes_applied": len(applied), "changes_validated": len(validated), "changes_failed": len(failed),
        "pages_optimized": len({r[1] for r in applied if r[1] is not None}),
        "pages_unattributed": sum(1 for r in applied if r[1] is None),
        "opportunities_implemented": {r[2] for r in applied if r[2] is not None},
        "opportunities_validated": {r[2] for r in validated if r[2] is not None},
        "opportunities_failed": {r[2] for r in failed if r[2] is not None},
    }
