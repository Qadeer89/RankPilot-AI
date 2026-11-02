from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RollbackStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    unavailable = "unavailable"


class RollbackRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A rollback attempt for one change (RP-0707,
    SEO_AUTOMATION_ENGINE.md #8: "Never promise rollback when the
    connector cannot restore the prior state").
    """

    __tablename__ = "rollback_records"

    change_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("change_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rollback_method: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[RollbackStatus] = mapped_column(
        Enum(RollbackStatus, name="rollback_status"), default=RollbackStatus.pending, nullable=False
    )
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    change_record: Mapped["ChangeRecord"] = relationship()
