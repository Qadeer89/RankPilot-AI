from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PageSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable record of what one crawl observed on one page (RP-0305).

    Evidence for every SEOFinding traces back to a snapshot; nothing here is
    ever mutated after creation.
    """

    __tablename__ = "page_snapshots"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    crawl_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redirect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    robots_directives: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    headings_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    schema_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    internal_links_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    page: Mapped["Page"] = relationship(back_populates="snapshots")
    crawl_job: Mapped["CrawlJob"] = relationship()
