from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CrawlTrigger(str, enum.Enum):
    manual = "manual"
    scheduled = "scheduled"
    # A deploy/content-change event from a connected CMS or CI pipeline,
    # via the generic secret-authenticated webhook endpoint (RankPilot AI
    # Phase 7 "Change Detection" -- deployment/webhook-triggered re-crawl).
    webhook = "webhook"
    # A one-URL verification crawl queued after RankPilot applies a change
    # to that page (app/growth/recrawl.py). Not a full-site crawl: it runs
    # no rules, computes no health score, and does not count as the
    # website's "last crawl" for scheduling.
    post_change = "post_change"


class CrawlStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class CrawlJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bounded crawl run against a website (RP-0301..RP-0306)."""

    __tablename__ = "crawl_jobs"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trigger: Mapped[CrawlTrigger] = mapped_column(Enum(CrawlTrigger, name="crawl_trigger"), nullable=False)
    status: Mapped[CrawlStatus] = mapped_column(
        Enum(CrawlStatus, name="crawl_status"), default=CrawlStatus.pending, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_requested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    website: Mapped["Website"] = relationship()
