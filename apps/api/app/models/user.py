from __future__ import annotations

import enum

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class UserStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), default=UserStatus.active, nullable=False
    )
    # Platform-level admin (distinct from org-scoped MembershipRole):
    # manages the shared product knowledge base (Part 6 of the AI
    # Assistant spec). No self-service signup path -- granted directly
    # in the DB by whoever operates this deployment.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set only by following an emailed link (or by the server operator's script). Existing users stay
    # NULL: it is required for Super Admin access and nothing else.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")
