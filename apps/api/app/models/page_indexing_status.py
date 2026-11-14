from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PageIndexingStatus(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Google's own view of one page, from the Search Console URL
    Inspection API (RankPilot AI Phase 5 "Google Search Intelligence").

    This is Google's authoritative indexing state -- not a RankPilot
    inference -- so every field mirrors the API response as-is and
    stays None when Google genuinely has no data for it (e.g. a page
    it has never crawled), never a fabricated default.

    Replaced per page on each inspection sync, the same current-state
    contract PerformanceMetric already follows -- this is "Google's
    latest known view", not a time series.
    """

    __tablename__ = "page_indexing_statuses"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    # Google's own verdict string, e.g. "PASS", "FAIL", "NEUTRAL", "PARTIAL".
    verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    coverage_state: Mapped[str | None] = mapped_column(String(256), nullable=True)
    robots_txt_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexing_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    page_fetch_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # None when Google has never crawled this URL.
    last_crawl_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The canonical Google actually selected to index, vs. the one it
    # read off this page (userCanonical) -- these can legitimately
    # differ from RankPilot's own declared-canonical reading
    # (PageSnapshot.canonical_url) when Google ignores the hint.
    google_canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    user_canonical_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    crawled_as: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mobile_usability_verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mobile_usability_issues_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    page: Mapped["Page"] = relationship()
