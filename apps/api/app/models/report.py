from __future__ import annotations

import enum
import uuid
from datetime import date as date_type

from sqlalchemy import JSON, Date, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ReportType(str, enum.Enum):
    weekly = "weekly"


class Report(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A generated activity report (RP-0805).

    DATABASE_SCHEMA.md's `storage_reference` is a pointer to an external
    object store; this MVP has none, so the report content is stored
    inline as `content_json` instead (see README deviations).
    """

    __tablename__ = "reports"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date_type] = mapped_column(Date, nullable=False)
    period_end: Mapped[date_type] = mapped_column(Date, nullable=False)
    report_type: Mapped[ReportType] = mapped_column(Enum(ReportType, name="report_type"), nullable=False)
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    organization: Mapped["Organization"] = relationship()
    website: Mapped["Website"] = relationship()
