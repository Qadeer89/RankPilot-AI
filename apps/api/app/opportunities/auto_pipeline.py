"""Turn open opportunities into tasks automatically after a crawl, and
auto-execute whichever of those tasks don't need human approval (per the
same policy.requires_approval rules the manual "create task" flow already
uses -- this adds no new execution permission, it just calls the existing
one without a human clicking through each opportunity).

Runs inside the crawl Celery task (app/tasks/crawl.py), right after
refresh_opportunities_for_website. Best-effort per opportunity: an AI
failure, a budget cutoff, or a missing connector for one opportunity
logs and moves on rather than failing the whole crawl.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.ai.budget import BudgetExceeded
from app.ai.client import AINotConfigured
from app.ai.content_agent import propose_content_fix
from app.ai.runner import PromptTooLarge
from app.execution.service import ExecutionBlocked, create_tasks_from_proposal, execute_task
from app.models.page_snapshot import PageSnapshot
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import Website

logger = logging.getLogger(__name__)

# Bounds one crawl's worth of AI calls so a site with hundreds of open
# opportunities (e.g. many long blog-post titles) can't turn a single
# crawl job into an hours-long sequential loop of AI calls. Opportunities
# left over are picked up on the next crawl, since they still have no
# task (RP13-012/013's global AI budget is the other, spend-based cap).
MAX_AUTO_TASKS_PER_CRAWL = 20


def auto_generate_and_execute_tasks(db: Session, website: Website) -> None:
    opportunities = (
        db.query(SEOOpportunity)
        .filter(SEOOpportunity.website_id == website.id, SEOOpportunity.status == OpportunityStatus.open)
        .order_by(SEOOpportunity.id)
        .all()
    )
    if not opportunities:
        return

    already_has_task = {
        row[0]
        for row in db.query(SEOTask.opportunity_id)
        .filter(SEOTask.website_id == website.id, SEOTask.opportunity_id.isnot(None))
        .all()
    }

    processed = 0
    for opportunity in opportunities:
        if opportunity.id in already_has_task:
            continue
        if processed >= MAX_AUTO_TASKS_PER_CRAWL:
            break
        processed += 1

        snapshot = None
        if opportunity.page_id is not None:
            snapshot = (
                db.query(PageSnapshot)
                .filter(PageSnapshot.page_id == opportunity.page_id)
                .order_by(PageSnapshot.fetched_at.desc())
                .first()
            )

        try:
            proposal = propose_content_fix(db, website, opportunity, snapshot)
            db.commit()
        except BudgetExceeded:
            db.commit()
            logger.info("auto_pipeline: AI budget exhausted, stopping for website %s", website.id)
            break
        except (AINotConfigured, PromptTooLarge) as exc:
            db.commit()
            logger.info("auto_pipeline: skipping opportunity %s (%s)", opportunity.id, exc)
            continue
        except Exception:
            db.commit()
            logger.exception("auto_pipeline: AI proposal failed for opportunity %s", opportunity.id)
            continue

        try:
            tasks = create_tasks_from_proposal(db, website, opportunity, proposal, requested_by=None)
            db.commit()
        except ExecutionBlocked as exc:
            db.commit()
            logger.info("auto_pipeline: no task created for opportunity %s (%s)", opportunity.id, exc)
            continue

        for task in tasks:
            if task.approval_status != ApprovalStatus.not_required:
                continue
            try:
                execute_task(db, website, task)
                db.commit()
            except ExecutionBlocked as exc:
                db.rollback()
                logger.info("auto_pipeline: could not auto-execute task %s (%s)", task.id, exc)
