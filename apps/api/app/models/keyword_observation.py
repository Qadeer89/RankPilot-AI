from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Date, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class KeywordObservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One day's Search Console search-analytics row for one query
    (RP-0503). Search Console data is delayed/aggregated, never real-time
    ranking telemetry (MASTER_SPEC.md "Global implementation rules").
    """

    __tablename__ = "keyword_observations"
    __table_args__ = (
        UniqueConstraint("website_id", "query", "date", "page_id", name="uq_keyword_obs_identity"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_position: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="google_search_console", nullable=False)

    website: Mapped["Website"] = relationship()
