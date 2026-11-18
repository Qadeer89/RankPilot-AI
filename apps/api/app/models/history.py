"""Permanent, per-project SEO history (docs/GROWTH_ENGINE_GAP_ANALYSIS.md, part 2).

Design rules that these tables enforce or make possible:

* **Snapshots are immutable.** A database trigger rejects any UPDATE of `project_snapshots`, so neither a bug nor a
  later analysis can rewrite what a project looked like. The first completed analysis is the baseline
  (`is_baseline`, at most one per project, enforced by a partial unique index).
* **No duplicate snapshots.** `(website_id, idempotency_key)` is unique: the same completed run can never produce
  two snapshots, while a new run always produces a new one.
* **Nothing is invented.** Where no data exists the summary says "not available" with the reason; numbers are never
  defaulted to zero. Every stored metric records its source, date range and whether it was imported history or
  collected by RankPilot.
* **Tenant isolation.** Every row carries `website_id` (and `organization_id` where rows are listed across
  projects) and is read only through tenant-scoped queries.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

SNAPSHOT_TYPES = ("crawl", "gsc", "ga4", "validation", "product", "collection")
SNAPSHOT_STATUSES = ("completed", "partial", "failed")


class ProjectSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_snapshots"
    __table_args__ = (
        UniqueConstraint("website_id", "idempotency_key", name="uq_project_snapshot_idempotency"),
        Index("uq_project_snapshot_one_baseline", "website_id", unique=True, postgresql_where=text("is_baseline")),
        Index("ix_project_snapshot_site_time", "website_id", "created_at"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    snapshot_type: Mapped[str] = mapped_column(String(24), nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="completed", nullable=False)
    partial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True when the snapshot was rebuilt later from aggregates that were stored at the time (e.g. a health score)
    # because the full detail of that run was not kept. It is labelled as such everywhere.
    reconstructed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    crawl_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("crawl_jobs.id", ondelete="SET NULL"), nullable=True)
    analysis_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(32), nullable=False)
    crawl_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    data_sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class SnapshotFindings(Base):
    """The issues that were open when a snapshot was taken (compact: page id, rule, severity). Findings themselves
    are updated in place as the site changes, so this is the only record of "what was wrong then"."""

    __tablename__ = "project_snapshot_findings"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("project_snapshots.id", ondelete="CASCADE"), primary_key=True)
    open_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # [[page_id|null, rule_code, severity], ...]


class ProjectMetricHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Daily Search Console totals for a property (or one country/device), kept as their own time series.

    These are the property-level numbers Search Console itself reports, including queries it anonymises, which the
    query-level rows in `keyword_observations` cannot add up to. `origin` says whether the day came from the first
    back-fill of Google's available history ("imported") or from RankPilot's own regular collection ("collected")."""

    __tablename__ = "project_metric_history"
    __table_args__ = (
        UniqueConstraint("website_id", "source", "scope_type", "scope_value", "metric_date", name="uq_project_metric_day"),
        Index("ix_project_metric_lookup", "website_id", "source", "scope_type", "metric_date"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # google_search_console
    scope_type: Mapped[str] = mapped_column(String(16), default="property", nullable=False)  # property | country | device
    scope_value: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    ctr: Mapped[float | None] = mapped_column(Float, nullable=True)
    position: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # imported | collected
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectActivityEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "project_activity_events"
    __table_args__ = (
        Index("uq_project_activity_dedupe", "website_id", "dedupe_key", unique=True, postgresql_where=text("dedupe_key IS NOT NULL")),
        Index("ix_project_activity_site_time", "website_id", "occurred_at"),
    )

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)


class DataSourceSyncHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_source_sync_history"
    __table_args__ = (Index("ix_sync_history_site_source_time", "website_id", "source", "started_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # crawler | google_search_console | ga4 | shopify
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success | partial | failed | skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rows_synced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    range_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    range_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class RecommendationHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only log of every lifecycle step of a recommendation, across the different recommendation systems.
    IDENTIFIED -> RECOMMENDED -> APPROVED -> IMPLEMENTED -> VALIDATED -> MONITORING, plus rejected, dismissed,
    failed and reopened."""

    __tablename__ = "recommendation_history"
    __table_args__ = (Index("ix_recommendation_history_ref", "website_id", "kind", "ref_id", "occurred_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # growth_recommendation | ai_search_finding | seo_task | seo_opportunity
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(24), nullable=False)
    previous_stage: Mapped[str | None] = mapped_column(String(24), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    detail_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Shopify product as it was at one snapshot. Filled by the Shopify catalog phase."""

    __tablename__ = "product_snapshots"
    __table_args__ = (Index("ix_product_snapshot_lookup", "website_id", "external_id", "captured_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("project_snapshots.id", ondelete="CASCADE"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_alts: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    issues_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CollectionSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Shopify collection as it was at one snapshot. Filled by the Shopify catalog phase."""

    __tablename__ = "collection_snapshots"
    __table_args__ = (Index("ix_collection_snapshot_lookup", "website_id", "external_id", "captured_at"),)

    website_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("websites.id", ondelete="CASCADE"), nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("project_snapshots.id", ondelete="CASCADE"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    seo_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    meta_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issues_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
