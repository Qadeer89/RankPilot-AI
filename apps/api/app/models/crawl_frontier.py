from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FrontierState(str, enum.Enum):
    pending = "pending"
    fetched = "fetched"
    skipped = "skipped"
    error = "error"


class CrawlFrontier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """URLs discovered but not yet (or no longer) needing a fetch (RP-0306).

    Persisted so a crawl can resume across worker restarts and so repeat
    discoveries of the same URL within a crawl are deduplicated.
    """

    __tablename__ = "crawl_frontier"
    __table_args__ = (UniqueConstraint("website_id", "url", name="uq_frontier_website_url"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_from: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    state: Mapped[FrontierState] = mapped_column(
        Enum(FrontierState, name="crawl_frontier_state"), default=FrontierState.pending, nullable=False
    )
    next_fetch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    website: Mapped["Website"] = relationship()
