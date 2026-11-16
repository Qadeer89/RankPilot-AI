"""Repair titles that went live with the brand shown twice.

Before the site's title template was taken into account, RankPilot wrote full
titles (brand included) into CMS title fields that the site template then
suffixed again ("X | Brand | Brand"). The right value is already known: the
title RankPilot applied, minus the repeated brand. No AI call is needed.

Planning is read-only. Creating tasks only *creates* them, always waiting
for a person's approval (even under Autopilot), so nothing goes live until a
person approves and executes each one in the normal Tasks flow.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.schemas import EvidenceRef, OpportunityProposal, ProposedAction
from app.crawler.orchestrator import normalize_frontier_url
from app.execution.service import create_tasks_from_proposal
from app.growth.recrawl import applied_value
from app.models.approval import Approval, ApprovalDecision
from app.models.change_record import ChangeRecord
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.rollback_record import RollbackRecord, RollbackStatus
from app.models.seo_opportunity import SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask, SEOTaskStatus
from app.models.website import Website
from app.seo_rules.site_title import site_title_suffix
from app.seo_rules.title_template import has_duplicate_brand, strip_title_suffix

FINDING_CODE = "TITLE_BRAND_DUPLICATED"


@dataclass(frozen=True)
class RepairCandidate:
    target_url: str
    applied_title: str
    live_title: str
    fixed_title: str
    opportunity_id: object


@dataclass
class RepairPlan:
    candidates: list[RepairCandidate]
    skipped_already_pending: int = 0
    reason_none: str | None = None


def _latest_snapshot_title(db: Session, website: Website, target_url: str) -> str | None:
    page = (
        db.query(Page)
        .filter(Page.website_id == website.id, Page.normalized_url == normalize_frontier_url(target_url))
        .one_or_none()
    )
    if page is None:
        return None
    snapshot = (
        db.query(PageSnapshot).filter(PageSnapshot.page_id == page.id).order_by(PageSnapshot.fetched_at.desc()).first()
    )
    return snapshot.title if snapshot else None


def plan_title_repairs(db: Session, website: Website, *, limit: int | None = None) -> RepairPlan:
    """Pages whose newest applied title is still shown with the brand twice
    in the most recent crawl, and the corrected value for each."""
    suffix = site_title_suffix(db, website)
    if suffix is None:
        return RepairPlan([], reason_none="No site-wide title template was detected from the crawled titles.")

    rows = (
        db.query(SEOTask, ChangeRecord)
        .join(ChangeRecord, ChangeRecord.seo_task_id == SEOTask.id)
        .filter(SEOTask.website_id == website.id, SEOTask.status == SEOTaskStatus.completed,
                SEOTask.task_type == "set_title")
        .order_by(ChangeRecord.executed_at.desc())
        .all()
    )
    plan = RepairPlan([])
    seen: set[str] = set()
    for task, change in rows:
        url = (task.proposed_change_json or {}).get("target_url")
        if not url or normalize_frontier_url(url) in seen:
            continue
        seen.add(normalize_frontier_url(url))
        rolled_back = (
            db.query(RollbackRecord)
            .filter(RollbackRecord.change_record_id == change.id, RollbackRecord.status == RollbackStatus.completed)
            .first()
        )
        if rolled_back is not None or task.opportunity_id is None:
            continue
        live = _latest_snapshot_title(db, website, url)
        applied = applied_value(change, task) or ""
        if not live or not has_duplicate_brand(live):
            continue
        fixed = strip_title_suffix(applied, suffix).strip()
        if not fixed or fixed == applied.strip():
            continue

        pending = (
            db.query(SEOTask)
            .filter(
                SEOTask.opportunity_id == task.opportunity_id,
                SEOTask.task_type == "set_title",
                SEOTask.status.in_([SEOTaskStatus.pending, SEOTaskStatus.executing]),
            )
            .all()
        )
        if any((t.proposed_change_json or {}).get("value") == fixed and (t.proposed_change_json or {}).get("target_url") == url
               for t in pending):
            plan.skipped_already_pending += 1
            continue
        plan.candidates.append(RepairCandidate(url, applied, live, fixed, task.opportunity_id))

    if limit is not None:
        plan.candidates = plan.candidates[:limit]
    return plan


def create_repair_tasks(db: Session, website: Website, candidates: list[RepairCandidate], *, requested_by) -> list[SEOTask]:
    """One task per candidate, each waiting for approval."""
    created: list[SEOTask] = []
    for candidate in candidates:
        opportunity = db.get(SEOOpportunity, candidate.opportunity_id)
        if opportunity is None:
            continue
        proposal = OpportunityProposal(
            opportunity_id=str(opportunity.id),
            summary="Remove the brand that the site's title template already adds, so it is not shown twice.",
            evidence=[EvidenceRef(page_url=candidate.target_url, finding_code=FINDING_CODE)],
            proposed_actions=[ProposedAction(operation="set_title", target_url=candidate.target_url, value=candidate.fixed_title)],
            risk_tier=1,
            confidence=0.95,
            requires_approval=True,
            validation_plan=["Re-crawl the page", "Confirm the brand appears once"],
        )
        for task in create_tasks_from_proposal(db, website, opportunity, proposal, requested_by=requested_by):
            # Under Autopilot opt-ins a task can be created without needing approval;
            # this repair must never run on its own.
            if task.approval_status == ApprovalStatus.not_required:
                task.approval_status = ApprovalStatus.pending
                db.add(Approval(seo_task_id=task.id, requested_by=requested_by, decision=ApprovalDecision.pending))
            created.append(task)
    db.flush()
    return created
