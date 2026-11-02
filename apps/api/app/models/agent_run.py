from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AgentType(str, enum.Enum):
    content_optimization = "content_optimization"


class AgentRunStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Audit trail and cost ledger for every AI call (RP-0607,
    AI_AGENT_SPECIFICATION.md #7: "Log token usage and estimated cost by
    organization/site/task").
    """

    __tablename__ = "agent_runs"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_type: Mapped[AgentType] = mapped_column(Enum(AgentType, name="agent_type"), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"), default=AgentRunStatus.pending, nullable=False
    )
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_reference: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    website: Mapped["Website"] = relationship()
