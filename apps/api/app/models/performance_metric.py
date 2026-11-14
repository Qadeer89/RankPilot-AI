from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Enum, Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PerformanceStrategy(str, enum.Enum):
    mobile = "mobile"
    desktop = "desktop"


class PerformanceMetric(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One PageSpeed Insights run for one page (RankPilot AI Phase 4
    "Core Web Vitals"). Lab data (a single simulated Lighthouse run) and
    field data (real-user CrUX data, which can genuinely not exist for
    a low-traffic page) are kept in distinct, independently-nullable
    columns -- never blended into one number, so a dashboard reading
    this can always tell which kind of data, if any, backs a value.

    Replaced per (page, strategy) on each sync, the same current-state
    contract PageImage already follows -- this is "the latest measured
    performance", not a time series (SiteHealthScore already provides
    the historical trend at the site level).
    """

    __tablename__ = "performance_metrics"
    __table_args__ = (
        UniqueConstraint("page_id", "strategy", name="uq_performance_metric_page_strategy"),
    )

    page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    strategy: Mapped[PerformanceStrategy] = mapped_column(
        Enum(PerformanceStrategy, name="performance_strategy"), nullable=False
    )
    lab_performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    lab_lcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    lab_cls: Mapped[float | None] = mapped_column(Float, nullable=True)
    lab_tbt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_lcp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_cls: Mapped[float | None] = mapped_column(Float, nullable=True)
    field_inp_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Lighthouse's own "opportunity" audits with nonzero estimated
    # savings (RankPilot AI Phase 4 "Performance Recommendations") --
    # Lighthouse's own findings, re-surfaced, not a RankPilot judgment
    # call. [] when Lighthouse found none, never a fabricated list.
    opportunities_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    page: Mapped["Page"] = relationship()
