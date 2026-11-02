from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FindingSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class FindingStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


class SEOFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A deterministic rule-engine finding, backed by evidence (RP-0407).

    Findings persist across crawls: a rule firing again on the same page just
    bumps `last_detected_at`; a rule that stops firing resolves the finding
    rather than deleting it, preserving history.
    """

    __tablename__ = "seo_findings"
    __table_args__ = (
        UniqueConstraint("website_id", "page_id", "rule_code", name="uq_finding_website_page_rule"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, name="finding_severity"), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, name="finding_status"), default=FindingStatus.open, nullable=False
    )

    website: Mapped["Website"] = relationship()
    page: Mapped["Page | None"] = relationship()
