from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RenderStatus(str, enum.Enum):
    ok = "ok"
    failed = "failed"


class PageRenderResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The outcome of attempting headless-browser rendering for one page
    this crawl flagged as JS-dependent (RankPilot AI Phase 4).

    Only ever created for a page app/crawler/render.py's heuristic
    selected -- most pages never get a row here, by design. Replaced
    wholesale for a page on each crawl that re-attempts rendering for
    it, the same current-state contract PageImage already follows.
    """

    __tablename__ = "page_render_results"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    render_status: Mapped[RenderStatus] = mapped_column(Enum(RenderStatus, name="page_render_status"), nullable=False)
    raw_word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rendered_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    page: Mapped["Page"] = relationship()
