"""Platform health for the Super Admin. Reads only; never returns a secret, connection string or token.
Each check reports ok / warning / error / unknown, and `unknown` is used when a check could not run."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.admin import runtime_settings
from app.config import get_settings
from app.core.deployment import deployment_problems
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.billing import BillingEvent, BillingEventStatus, Payment, PaymentStatus
from app.models.change_record import ChangeRecord, ValidationStatus
from app.models.crawl_job import CrawlJob, CrawlStatus
from app.models.ga4_daily_metric import Ga4DailyMetric
from app.models.oauth_connection import OAuthConnection, OAuthConnectionStatus
from app.models.website_connection import WebsiteConnection, WebsiteConnectionStatus


def _check(name: str, state: str, detail: str, **extra) -> dict:
    return {"name": name, "state": state, "detail": detail, **extra}


def _redis_checks() -> list[dict]:
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        backlog = int(client.llen("rankpilot"))
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return [_check("queue", "error", f"Redis is not reachable ({type(exc).__name__}).")]
    state = "ok" if backlog < 100 else "warning"
    return [_check("queue", state, f"{backlog} task(s) waiting in the default queue.", backlog=backlog)]


def _worker_check() -> dict:
    try:
        from app.celery_app import celery_app

        replies = celery_app.control.inspect(timeout=1.0).ping() or {}
    except Exception as exc:  # noqa: BLE001
        return _check("workers", "unknown", f"Could not ask the workers ({type(exc).__name__}).")
    if not replies:
        return _check("workers", "error", "No Celery worker answered within 1 second.", workers=0)
    return _check("workers", "ok", f"{len(replies)} worker(s) answered.", workers=len(replies))


def collect(db: Session, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    checks: list[dict] = [_check("api", "ok", "The API answered this request.")]
    try:
        db.execute(text("SELECT 1"))
        checks.append(_check("database", "ok", "Query succeeded."))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("database", "error", f"Query failed ({type(exc).__name__})."))
    checks.extend(_redis_checks())
    checks.append(_worker_check())

    failed_crawls = db.query(CrawlJob).filter(CrawlJob.status == CrawlStatus.failed, CrawlJob.created_at >= day_ago).count()
    failed_ai = db.query(AgentRun).filter(AgentRun.status == AgentRunStatus.failed, AgentRun.started_at >= day_ago).count()
    checks.append(_check("failed_jobs", "warning" if failed_crawls + failed_ai else "ok",
                         f"{failed_crawls} crawl(s) and {failed_ai} AI run(s) failed in the last 24 hours.",
                         crawls=failed_crawls, ai_runs=failed_ai))

    threshold = int(runtime_settings.get_value(db, "webhook_failure_warning_count"))
    failed_events = db.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.failed).count()
    rejected = db.query(BillingEvent).filter(BillingEvent.status == BillingEventStatus.rejected, BillingEvent.created_at >= day_ago).count()
    last_ok = db.query(func.max(BillingEvent.processed_at)).scalar()
    webhook_state = "error" if failed_events >= threshold else "warning" if (failed_events or rejected) else "ok"
    checks.append(_check("billing_webhooks", webhook_state,
                         f"{failed_events} failed event(s) awaiting retry, {rejected} rejected (bad signature) in 24h.",
                         failed=failed_events, rejected_24h=rejected, last_processed_at=last_ok.isoformat() if last_ok else None))
    failed_payments = db.query(Payment).filter(Payment.status == PaymentStatus.failed, Payment.created_at >= week_ago).count()
    checks.append(_check("payment_sync", "warning" if failed_payments else "ok", f"{failed_payments} failed payment(s) in the last 7 days.", failed_7d=failed_payments))

    last_ga4 = db.query(func.max(Ga4DailyMetric.date)).scalar()
    checks.append(_check("ga4_sync", "unknown" if last_ga4 is None else ("warning" if (now.date() - last_ga4).days > 3 else "ok"),
                         "No GA4 data stored yet." if last_ga4 is None else f"Newest stored GA4 day: {last_ga4.isoformat()}.",
                         newest_day=last_ga4.isoformat() if last_ga4 else None))
    oauth_bad = db.query(OAuthConnection).filter(OAuthConnection.status == OAuthConnectionStatus.error).count()
    checks.append(_check("google_connections", "warning" if oauth_bad else "ok", f"{oauth_bad} Google connection(s) need re-authorisation.", needs_reauth=oauth_bad))
    cms_bad = db.query(WebsiteConnection).filter(WebsiteConnection.status == WebsiteConnectionStatus.error).count()
    cms_failed = db.query(ChangeRecord).filter(ChangeRecord.validation_status == ValidationStatus.failed, ChangeRecord.executed_at >= week_ago).count()
    checks.append(_check("cms", "warning" if (cms_bad or cms_failed) else "ok",
                         f"{cms_bad} CMS connection(s) in error; {cms_failed} change(s) failed validation in 7 days.", connections_in_error=cms_bad, failed_validations_7d=cms_failed))

    problems = deployment_problems()
    if problems:
        worst = "error" if any(p["level"] == "error" for p in problems) else "warning"
        checks.append(_check("configuration", worst, "; ".join(p["message"] for p in problems), problems=problems))
    else:
        checks.append(_check("configuration", "ok", "Environment, URLs and payment mode are consistent."))

    order = {"error": 3, "warning": 2, "unknown": 1, "ok": 0}
    overall = max((c["state"] for c in checks), key=lambda s: order[s])
    return {"overall": overall, "checked_at": now.isoformat(), "checks": checks}
