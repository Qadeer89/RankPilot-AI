from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ImageStatus(str, enum.Enum):
    ok = "ok"
    missing_src = "missing_src"
    broken = "broken"
    unknown = "unknown"


class PageImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An <img> element observed on a page's latest crawl (RP-0303 extension).

    Rows are replaced wholesale for a page on each crawl that refetches it
    (app/crawler/orchestrator.py), so this always reflects the current HTML,
    not a history -- the same current-state contract Page itself follows.
    """

    __tablename__ = "page_images"

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_src: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    alt_text: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    has_alt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_decorative: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_dimensions: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_status: Mapped[ImageStatus] = mapped_column(
        Enum(ImageStatus, name="page_image_status"), default=ImageStatus.unknown, nullable=False
    )

    page: Mapped["Page"] = relationship()
