"""Targeted post-change verification crawl.

After RankPilot applies a change to a page, a one-URL crawl job (trigger
`post_change`) re-fetches that page through the normal crawler and
compares what a crawler actually sees with the value that was applied.
The result is stored on the ChangeRecord (`after_state_json["recrawl"]`)
and read back by the recommendation lifecycle (app/growth/lifecycle.py).

This is deliberately narrow: it runs no SEO rules, computes no health
score, and does not count as the site's "last crawl". A CMS read-back
passing is *not* treated as a finished validation until this crawl
confirms the change is visible on the public page.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.crawler.orchestrator import create_crawl_job
from app.models.change_record import ChangeRecord
from app.models.crawl_job import CrawlJob, CrawlStatus, CrawlTrigger
from app.models.page_snapshot import PageSnapshot
from app.models.seo_task import SEOTask
from app.models.website import Website

logger = logging.getLogger(__name__)

# Task operations whose result is visible in a crawled page snapshot.
RECRAWL_FIELDS = {"set_title": "title", "set_meta_description": "meta_description"}
IN_FLIGHT = ("queued", "running")


def applied_value(change: ChangeRecord, task: SEOTask) -> str | None:
    """The value RankPilot wrote. WordPress records it as
    `after_state_json["value"]`; the generic connectors do not, so fall back
    to the value the approved task asked for."""
    value = (change.after_state_json or {}).get("value")
    return value if value is not None else task.proposed_change_json.get("value")


def _set_recrawl(change: ChangeRecord, **fields) -> dict:
    current = dict((change.after_state_json or {}).get("recrawl") or {})
    current.update(fields)
    change.after_state_json = {**(change.after_state_json or {}), "recrawl": current}
    return current


def schedule_post_change_crawl(db: Session, website: Website, change: ChangeRecord) -> CrawlJob | None:
    """Create the pending one-URL crawl job and record it on the change.
    Returns None (and records why) when there is nothing to crawl. The
    caller commits, then enqueues `run_post_change_crawl`."""
    task = change.seo_task
    target_url = (task.proposed_change_json or {}).get("target_url") if task is not None else None
    if not target_url:
        _set_recrawl(change, status="not_started", error="This change has no page URL to crawl.")
        return None
    job = create_crawl_job(db, website, trigger=CrawlTrigger.post_change)
    _set_recrawl(
        change,
        status="queued",
        crawl_job_id=str(job.id),
        url=target_url,
        queued_at=datetime.now(timezone.utc).isoformat(),
        error=None,
        expected=None,
        found=None,
        completed_at=None,
    )
    db.flush()
    return job


def enqueue_post_change_crawl(db: Session, website: Website, change: ChangeRecord) -> CrawlJob | None:
    """Schedule + commit + queue. Never raises: a verification crawl that
    cannot be queued must not undo or fail the change that was applied; it
    is recorded on the change and shows up as `validation_pending`."""
    try:
        job = schedule_post_change_crawl(db, website, change)
        db.commit()
        if job is None:
            return None
        from app.tasks.crawl import run_post_change_crawl

        run_post_change_crawl.delay(str(website.id), str(job.id), str(change.id))
        return job
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not queue the post-change crawl for change %s", change.id)
        db.rollback()
        try:
            _set_recrawl(change, status="not_started", error=f"Could not queue the verification crawl: {str(exc)[:200]}")
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return None


def record_recrawl_result(db: Session, job: CrawlJob, change: ChangeRecord) -> dict:
    """Compare the page snapshot this crawl took with the applied value."""
    task = change.seo_task
    snapshot = (
        db.query(PageSnapshot)
        .filter(PageSnapshot.crawl_job_id == job.id)
        .order_by(PageSnapshot.fetched_at.desc())
        .first()
    )
    now = datetime.now(timezone.utc).isoformat()
    field = RECRAWL_FIELDS.get(task.task_type)

    if job.status != CrawlStatus.completed or snapshot is None:
        return _set_recrawl(
            change, status="failed", completed_at=now,
            error=(job.error_summary or "The page could not be crawled.")[:300],
        )
    if snapshot.status_code is not None and snapshot.status_code >= 400:
        return _set_recrawl(change, status="failed", completed_at=now, http_status=snapshot.status_code,
                            error=f"The page returned HTTP {snapshot.status_code}.")
    if field is None:
        return _set_recrawl(change, status="not_applicable", completed_at=now, http_status=snapshot.status_code,
                            error=None)

    expected = applied_value(change, task)
    found = getattr(snapshot, field)
    matched = (found or "").strip() == (expected or "").strip()
    return _set_recrawl(
        change,
        status="validated" if matched else "mismatch",
        completed_at=now,
        http_status=snapshot.status_code,
        expected=expected,
        found=found,
        error=None,
    )
