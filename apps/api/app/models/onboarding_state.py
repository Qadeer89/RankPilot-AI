from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OnboardingState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tracks only what can't be derived from the rest of the schema --
    which optional steps the organization explicitly skipped, and
    whether they've dismissed the welcome screen / finished the guide.

    Every *mandatory* step's completion (website added, verified, first
    crawl run, etc.) is computed live from the real data it already
    has (Website, WebsiteConnection, CrawlJob, ...) rather than
    duplicated into a flag here -- a flag would drift out of sync with
    reality (e.g. a user disconnects GSC after the step was marked
    done) and this project's own principle is "no fabricated state."
    """

    __tablename__ = "onboarding_states"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    # Step keys the org explicitly chose to skip (e.g. "cms", "gsc",
    # "ga4", "notifications") -- only steps the spec marks optional are
    # ever accepted here; see onboarding.py's STEP_DEFINITIONS.
    skipped_steps: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    welcomed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["Organization"] = relationship()
