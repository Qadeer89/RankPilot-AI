"""Background jobs for crawling and auditing a website
(SYSTEM_ARCHITECTURE.md #5: "site_crawl", "technical_audit").
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import OperationalError

from app.celery_app import celery_app
from app.crawler.orchestrator import run_crawl
from app.db.session import SessionLocal
from app.models.crawl_job import CrawlJob, CrawlStatus
from app.models.website import Website
from app.monitoring.regression_detection import detect_regressions
from app.notifications.dispatch import notify_organization
from app.opportunities.auto_pipeline import auto_generate_and_execute_tasks
from app.opportunities.health_score import compute_health_score
from app.opportunities.scoring import refresh_opportunities_for_website
from app.seo_rules.engine import run_rules_for_crawl

logger = logging.getLogger(__name__)

# Only a real connection blip is worth retrying automatically: every other
# failure mode this task can hit is either already handled internally
# (run_crawl's own except-Exception marks the CrawlJob "failed" and returns
# normally instead of raising -- see app/crawler/orchestrator.py) or is a
# genuine bug that retrying unchanged inputs won't fix.
TRANSIENT_EXCEPTIONS = (OperationalError,)
BASE_BACKOFF_SECONDS = 30


def _mark_crawl_job_failed(crawl_job_id: str, error_summary: str) -> None:
    """Uses a fresh session rather than the task's own `db`, since the
    failure that lands here (retries exhausted) may be exactly a broken
    connection on that session.
    """
    db = SessionLocal()
    try:
        crawl_job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
        if crawl_job is not None:
            crawl_job.status = CrawlStatus.failed
            crawl_job.error_summary = error_summary[:2000]
            crawl_job.completed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.exception("run_site_crawl: could not mark crawl_job %s failed after exhausting retries", crawl_job_id)
    finally:
        db.close()


@celery_app.task(name="app.tasks.crawl.run_site_crawl", bind=True, max_retries=4)
def run_site_crawl(self, website_id: str, crawl_job_id: str) -> str:
    """Run one crawl against an already-created (pending) CrawlJob row, then
    run the deterministic rule engine against what it found.

    The API layer creates the CrawlJob synchronously (so it can hand the
    caller an id immediately) and only enqueues this task to do the work.
    """
    db = SessionLocal()
    try:
        website = db.get(Website, uuid.UUID(website_id))
        crawl_job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
        if website is None or crawl_job is None:
            logger.error("run_site_crawl: website or crawl_job not found (%s, %s)", website_id, crawl_job_id)
            return "not_found"

        # Guards against the broker redelivering this task's message after
        # it already ran to completion (at-least-once delivery semantics,
        # not something specific to this task's retry logic above) --
        # without this, a redelivered message would re-crawl and double up
        # the auto-pipeline's AI/execution work for an already-finished job.
        if crawl_job.status in (CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled):
            logger.info(
                "run_site_crawl: crawl_job %s is already %s, skipping duplicate delivery",
                crawl_job_id,
                crawl_job.status.value,
            )
            return crawl_job.status.value

        run_crawl(db, website, crawl_job)
        db.commit()

        run_rules_for_crawl(db, website, crawl_job)
        db.commit()

        compute_health_score(db, website, crawl_job)
        db.commit()

        # Permanent history: an immutable snapshot of this completed analysis. Best-effort and idempotent, so a
        # failure here can never fail the crawl and a redelivered task cannot create a second snapshot.
        try:
            from app.history.snapshots import ensure_history, record_crawl_snapshot

            ensure_history(db, website)
            record_crawl_snapshot(db, website, crawl_job)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("run_site_crawl: could not save the history snapshot for website %s", website_id)

        # Best-effort: a regression (new critical finding or a health-score
        # category dropping sharply) is worth surfacing right away rather
        # than only on the next manual dashboard visit
        # (app/monitoring/regression_detection.py).
        try:
            regressions = detect_regressions(db, website, crawl_job)
            notify_on_regression = website.automation_policy.get("notify_on_regression", True)
            if regressions.has_regressions and notify_on_regression:
                lines = [f"SEO regression detected on {website.display_name} ({website.canonical_url}):"]
                for f in regressions.new_critical_findings:
                    lines.append(f"- New critical finding: {f.rule_code}")
                for r in regressions.score_regressions:
                    lines.append(
                        f"- {r.category.replace('_', ' ')} dropped {r.drop:.0f} points "
                        f"({r.previous_score:.0f} -> {r.current_score:.0f})"
                    )
                notify_organization(
                    db,
                    website.organization,
                    website_id=website.id,
                    event_type="seo_regression",
                    subject=f"SEO regression detected on {website.display_name}",
                    message="\n".join(lines),
                )
                db.commit()
        except Exception:
            db.rollback()
            logger.exception("run_site_crawl: regression notification failed for website %s", website_id)

        # Folded into the same task for MVP simplicity rather than a
        # separate "opportunity_refresh" job (SYSTEM_ARCHITECTURE.md #5):
        # it's cheap, deterministic, and always needs to follow a rule run.
        refresh_opportunities_for_website(db, website)
        db.commit()

        # Best-effort: turns open opportunities into AI-proposed tasks and
        # auto-executes whichever don't need human approval, so a verified
        # site keeps improving without someone clicking through every
        # opportunity by hand (app/opportunities/auto_pipeline.py).
        auto_generate_and_execute_tasks(db, website)
        db.commit()
        return crawl_job.status.value
    except TRANSIENT_EXCEPTIONS as exc:
        db.rollback()
        retries_so_far = self.request.retries
        if retries_so_far >= self.max_retries:
            logger.error(
                "run_site_crawl: giving up for website %s after %s retries (%s)", website_id, retries_so_far, exc
            )
            _mark_crawl_job_failed(crawl_job_id, f"Gave up after {retries_so_far} retries: {exc}")
            raise
        backoff = BASE_BACKOFF_SECONDS * (2**retries_so_far)
        logger.warning(
            "run_site_crawl: transient failure for website %s (retry %s/%s in %ss): %s",
            website_id,
            retries_so_far + 1,
            self.max_retries,
            backoff,
            exc,
        )
        raise self.retry(exc=exc, countdown=backoff)
    except Exception:
        db.rollback()
        logger.exception("run_site_crawl: permanent failure for website %s", website_id)
        raise
    finally:
        db.close()


class _OtherCrawlRunning(Exception):
    pass


POST_CHANGE_MAX_RETRIES = 6
POST_CHANGE_RETRY_SECONDS = 45


@celery_app.task(name="app.tasks.crawl.run_post_change_crawl", bind=True, max_retries=POST_CHANGE_MAX_RETRIES)
def run_post_change_crawl(self, website_id: str, crawl_job_id: str, change_record_id: str) -> str:
    """One-URL verification crawl after a change was applied
    (app/growth/recrawl.py). Waits (retries) while a full crawl of the same
    site is running, so the two never fight over the shared crawl frontier."""
    from app.growth.recrawl import _set_recrawl, record_recrawl_result
    from app.models.change_record import ChangeRecord
    from app.models.crawl_job import CrawlTrigger

    db = SessionLocal()
    try:
        website = db.get(Website, uuid.UUID(website_id))
        job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
        change = db.get(ChangeRecord, uuid.UUID(change_record_id))
        if website is None or job is None or change is None:
            return "not_found"
        if job.status in (CrawlStatus.completed, CrawlStatus.failed, CrawlStatus.cancelled):
            return job.status.value

        busy = (
            db.query(CrawlJob)
            .filter(
                CrawlJob.website_id == website.id,
                CrawlJob.id != job.id,
                CrawlJob.status == CrawlStatus.running,
            )
            .first()
        )
        if busy is not None:
            raise _OtherCrawlRunning()

        _set_recrawl(change, status="running")
        db.commit()

        target_url = (change.after_state_json.get("recrawl") or {}).get("url")
        run_crawl(db, website, job, trigger=CrawlTrigger.post_change, only_urls=[target_url] if target_url else [])
        db.commit()

        result = record_recrawl_result(db, job, change)
        db.commit()
        from app.growth.recrawl import retry_if_not_visible

        again = retry_if_not_visible(db, website, change, result)
        db.commit()
        if again is not None:
            next_job, countdown = again
            run_post_change_crawl.apply_async(args=[str(website.id), str(next_job.id), str(change.id)], countdown=countdown)
        return job.status.value
    except _OtherCrawlRunning as exc:
        db.rollback()
        try:
            raise self.retry(exc=exc, countdown=POST_CHANGE_RETRY_SECONDS)
        except self.MaxRetriesExceededError:
            job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
            change = db.get(ChangeRecord, uuid.UUID(change_record_id))
            if job is not None:
                job.status = CrawlStatus.failed
                job.error_summary = "Another crawl kept running; the verification crawl was not started."
                job.completed_at = datetime.now(timezone.utc)
            if change is not None:
                _set_recrawl(change, status="failed", error="Another crawl kept running; use Re-crawl page to try again.")
            db.commit()
            return "deferred_too_long"
    except Exception:
        db.rollback()
        logger.exception("run_post_change_crawl failed for change %s", change_record_id)
        job = db.get(CrawlJob, uuid.UUID(crawl_job_id))
        change = db.get(ChangeRecord, uuid.UUID(change_record_id))
        if job is not None and job.status not in (CrawlStatus.completed, CrawlStatus.cancelled):
            job.status = CrawlStatus.failed
            job.error_summary = "The verification crawl crashed."
            job.completed_at = datetime.now(timezone.utc)
        if change is not None:
            _set_recrawl(change, status="failed", error="The verification crawl crashed. See server logs.")
        db.commit()
        return "failed"
    finally:
        db.close()
