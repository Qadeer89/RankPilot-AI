from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import Date, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One metered usage line for one website on one day (RP-0806).

    `metric` is a short code (e.g. "pages_crawled", "ai_proposals",
    "ai_cost_usd") rather than an enum, so new metrics don't need a
    migration.
    """

    __tablename__ = "usage_records"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=True, index=True
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    period_start: Mapped[date_type] = mapped_column(Date, nullable=False, index=True)

    organization: Mapped["Organization"] = relationship()
    website: Mapped["Website | None"] = relationship()
