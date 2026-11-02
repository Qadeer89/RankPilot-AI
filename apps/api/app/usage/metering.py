"""Per-site daily usage metering (RP-0806, MASTER_SPEC.md acceptance
criteria: "Usage and cost are attributable per tenant/site").
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun
from app.models.crawl_job import CrawlJob
from app.models.usage_record import UsageRecord
from app.models.website import Website

METRIC_PAGES_CRAWLED = "pages_crawled"
METRIC_AI_PROPOSALS = "ai_proposals"
METRIC_AI_COST_USD = "ai_cost_usd"


def _upsert(db: Session, website: Website, metric: str, quantity: float, unit: str, day: date) -> UsageRecord:
    existing = (
        db.query(UsageRecord)
        .filter(
            UsageRecord.website_id == website.id,
            UsageRecord.metric == metric,
            UsageRecord.period_start == day,
        )
        .one_or_none()
    )
    if existing is None:
        existing = UsageRecord(
            organization_id=website.organization_id,
            website_id=website.id,
            metric=metric,
            quantity=quantity,
            unit=unit,
            estimated_cost=quantity if metric == METRIC_AI_COST_USD else 0.0,
            period_start=day,
        )
        db.add(existing)
    else:
        existing.quantity = quantity
        existing.estimated_cost = quantity if metric == METRIC_AI_COST_USD else 0.0
    return existing


def record_daily_usage(db: Session, website: Website, *, day: date | None = None) -> list[UsageRecord]:
    day = day or date.today()
    start_dt = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    end_dt = start_dt + timedelta(days=1)

    pages_crawled = (
        db.query(func.coalesce(func.sum(CrawlJob.pages_fetched), 0))
        .filter(CrawlJob.website_id == website.id, CrawlJob.created_at >= start_dt, CrawlJob.created_at < end_dt)
        .scalar()
    )
    ai_proposals = (
        db.query(func.count(AgentRun.id))
        .filter(AgentRun.website_id == website.id, AgentRun.started_at >= start_dt, AgentRun.started_at < end_dt)
        .scalar()
    )
    ai_cost = (
        db.query(func.coalesce(func.sum(AgentRun.estimated_cost), 0.0))
        .filter(AgentRun.website_id == website.id, AgentRun.started_at >= start_dt, AgentRun.started_at < end_dt)
        .scalar()
    )

    records = [
        _upsert(db, website, METRIC_PAGES_CRAWLED, float(pages_crawled or 0), "pages", day),
        _upsert(db, website, METRIC_AI_PROPOSALS, float(ai_proposals or 0), "calls", day),
        _upsert(db, website, METRIC_AI_COST_USD, float(ai_cost or 0.0), "usd", day),
    ]
    db.flush()
    return records
