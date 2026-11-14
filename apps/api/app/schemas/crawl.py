import uuid
from datetime import datetime

from pydantic import BaseModel


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
