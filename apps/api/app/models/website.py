from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class VerificationStatus(str, enum.Enum):
    unverified = "unverified"
    pending = "pending"
    verified = "verified"
    failed = "failed"


class WebsitePlatform(str, enum.Enum):
    unknown = "unknown"
    wordpress = "wordpress"
    custom = "custom"


class WebsiteStatus(str, enum.Enum):
    active = "active"
    paused = "paused"
    deleted = "deleted"


class Website(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "websites"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canonical_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus, name="website_verification_status"),
        default=VerificationStatus.unverified,
        nullable=False,
    )
    platform: Mapped[WebsitePlatform] = mapped_column(
        Enum(WebsitePlatform, name="website_platform"), default=WebsitePlatform.unknown, nullable=False
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    automation_policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    crawl_budget: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    status: Mapped[WebsiteStatus] = mapped_column(
        Enum(WebsiteStatus, name="website_status"), default=WebsiteStatus.active, nullable=False
    )
    search_console_site_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="websites")
    verifications: Mapped[list["WebsiteVerification"]] = relationship(
        back_populates="website", cascade="all, delete-orphan"
    )
