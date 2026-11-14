from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ExternalLinkStatus(str, enum.Enum):
    # Not yet (re-)checked this crawl, or past the per-crawl verification
    # cap -- distinct from "ok" so a dashboard never implies a link was
    # confirmed healthy when it was simply never looked at
    # (app/crawler/external_links.py).
    unchecked = "unchecked"
    ok = "ok"
    redirect = "redirect"
    broken = "broken"


class PageExternalLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An <a href> observed on a page's latest crawl that points off-site
    (RP-0303 extension, RankPilot AI Phase 2 "External Link Audit").

    Rows are replaced wholesale for a page on each crawl that refetches
    it, the same current-state contract PageImage already follows.
    """

    __tablename__ = "page_external_links"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    is_nofollow: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_ugc: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    link_status: Mapped[ExternalLinkStatus] = mapped_column(
        Enum(ExternalLinkStatus, name="page_external_link_status"),
        default=ExternalLinkStatus.unchecked,
        nullable=False,
    )

    page: Mapped["Page"] = relationship()
