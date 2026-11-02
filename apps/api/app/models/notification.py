from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NotificationChannel(str, enum.Enum):
    email = "email"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"
    skipped_not_configured = "skipped_not_configured"


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A record of one notification attempt (RP-0804). Recorded even when
    the channel isn't configured, so "why didn't I get an email" has an
    answer in the audit trail rather than a silent gap.
    """

    __tablename__ = "notifications"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    website_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"), default=NotificationStatus.pending, nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
    website: Mapped["Website | None"] = relationship()
