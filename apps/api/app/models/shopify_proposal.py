from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ShopifyProposal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One proposed change to one Shopify product/collection SEO field.

    Lifecycle: draft -> approved -> applied (verified or not) | failed; or draft -> rejected. Nothing reaches the store
    before a person approves it, and `before_value` is kept so the change can be rolled back."""

    __tablename__ = "shopify_proposals"
    __table_args__ = (Index("ix_shopify_proposal_site_status", "website_id", "status"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(16), nullable=False)  # products | collections
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    field: Mapped[str] = mapped_column(String(24), nullable=False)  # seo_title | meta_description
    before_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    quality_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verification_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
