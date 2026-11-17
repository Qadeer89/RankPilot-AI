from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AiSearchFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One query the user chose to analyse: the analysis, the AI draft and its quality checks, the link to the
    shared recommendation, and what happened after it was applied.

    Search Console metrics are NOT stored here as a second copy of the truth (they live in KeywordObservation);
    `metrics_json` is a snapshot of what the person saw when they asked for the analysis, and `baseline_json`
    freezes the before-period at implementation time so later syncs cannot rewrite history."""

    __tablename__ = "ai_search_findings"
    __table_args__ = (UniqueConstraint("website_id", "query_key", "scope_country", name="uq_ai_search_finding_identity"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    query_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    scope_country: Mapped[str] = mapped_column(String(8), default="ALL", nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    categories: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score_factors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    content_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)  # public page text used as evidence (untrusted)
    answer_analysis: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    readiness_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    ai_status: Mapped[str] = mapped_column(String(24), default="none", nullable=False)  # none | ok | failed | unavailable | skipped
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    growth_recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("growth_recommendations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    implemented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    implemented_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    implementation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    live_check_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    baseline_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    monitoring_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
