from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SEOTaskStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    executing = "executing"
    completed = "completed"
    failed = "failed"


class ApprovalStatus(str, enum.Enum):
    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class SEOTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One concrete, bounded change derived from an AI proposal, gated by
    risk tier and approval (RP-0701, RP-0702, SEO_AUTOMATION_ENGINE.md #4).
    """

    __tablename__ = "seo_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_seo_task_idempotency_key"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seo_opportunities.id", ondelete="SET NULL"), nullable=True
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[SEOTaskStatus] = mapped_column(
        Enum(SEOTaskStatus, name="seo_task_status"), default=SEOTaskStatus.pending, nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    risk_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_change_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"), default=ApprovalStatus.pending, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)

    website: Mapped["Website"] = relationship()
    opportunity: Mapped["SEOOpportunity | None"] = relationship()
