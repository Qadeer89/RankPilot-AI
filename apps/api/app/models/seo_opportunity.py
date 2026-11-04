from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OpportunityStatus(str, enum.Enum):
    open = "open"
    dismissed = "dismissed"
    # The backing finding stopped recurring on its own (a false positive
    # was fixed, the page changed externally, re-crawl logic improved) --
    # RankPilot did not execute anything for it. Distinct from `completed`
    # so the UI never implies RankPilot fixed something it didn't touch.
    resolved = "resolved"
    # A task for this opportunity was executed through RankPilot and its
    # post-write validation passed (app/execution/service.py).
    completed = "completed"


class SEOOpportunity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A scored, actionable opportunity derived from findings (and, when
    connected, Search Console signals) (RP-0603, SEO_AUTOMATION_ENGINE.md
    #3). Scoring is deterministic; AI only explains and drafts
    (MASTER_SPEC.md "Global implementation rules").
    """

    __tablename__ = "seo_opportunities"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2048), nullable=False)
    impact_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    effort_estimate: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus, name="opportunity_status"), default=OpportunityStatus.open, nullable=False
    )

    website: Mapped["Website"] = relationship()
    page: Mapped["Page | None"] = relationship()

    @property
    def score(self) -> float:
        """Transparent, explainable score (SEO_AUTOMATION_ENGINE.md #3:
        "Show score components to avoid opaque AI rankings"). Higher impact
        and confidence raise the score; higher effort and risk lower it.
        """
        risk_penalty = 1.0 - (self.risk_tier * 0.15)
        effort_penalty = 1.0 / (1.0 + self.effort_estimate)
        return round(self.impact_estimate * self.confidence * effort_penalty * max(risk_penalty, 0.1), 4)
