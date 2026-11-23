"""Independent authority and backlink records.

Nothing here imitates a third-party metric. `AuthorityAssessment` rows are RankPilot's own, reproducible from the stored
`inputs_json`; `Backlink` rows are only links RankPilot has actually verified (or that someone supplied and are marked as
not yet verified), never an estimate of a global backlink index."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AuthorityAssessment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One computation of the RankPilot Domain Quality Assessment and its signals for one crawl. Append-only: a later
    computation adds a row, it never rewrites an earlier one, so the original baseline stays as it was."""

    __tablename__ = "authority_assessments"
    __table_args__ = (UniqueConstraint("website_id", "crawl_job_id", name="uq_authority_website_crawl"), Index("ix_authority_site_time", "website_id", "computed_at"))

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)  # share of the formula's weight that had data
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    signals_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    inputs_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class Backlink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A link from a public page to this website that RankPilot knows about, and what its last check found."""

    __tablename__ = "backlinks"
    __table_args__ = (UniqueConstraint("website_id", "source_url", name="uq_backlink_website_source"), Index("ix_backlink_site_domain", "website_id", "source_domain"))

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False)
    target_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)  # the page on this site it points to (known after a check)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rel_values: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_nofollow: Mapped[bool | None] = mapped_column(nullable=True)
    link_location: Mapped[str | None] = mapped_column(String(24), nullable=True)  # content | navigation | header | footer | sidebar
    discovery_source: Mapped[str] = mapped_column(String(32), nullable=False)  # user_provided | gsc_export | public_page_scan
    status: Mapped[str] = mapped_column(String(24), default="unchecked", nullable=False)  # unchecked | live | link_removed | unreachable | blocked_by_robots | error
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BacklinkCheck(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every verification of a backlink, kept so appearing, disappearing and changed links can be shown over time."""

    __tablename__ = "backlink_checks"
    __table_args__ = (Index("ix_backlink_check_link_time", "backlink_id", "checked_at"),)

    backlink_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backlinks.id", ondelete="CASCADE"), nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    anchor_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rel_values: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    changes_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # what differs from the previous check
