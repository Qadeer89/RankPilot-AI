from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SiteHealthScore(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One severity-weighted health score snapshot per crawl_job
    (opportunities/health_score.py). `technical_score`/`on_page_score`/
    `content_score`/`performance_score` are each nullable: a category this
    crawl has no data for (e.g. content_score before thin-content
    detection exists, performance_score before Core Web Vitals collection
    exists) is stored as NULL, never as a fabricated 0 or 100 -- `None`
    means "not measured yet", not "perfect" or "worst possible".
    `overall_score` is the average of whichever categories aren't NULL,
    and is itself NULL if none are available.
    """

    __tablename__ = "site_health_scores"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    on_page_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
