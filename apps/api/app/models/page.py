from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IndexabilityState(str, enum.Enum):
    unknown = "unknown"
    indexable = "indexable"
    noindex = "noindex"
    blocked_by_robots = "blocked_by_robots"


class Page(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A discovered URL on a website, tracked across crawls (RP-0303, RP-0306)."""

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("website_id", "normalized_url", name="uq_page_website_url"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    normalized_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    indexability_state: Mapped[IndexabilityState] = mapped_column(
        Enum(IndexabilityState, name="page_indexability_state"),
        default=IndexabilityState.unknown,
        nullable=False,
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    website: Mapped["Website"] = relationship()
    snapshots: Mapped[list["PageSnapshot"]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )
