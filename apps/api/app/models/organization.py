from __future__ import annotations

import enum

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"
    deleted = "deleted"


class OrganizationPlan(str, enum.Enum):
    solo = "solo"
    business = "business"
    pro = "pro"
    agency = "agency"
    agency_plus = "agency_plus"


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    plan: Mapped[OrganizationPlan] = mapped_column(
        Enum(OrganizationPlan, name="organization_plan"), default=OrganizationPlan.solo, nullable=False
    )
    status: Mapped[OrganizationStatus] = mapped_column(
        Enum(OrganizationStatus, name="organization_status"),
        default=OrganizationStatus.active,
        nullable=False,
    )
    # Encrypted the same way OAuth/connector secrets are (app/core/encryption.py);
    # a Slack incoming-webhook URL lets anyone with it post into that channel.
    encrypted_slack_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    websites: Mapped[list["Website"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
