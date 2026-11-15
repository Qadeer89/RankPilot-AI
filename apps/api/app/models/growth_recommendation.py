"""Evidence-backed SEO growth recommendations (SEO Growth Engine spec
section 7). Deliberately a separate table from SEOOpportunity: open
SEOOpportunity rows feed the automatic AI-fix pipeline
(app/opportunities/auto_pipeline.py), and nothing here has an existing
automated fix operation -- these are strategic recommendations a
person approves and acts on.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RecommendationLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RecommendationStatus(str, enum.Enum):
    open = "open"
    approved = "approved"
    rejected = "rejected"
    done = "done"


class GrowthRecommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "growth_recommendations"
    __table_args__ = (UniqueConstraint("website_id", "dedupe_key", name="uq_growth_recommendation_identity"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(600), nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(600), nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"), nullable=True
    )
    proposed_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    target_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(512), nullable=True)
    data_source: Mapped[str] = mapped_column(String(64), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    # Always qualitative: nothing here can support a numeric traffic or
    # ranking forecast.
    expected_benefit: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[RecommendationLevel] = mapped_column(
        Enum(RecommendationLevel, name="recommendation_level"), nullable=False
    )
    difficulty: Mapped[RecommendationLevel] = mapped_column(
        Enum(RecommendationLevel, name="recommendation_level"), nullable=False
    )
    automation_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validation_method: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus, name="recommendation_status"), default=RecommendationStatus.open, nullable=False
    )

    website: Mapped["Website"] = relationship()
