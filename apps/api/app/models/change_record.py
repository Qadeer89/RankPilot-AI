from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.website_connection import ConnectorType


class ChangeActorType(str, enum.Enum):
    user = "user"
    system = "system"
    ai = "ai"


class ValidationStatus(str, enum.Enum):
    pending = "pending"
    passed = "passed"
    failed = "failed"


class ChangeRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Before/after evidence for one executed write (RP-0705,
    MASTER_SPEC.md acceptance criteria: "Every executed change has
    before/after records and validation results").
    """

    __tablename__ = "change_records"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pages.id", ondelete="SET NULL"), nullable=True
    )
    seo_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seo_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_type: Mapped[ConnectorType] = mapped_column(Enum(ConnectorType, name="connector_type"), nullable=False)
    before_state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    after_state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    actor_type: Mapped[ChangeActorType] = mapped_column(Enum(ChangeActorType, name="change_actor_type"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_status: Mapped[ValidationStatus] = mapped_column(
        Enum(ValidationStatus, name="validation_status"), default=ValidationStatus.pending, nullable=False
    )

    website: Mapped["Website"] = relationship()
    seo_task: Mapped["SEOTask"] = relationship()
