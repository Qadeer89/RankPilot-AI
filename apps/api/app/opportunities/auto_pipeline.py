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
from app.connectors.errors import ConnectorError
from app.connectors.wordpress import (
    UnsupportedOperation,
    WordPressConnectorError,
    find_media_by_url,
    find_post_by_url,
)
from app.execution.connections import get_connected_content_connector, get_connector_credentials, get_wordpress_credentials
from app.execution.service import (
    GENERIC_CONNECTOR_MODULES,
    ExecutionBlocked,
    create_tasks_from_proposal,
    execute_task,
)
from app.models.page import Page
from app.models.page_snapshot import PageSnapshot
from app.models.seo_opportunity import OpportunityStatus, SEOOpportunity
from app.models.seo_task import ApprovalStatus, SEOTask
from app.models.website import AutomationMode, Website, WebsiteStatus
from app.models.website_connection import ConnectorType
from app.notifications.dispatch import notify_organization

logger = logging.getLogger(__name__)


def _target_url_for(db: Session, opportunity: SEOOpportunity) -> str | None:
    if opportunity.category == "images":
        images = opportunity.evidence_json.get("finding_evidence", {}).get("images", [])
        if not images:
            return None
        first = images[0]
        src = first.get("src") if isinstance(first, dict) else first
        return src or None
    if opportunity.page_id is None:
        return None
    page = db.get(Page, opportunity.page_id)
    return page.canonical_url if page is not None else None


def _connector_can_write(
    db: Session, website: Website, target_url: str | None, *, is_image: bool = False
) -> tuple[bool, str | None]:
    """Best-effort pre-check, before any AI call: can the connected
    connector actually find/write this specific URL right now?

    Only ever returns a hard "no" when we've just confirmed the write
    would fail (e.g. Sanity's `find_target` can't resolve a URL whose
    document type the connected dataset doesn't expose SEO fields for --
    app/connectors/sanity.py). Returns "yes" (not a block) for every case
    that isn't a confirmed failure right now -- no connector connected yet,
    a site-wide opportunity with no single target page, or a connector
    this check doesn't special-case -- since those can still resolve once
    a connector is connected or at execution time; this pre-filter exists
    only to avoid spending an AI call on a write we already know will fail.
    """
    if target_url is None or website.status != WebsiteStatus.active:
        return True, None
    connector_type = get_connected_content_connector(db, website)
    if connector_type is None:
        return True, None

    if is_image and connector_type != ConnectorType.wordpress:
        return False, f"Image alt-text writes are not yet supported by the {connector_type.value} connector."

    if connector_type == ConnectorType.wordpress:
        try:
            credentials = get_wordpress_credentials(db, website)
            if is_image:
                find_media_by_url(credentials, target_url)
            else:
                find_post_by_url(credentials, target_url)
            return True, None
        except LookupError as exc:
            return False, str(exc)
        except (WordPressConnectorError, UnsupportedOperation) as exc:
            return False, str(exc)

    module = GENERIC_CONNECTOR_MODULES.get(connector_type)
    if module is None:
        return True, None
    try:
        credentials = get_connector_credentials(db, website, connector_type)
    except LookupError as exc:
        return False, str(exc)
    try:
        module.find_target(credentials, target_url)
        return True, None
    except ConnectorError as exc:
        return False, str(exc)

# Bounds one crawl's worth of AI calls so a site with hundreds of open
# opportunities (e.g. many long blog-post titles) can't turn a single
# crawl job into an hours-long sequential loop of AI calls. Opportunities
# left over are picked up on the next crawl, since they still have no
# task (RP13-012/013's global AI budget is the other, spend-based cap).
MAX_AUTO_TASKS_PER_CRAWL = 20


def auto_generate_and_execute_tasks(db: Session, website: Website) -> None:
    # Audit mode (RankPilot AI Phase 8 "Automation Modes"): detect and
    # report only -- the background pipeline never drafts an AI proposal
    # here, let alone executes a write. (Copilot mode still drafts and
    # creates tasks below; policy.requires_approval is what stops those
    # from auto-executing.)
    if website.automation_mode == AutomationMode.audit:
        return

    opportunities = (
        db.query(SEOOpportunity)
        .filter(
            SEOOpportunity.website_id == website.id,
            SEOOpportunity.status == OpportunityStatus.open,
            # A growth recommendation a person sent for an AI draft is
            # theirs to drive; the crawl pipeline never picks it up.
            SEOOpportunity.category != "growth",
        )
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
    auto_fixed_count = 0
    auto_fix_failed_count = 0
    pending_approval_count = 0
    for opportunity in opportunities:
        if opportunity.id in already_has_task:
            continue
        if processed >= MAX_AUTO_TASKS_PER_CRAWL:
            break

        target_url = _target_url_for(db, opportunity)
        writable, skip_reason = _connector_can_write(
            db, website, target_url, is_image=(opportunity.category == "images")
        )
        if not writable:
            logger.info(
                "auto_pipeline: skipping opportunity %s, target not writable by the connected connector (%s)",
                opportunity.id,
                skip_reason,
            )
            continue

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
                pending_approval_count += 1
                continue
            try:
                execute_task(db, website, task)
                auto_fixed_count += 1
            except ExecutionBlocked as exc:
                # execute_task already marks the task "failed" and flushes
                # that (e.g. an operation the connector doesn't support for
                # this specific document) before raising, for every case
                # past its early guard clauses (paused, writes disabled,
                # no connector, etc., which mutate nothing). Committing
                # here persists whichever of those actually happened;
                # rolling back would silently erase that "failed" write
                # and leave the task looking "pending" forever.
                logger.info("auto_pipeline: could not auto-execute task %s (%s)", task.id, exc)
                auto_fix_failed_count += 1
            db.commit()

    # A single end-of-run digest rather than one notification per task --
    # a busy site auto-fixing dozens of titles in one crawl shouldn't send
    # dozens of Slack messages (RankPilot AI Phase 7 "Notifications").
    notify_on_summary = website.automation_policy.get("notify_on_auto_pipeline_summary", True)
    if notify_on_summary and (auto_fixed_count or auto_fix_failed_count or pending_approval_count):
        lines = [f"Automation summary for {website.display_name} ({website.canonical_url}):"]
        if auto_fixed_count:
            lines.append(f"- {auto_fixed_count} fix{'es' if auto_fixed_count != 1 else ''} auto-executed")
        if auto_fix_failed_count:
            lines.append(f"- {auto_fix_failed_count} auto-fix attempt{'s' if auto_fix_failed_count != 1 else ''} failed")
        if pending_approval_count:
            lines.append(f"- {pending_approval_count} task{'s' if pending_approval_count != 1 else ''} awaiting approval")
        try:
            notify_organization(
                db,
                website.organization,
                website_id=website.id,
                event_type="auto_pipeline_summary",
                subject=f"Automation summary for {website.display_name}",
                message="\n".join(lines),
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("auto_pipeline: summary notification failed for website %s", website.id)
