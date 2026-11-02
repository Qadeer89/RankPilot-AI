from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ConnectorType(str, enum.Enum):
    wordpress = "wordpress"


class WebsiteConnectionStatus(str, enum.Enum):
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class WebsiteConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Write-access grant for one website (RP-0703, WEBSITE_CONNECTORS.md
    #1: "A website URL alone never grants write permission").
    """

    __tablename__ = "website_connections"
    __table_args__ = (UniqueConstraint("website_id", "connector_type", name="uq_connection_website_type"),)

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_type: Mapped[ConnectorType] = mapped_column(Enum(ConnectorType, name="connector_type"), nullable=False)
    encrypted_secret_reference: Mapped[str] = mapped_column(Text, nullable=False)
    granted_scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[WebsiteConnectionStatus] = mapped_column(
        Enum(WebsiteConnectionStatus, name="website_connection_status"),
        default=WebsiteConnectionStatus.connected,
        nullable=False,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    website: Mapped["Website"] = relationship()
