from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class VerificationMethod(str, enum.Enum):
    dns_txt = "dns_txt"
    html_file = "html_file"
    meta_tag = "meta_tag"


class WebsiteVerification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Proves domain control before recurring monitoring or any write access is
    granted (WEBSITE_CONNECTORS.md #1). A registered URL alone never implies
    verification.
    """

    __tablename__ = "website_verifications"

    website_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[VerificationMethod] = mapped_column(
        Enum(VerificationMethod, name="website_verification_method"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # RP13-004: throttles repeated confirm attempts against this one
    # verification row (a fresh row via /verify/instructions resets it).
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    website: Mapped["Website"] = relationship(back_populates="verifications")
