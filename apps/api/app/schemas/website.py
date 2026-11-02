import uuid

from pydantic import BaseModel, Field


class WebsiteCreateRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    display_name: str = Field(min_length=1, max_length=255)
    purpose: str = Field(default="owned_pilot_site", max_length=64)


class WebsiteResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    canonical_url: str
    hostname: str
    display_name: str
    verification_status: str
    platform: str
    crawl_budget: int
    status: str
    automation_policy: dict
    search_console_site_url: str | None

    model_config = {"from_attributes": True}


class WebsiteSettingsUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    crawl_budget: int | None = Field(default=None, ge=1, le=10000)
    auto_execute_risk_tier_1: bool | None = None


class VerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=1, max_length=255)


class VerificationInstructionsResponse(BaseModel):
    website_id: uuid.UUID
    method: str
    token: str
    instructions: str


class VerificationResultResponse(BaseModel):
    website_id: uuid.UUID
    verification_status: str
    verified: bool
    detail: str
