from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OAuthProvider(str, enum.Enum):
    google_search_console = "google_search_console"
    google_analytics = "google_analytics"


class OAuthConnectionStatus(str, enum.Enum):
    connected = "connected"
    disconnected = "disconnected"
    error = "error"


class OAuthConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An organization-level OAuth grant for an external provider
    (RP-0501). The token itself is never stored in plaintext — see
    app/core/encryption.py.
    """

    __tablename__ = "oauth_connections"
    __table_args__ = (UniqueConstraint("organization_id", "provider", name="uq_oauth_org_provider"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[OAuthProvider] = mapped_column(Enum(OAuthProvider, name="oauth_provider"), nullable=False)
    encrypted_token_reference: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[OAuthConnectionStatus] = mapped_column(
        Enum(OAuthConnectionStatus, name="oauth_connection_status"),
        default=OAuthConnectionStatus.connected,
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
