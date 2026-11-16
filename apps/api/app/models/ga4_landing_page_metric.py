from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Ga4LandingPageMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One day of GA4 organic-search sessions for one landing page.
    These are engagement figures from Analytics, not ranking data, and
    are kept apart from Search Console metrics everywhere they are shown.
    `page_id` is set when the landing path matches a crawled page.
    """

    __tablename__ = "ga4_landing_page_metrics"
    __table_args__ = (UniqueConstraint("website_id", "landing_page", "date", name="uq_ga4_landing_page_identity"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    landing_page: Mapped[str] = mapped_column(String(2048), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    engaged_sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
