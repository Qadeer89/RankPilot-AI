"""Public competitor content analysis (SEO Growth Engine spec section
4D): competitors the user names, and what RankPilot's own crawler saw
on their publicly accessible pages. Never a claim about a competitor's
private Search Console data, traffic, backlinks, rankings or search
volume -- only what a normal browser request to a public URL returns.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CompetitorDomain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "competitor_domains"
    __table_args__ = (UniqueConstraint("website_id", "domain", name="uq_competitor_domain_identity"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    website: Mapped["Website"] = relationship()
    pages: Mapped[list["CompetitorPageSnapshot"]] = relationship(
        back_populates="competitor_domain", cascade="all, delete-orphan"
    )


class CompetitorPageSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One publicly fetched competitor page -- the same shape of
    evidence the site's own crawler records for its own pages, so a
    content-gap comparison is apples-to-apples.
    """

    __tablename__ = "competitor_page_snapshots"

    competitor_domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competitor_domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    headings_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_structured_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    competitor_domain: Mapped["CompetitorDomain"] = relationship(back_populates="pages")
