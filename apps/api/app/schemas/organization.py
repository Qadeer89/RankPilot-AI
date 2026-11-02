import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    status: str

    model_config = {"from_attributes": True}


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str


class OrganizationSettingsUpdateRequest(BaseModel):
    slack_webhook_url: str | None = Field(default=None, max_length=2048)


class SlackTestResultResponse(BaseModel):
    status: str


class WebsiteOverviewRow(BaseModel):
    """One row of the agency multi-client overview (one per website in the
    organization): just enough to triage which client sites need
    attention without opening each one.
    """

    website_id: uuid.UUID
    display_name: str
    hostname: str
    verification_status: str
    status: str
    open_findings_count: int
    open_opportunities_count: int
    pending_tasks_count: int
    last_crawl_at: datetime | None
    last_crawl_status: str | None
