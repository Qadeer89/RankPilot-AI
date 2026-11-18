from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BusinessProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What the business is, in the owner's words. Target countries and languages already live on the website
    (target_country, additional_target_countries, target_language) and are not duplicated here.

    `ai_suggestions` holds what the AI proposed from the website's own text. It is only ever a suggestion: the
    confirmed fields change only when a person saves them, and `confirmed_at` records that they did."""

    __tablename__ = "business_profiles"

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), unique=True, nullable=False)
    business_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    offerings: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    target_customers: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    known_competitors: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    ai_suggestions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
