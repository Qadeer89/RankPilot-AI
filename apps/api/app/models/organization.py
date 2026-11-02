from __future__ import annotations

import enum

from sqlalchemy import Enum, String
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

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    websites: Mapped[list["Website"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
