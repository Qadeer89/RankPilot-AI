from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AdminSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A runtime override of one whitelisted setting, changed only by the Super Admin (always audited).
    No row means the environment/default value applies. Secrets never live here."""

    __tablename__ = "admin_settings"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
