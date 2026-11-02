from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Ga4DailyMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One day's GA4 sessions/users/conversions for a website (optional
    per MASTER_SPEC.md: "GA4 is optional"). Not in DATABASE_SCHEMA.md,
    which only sketches GA4 as a future table — see README deviations.
    """

    __tablename__ = "ga4_daily_metrics"
    __table_args__ = (UniqueConstraint("website_id", "date", name="uq_ga4_metric_website_date"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)
    sessions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_users: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="ga4", nullable=False)

    website: Mapped["Website"] = relationship()
