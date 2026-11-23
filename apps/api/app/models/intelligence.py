"""Append-only results of the free-first intelligence analyses (content, technical, local lab measurement, competitor structure).
One generic table so each analysis keeps a history without a table per module; `payload_json` holds the full, labelled result."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IntelligenceRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "intelligence_runs"
    __table_args__ = (Index("ix_intelligence_runs_site_kind_time", "website_id", "kind", "computed_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # content | technical | lab_performance | competitor_structure
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
