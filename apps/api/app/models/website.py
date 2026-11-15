from __future__ import annotations

import enum
import uuid

from sqlalchemy import JSON, Boolean, Enum, Float, ForeignKey, Integer, String
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


class AutomationMode(str, enum.Enum):
    """Three clearly-defined automation modes (RankPilot AI Phase 8
    "Autopilot Controls"), replacing what was previously only an
    implicit "copilot with an auto-execute dial" behavior.

    audit: detect and report only -- the automatic background pipeline
    (app/opportunities/auto_pipeline.py) never drafts an AI proposal,
    let alone executes a write. A human can still manually request a
    proposal/task through the API, but it always requires approval
    (never auto-executes), same as copilot below.
    copilot: AI drafts fixes automatically; every task always requires
    approval regardless of risk tier or per-category auto-execute
    settings -- never auto-executes.
    autopilot: the original behavior, unchanged for backward
    compatibility -- tier-1 changes auto-execute per
    automation_policy's blanket flag or per-category opt-in
    (app/execution/policy.py); tier 2+ always needs approval.
    """

    audit = "audit"
    copilot = "copilot"
    autopilot = "autopilot"


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
    # Write-specific kill switch (CW-004, custom-website-write addendum §9):
    # distinct from `status`/paused, which also stops crawling. This lets a
    # site keep being monitored/crawled while new connector writes are
    # blocked outright -- execute_task() checks it before every write.
    writes_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    search_console_site_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ga4_property_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Deployment/webhook-triggered re-crawl (RankPilot AI Phase 7 "Change
    # Detection"). A hash, not the plaintext secret, the same pattern as
    # WebsiteVerification.token_hash -- the plaintext is only ever shown
    # once, at rotation time, and this is compared via hash_token().
    # None until an admin rotates it for the first time, so the webhook
    # endpoint stays disabled by default rather than accepting an unset
    # or empty secret.
    deploy_webhook_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    automation_mode: Mapped[AutomationMode] = mapped_column(
        Enum(AutomationMode, name="website_automation_mode"), default=AutomationMode.autopilot, nullable=False
    )
    # How often this website should be re-crawled on the daily schedule
    # (RankPilot AI Phase 8 "User Controls" -- configure crawl frequency).
    # The scheduler task still ticks hourly; this is compared against the
    # most recent crawl's start time, not a separate per-website cron.
    crawl_frequency_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    # Overrides config.ai_daily_budget_usd_per_site for this one website
    # when set; None (the default) means "use the global per-site default".
    ai_daily_budget_usd_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Country-based SEO intelligence (SEO Growth Engine spec, section 5
    # "Country-Based SEO Intelligence"). ISO 3166-1 alpha-2 for countries
    # (matching Search Console's own country dimension values), ISO 639-1
    # for language. None/empty means "no country target configured yet" --
    # never a fabricated default market.
    target_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    additional_target_countries: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    target_language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_city: Mapped[str | None] = mapped_column(String(128), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="websites")
    verifications: Mapped[list["WebsiteVerification"]] = relationship(
        back_populates="website", cascade="all, delete-orphan"
    )

    @property
    def all_target_countries(self) -> list[str]:
        """Primary target country plus any additional ones, de-duplicated,
        primary first. Empty when no country has been configured yet.
        """
        countries = [self.target_country] if self.target_country else []
        for country in self.additional_target_countries:
            if country not in countries:
                countries.append(country)
        return countries
