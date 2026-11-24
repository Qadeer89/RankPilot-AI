import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.execution import ChangeRecordResponse


class CrawlJobResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    trigger: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    pages_requested: int
    pages_fetched: int
    error_summary: str | None

    model_config = {"from_attributes": True}


class PageResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    canonical_url: str
    normalized_url: str
    last_status_code: int | None
    indexability_state: str
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class SiteHealthScoreResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    crawl_job_id: uuid.UUID
    overall_score: float | None
    technical_score: float | None
    on_page_score: float | None
    content_score: float | None
    performance_score: float | None
    critical_count: int
    warning_count: int
    info_count: int
    passed_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WebsiteOverviewResponse(BaseModel):
    """Site Overview (RankPilot AI Phase 6 "Advanced SEO Reporting").
    latest_health_score is None only when no crawl has completed yet.
    pages_indexed is None (not 0) when no URL Inspection data has been
    synced for this website at all -- distinct from "synced and found
    zero indexed pages", which would be a real, alarming 0.
    """

    pages_discovered: int
    pages_indexed: int | None
    # How many pages Google has actually been asked about so far (None when none yet). pages_indexed counts only these, so it is
    # "indexed out of checked", not "indexed out of all pages".
    pages_inspected: int | None = None
    indexing_last_checked_at: datetime | None = None
    pending_approvals: int
    latest_health_score: SiteHealthScoreResponse | None


class SEOFindingResponse(BaseModel):
    id: uuid.UUID
    website_id: uuid.UUID
    page_id: uuid.UUID | None
    rule_code: str
    severity: str
    confidence: float
    evidence_json: dict
    first_detected_at: datetime
    last_detected_at: datetime
    status: str

    model_config = {"from_attributes": True}


class PageSnapshotSummaryResponse(BaseModel):
    fetched_at: datetime
    status_code: int | None
    redirect_count: int
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    robots_directives: list
    heading_sequence_json: list
    structured_data_json: list
    word_count: int
    viewport_content: str | None
    rel_next_url: str | None
    rel_prev_url: str | None

    model_config = {"from_attributes": True}


class PageImageSummaryResponse(BaseModel):
    image_src: str | None
    alt_text: str | None
    has_alt: bool
    is_decorative: bool
    has_dimensions: bool
    image_status: str

    model_config = {"from_attributes": True}


class PageExternalLinkSummaryResponse(BaseModel):
    url: str
    is_nofollow: bool
    is_sponsored: bool
    is_ugc: bool
    link_status: str

    model_config = {"from_attributes": True}


class PerformanceMetricSummaryResponse(BaseModel):
    strategy: str
    lab_performance_score: float | None
    lab_lcp_ms: float | None
    lab_cls: float | None
    lab_tbt_ms: float | None
    field_lcp_ms: float | None
    field_cls: float | None
    field_inp_ms: float | None
    opportunities_json: list

    model_config = {"from_attributes": True}


class PageIndexingStatusSummaryResponse(BaseModel):
    verdict: str
    coverage_state: str | None
    indexing_state: str | None
    last_crawl_time: datetime | None
    google_canonical_url: str | None
    user_canonical_url: str | None
    mobile_usability_verdict: str | None
    mobile_usability_issues_json: list

    model_config = {"from_attributes": True}


class PageReportResponse(BaseModel):
    """Page-Level SEO Report (RankPilot AI Phase 6). Aggregates every
    per-page data source this codebase has into one call -- previously
    scattered across PageSnapshot/PageImage/PageExternalLink/
    PerformanceMetric/PageIndexingStatus with no single read endpoint.
    Each section is None/empty when genuinely not yet measured for
    this page (e.g. latest_snapshot is None before the first crawl,
    indexing_status is None until a Search Console URL Inspection sync
    has run) -- never a fabricated placeholder.
    """

    page: PageResponse
    latest_snapshot: PageSnapshotSummaryResponse | None
    images: list[PageImageSummaryResponse]
    external_links: list[PageExternalLinkSummaryResponse]
    performance: PerformanceMetricSummaryResponse | None
    indexing_status: PageIndexingStatusSummaryResponse | None
    findings: list[SEOFindingResponse]
    change_history: list[ChangeRecordResponse]
